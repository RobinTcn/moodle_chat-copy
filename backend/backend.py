# backend.py
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
import os
import re
import logging
import asyncio
import datetime
import time

# Load .env file if present (developer convenience). Requires python-dotenv in requirements.
try:
    from dotenv import load_dotenv
    # load .env from backend directory (where this file lives)
    load_dotenv()
except Exception:
    # If python-dotenv isn't installed, that's okay — environment variables may be set elsewhere.
    pass

# Note: selenium and bs4 imports are moved into the scraping function so the
# FastAPI app can start even when Selenium/chromedriver aren't installed.

TARGET = "https://lernen.min.uni-hamburg.de/my/"

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Frontend erlaubt
    allow_methods=["*"],
    allow_headers=["*"]
)

class ChatRequest(BaseModel):
    message: str
    username: str
    password: str

def scrape_moodle_text(username, password, headless=True, max_wait=25):
    # Import heavy/optional deps here so the app can still start without them.
    try:
        from selenium import webdriver
        from selenium.webdriver.common.by import By
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.common.exceptions import TimeoutException
        from bs4 import BeautifulSoup
    except Exception as e:
        # Return a clear message the frontend can display instead of crashing.
        return f"Selenium/bs4 nicht verfügbar: {e}. Installiere 'selenium' und 'beautifulsoup4' und einen passenden ChromeDriver, oder starte den Server mit den Abhängigkeiten." 

    options = Options()
    if headless:
        # older/newer chrome headless flags differ; this should be broadly compatible
        options.add_argument("--headless")
    try:
        driver = webdriver.Chrome(options=options)
    except Exception as e:
        return f"Chrome WebDriver nicht gefunden oder konnte nicht gestartet werden: {e}"

    wait = WebDriverWait(driver, max_wait)
    try:
        driver.get(TARGET)

        # Login Button - try to click, but handle overlays/cookie popups that may intercept clicks
        try:
            login_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//a[contains(., 'Login') or contains(., 'Anmelden')]") ))

            # Helper: attempt several click strategies to avoid ElementClickInterceptedException
            def try_click(element):
                try:
                    # preferred: javascript click (bypasses some overlays)
                    driver.execute_script("arguments[0].click();", element)
                    return True
                except Exception:
                    try:
                        element.click()
                        return True
                    except Exception:
                        return False

            # If a cookie/privacy popup blocks clicks, try to close it first
            try:
                # common eupopup cookie button
                popup_btns = driver.find_elements(By.CSS_SELECTOR, ".eupopup-button, .eupopup-accept, button[aria-label*='Akzeptieren'], button[data-cookieaccept]")
                if popup_btns:
                    for b in popup_btns:
                        try:
                            driver.execute_script("arguments[0].click();", b)
                        except Exception:
                            try:
                                b.click()
                            except Exception:
                                pass
            except Exception:
                pass

            # finally try to click the login button
            clicked = try_click(login_btn)
            if not clicked:
                # as a last resort, scroll into view and try again
                try:
                    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", login_btn)
                    driver.execute_script("arguments[0].click();", login_btn)
                except Exception:
                    pass
        except TimeoutException:
            pass

        # Username/Passwort
        user_field = wait.until(EC.presence_of_element_located((By.NAME, "j_username")))
        pass_field = wait.until(EC.presence_of_element_located((By.NAME, "j_password")))
        user_field.send_keys(username)
        pass_field.send_keys(password)
        submit_btn = driver.find_element(By.XPATH, "//button[@name='_eventId_proceed' or contains(., 'Anmelden')]")
        submit_btn.click()

        # 2FA (FIDO)
        try:
            fido_radio = wait.until(EC.element_to_be_clickable((By.XPATH, "//input[@name='2fa_method' and @value='fido']")))
            driver.execute_script("arguments[0].click();", fido_radio)
            continue_btn = wait.until(EC.element_to_be_clickable(
                (By.XPATH, "//button[contains(@class, 'calltoaction') and contains(@class, 'mfa_login')]") ))
            driver.execute_script("arguments[0].click();", continue_btn)
        except TimeoutException:
            pass

        # Warte auf Aktuelle Termine
        wait.until(EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'Aktuelle Termine')]") ))

        # Ensure the page is fully loaded before capturing the HTML.
        # 1) wait for document.readyState == 'complete'
        # 2) if jQuery is present, wait until there are no active ajax requests
        try:
            wait.until(lambda d: d.execute_script("return document.readyState") == 'complete')
            # give a tiny buffer for any final async rendering
            time.sleep(0.25)
            try:
                wait.until(lambda d: d.execute_script("return (typeof jQuery !== 'undefined') ? (jQuery.active === 0) : true"))
            except Exception:
                # jQuery check is optional; ignore if it times out or jQuery not present
                pass
        except Exception:
            # If waiting for readyState times out, continue anyway but log for debugging
            logging.info("Wartezeit für vollständiges Laden der Seite überschritten, fahre mit Erfassen fort.")

        html = driver.page_source

        # Ergänze den sichtbaren Text (für Fälle, in denen Termine als Text sichtbar sind)
        soup = BeautifulSoup(html, "html.parser")
        visible_text = soup.get_text(separator="\n", strip=True)

        # Versuche, den Abschnitt zwischen 'Aktuelle Termine' und 'Zum Kalender' zu extrahieren
        match = re.search(r"(?<=Aktuelle Termine)(.*?)(?=Zum Kalender)", visible_text, re.DOTALL)
        if match:
            block = match.group(1).strip()
            # Remove leading accessibility/skip-link words like 'überspringen' or 'zum inhalt springen'
            block = re.sub(r"(?i)^\s*(?:überspringen\b[:\-\–\—]?\s*|zum inhalt springen\b[:\-\–\—]?\s*|zum inhalt\b[:\-\–\—]?\s*)", "", block)
            block = re.sub(r"(?i)^\s*Aktuelle Termine\s*[:\-\–\—]?\s*", "", block)
        else:
            block = visible_text

        # Jetzt: parse mögliche Termin-Zeilen aus `block`.
        # Ziel: eine robuste Extraktion von Aktivität, Modul und Fälligkeitsdatum/-zeit
        month_map = {
            'januar':1,'februar':2,'märz':3,'maerz':3,'april':4,'mai':5,'juni':6,'juli':7,'august':8,'september':9,'oktober':10,'november':11,'dezember':12
        }

        def parse_line_into_entry(line: str):
            # Entferne überflüssige Whitespace
            s = re.sub(r"\s+", " ", line).strip()
            if not s:
                return None


            # Versuche, Aktivität und Kurs/Modul zu ermitteln
            activity = ''
            course = ''

            # Split before ' ist ' or before the date if present
            split_point = None
            m_ist = re.search(r"\bist\b|\bist\s+am\b|\bfällig\b", s, re.I)
            if m_ist:
                split_point = m_ist.start()

            left = s if split_point is None else s[:split_point].strip()

            # Suche nach gängigen Trennwörtern (in, im, für, vom, von, aus)
            sep = re.search(r"\b(in|im|für|vom|von|aus)\b", left, re.I)
            if sep:
                # activity = text before separator; course = text after
                activity = left[:sep.start()].strip(" -:\t")
                course = left[sep.end():].strip(" -:\t")
            else:
                # Try other separators like ' - '
                if ' - ' in left:
                    parts = left.split(' - ', 1)
                    activity = parts[0].strip()
                    course = parts[1].strip()
                else:
                    activity = left

            # Cleanup words like leading 'Aktivität' etc.
            activity = re.sub(r"(?i)^Aktivit\w+\s*[:\-\–\—]?\s*", "", activity).strip()

            return {
                'activity': activity or None,
                'course': course or None,
                'original': s
            }

        entries = []
        # Zerlege Block in Zeilen und untersuche jede
        for line in block.splitlines():
            # pick lines containing keyword 'fällig' or a date pattern
            lower_line = line.lower()
            # filter out obvious UI strings (e.g. 'Überfällig Filteroption')
            if 'filteroption' in lower_line or lower_line.strip() == 'überfällig' or lower_line.strip().startswith('überfällig filter'):
                continue
            if 'fällig' in lower_line or re.search(r"\d{1,2}\.\s*[A-Za-zÄÖÜäöü]+\s+\d{4}", line):
                e = parse_line_into_entry(line)
                if e:
                    entries.append(e)

        
        # Baue die Rückgabe-Textdarstellung, die an Gemini geschickt wird
        if entries:
            lines = []
            for e in entries:
                parts = []
                if e.get('activity'):
                    parts.append(f"Aktivität: {e['activity']}")
                if e.get('course'):
                    parts.append(f"Modul: {e['course']}")
                if e.get('due_iso'):
                    parts.append(f"Fällig: {e['due_iso']}")
                else:
                    # If no ISO date, include original text to preserve info
                    parts.append(f"Info: {e['original']}")
                lines.append(' | '.join(parts))
            termine_text = "\n".join(lines)
            return termine_text
        else:
            return visible_text

    except Exception as e:
        return f"Fehler beim Scraping: {e}"

    finally:
        try:
            driver.quit()
        except Exception:
            pass

def ask_gemini(termine: str) -> str:
    """Send a prompt to Gemini and return the response text."""
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        return "Fehler: 'google' Paket nicht installiert."

    client = genai.Client()
    response = client.models.generate_content(
        model="gemini-2.0-flash", 
        config=types.GenerateContentConfig(system_instruction="Du bist ein hilfreicher Assistent, der Moodle-Termine für den Benutzer zusammenfasst."),
        contents="Hier sind meine Moodle-Termine:\n" + termine 
            + "Beginne die Nachricht mit 'Hier sind deine Moodle-Termine:'. Heute ist der " + datetime.date.today().isoformat() 
            + ". Nenne die Termine abhängig vom heutigen Datum (z.B. 'morgen', 'in zwei Tagen'). Gib auch immer das jeweilige Modul für die Termine an."
        )
    return response.text


async def determine_intent(message: str) -> str:
    """Asynchronously determine the user's intent by asking Gemini.

    Returns one of: 'get_appointments', 'greeting', 'help', 'unknown'.
    Retries on transient errors to be more robust when many requests arrive quickly.
    """
    msg = message.strip()
    labels = ["get_moodle_appointments", "get_stine_messages", "get_mail", "greeting", "help", "unknown"]

    prompt = (
        "Classify the user's message into exactly one of the following intent labels: "
        + ", ".join(labels)
        + ".\nRespond with only the intent label (one of the labels) and nothing else.\n"
        + "If the user asks about Moodle appointments, deadlines or 'Termine', return 'get_moodle_appointments'.\n"
        + "If the user asks about Stine messages or 'Stine Nachrichten', return 'get_stine_messages'.\n"
        + "If the user asks about email or 'E-Mail', return 'get_mail'.\n"
        + "If the message is a greeting (hello, hi, hallo) return 'greeting'.\n"
        + "If the user asks for help or how to use the bot return 'help'.\n"
        + f"User message: \"{msg}\"\n"
    )

    # Blocking call will run in a thread to avoid blocking the event loop.
    def _call_genai(inner_prompt: str):
        try:
            from google import genai
        except Exception:
            raise
        client = genai.Client()
        return client.models.generate_content(model="gemini-2.0-flash", contents=inner_prompt)

    max_retries = 3
    backoff_base = 0.5
    for attempt in range(1, max_retries + 1):
        try:
            response = await asyncio.to_thread(_call_genai, prompt)
            # parse the model response robustly
            intent_text = ""
            if hasattr(response, 'text') and response.text:
                intent_text = response.text.strip().splitlines()[0].strip()
            if intent_text in labels:
                return intent_text
            for lab in labels:
                if lab in getattr(response, 'text', ''):
                    return lab
            logging.info("Gemini returned unexpected intent text (attempt %d): %s", attempt, getattr(response, 'text', response))
            # If model returned something unexpected, retry a couple times
        except Exception as e:
            logging.warning("Attempt %d: Error calling Gemini for intent detection: %s", attempt, e)

        # backoff before retrying
        if attempt < max_retries:
            await asyncio.sleep(backoff_base * (2 ** (attempt - 1)))

    # All retries failed or response couldn't be parsed -> fallback
    logging.error("Intent detection failed after %d attempts for message: %s", max_retries, msg)
    return "unknown"

@app.post("/chat")
async def chat(request: ChatRequest):
    # Use Gemini to classify the user's intent. If Gemini fails, determine_intent
    # will return 'unknown' and we fall back to a simple keyword check.
    intent = await determine_intent(request.message)
    # Route based on detected intent
    if intent == "get_moodle_appointments":
        try:
            termine = scrape_moodle_text(request.username, request.password)
            response = ask_gemini(termine)
            return {"response": response}
        except Exception as e:
            response = f"Fehler beim Abrufen: {e}"
            return {"response": response}
    elif intent == "get_stine_messages":
        return {"response": "Die Funktion zum Abrufen von Stine-Nachrichten ist noch nicht implementiert."}
    elif intent == "get_mail":
        return {"response": "Die Funktion zum Abrufen von E-Mails ist noch nicht implementiert."}
    elif intent == "greeting":
        return {"response": "Hallo! Ich kann dir bei Moodle-Terminen helfen. Frag z. B. 'Welche Termine habe ich?'"}
    elif intent == "help":
        return {"response": f"Du kannst nach 'Terminen' fragen. \n Formuliere z. B. 'Was sind meine Termine?'"}
    else:
        # As a safety net, also accept the old keyword check (keeps behaviour if Gemini fails)
        msg = request.message.lower()
        if "termin" in msg:
            try:
                termine = scrape_moodle_text(request.username, request.password)
                response = ask_gemini(termine)
                return {"response": response}
            except Exception as e:
                response = f"Fehler beim Abrufen: {e}"
                return {"response": response}
        return {"response": "Entschuldigung, ich habe dich nicht verstanden. Bitte frage nach Moodle-Terminen."}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def root():
    """Simple root page to avoid 404s when opening http://127.0.0.1:8000/ in a browser."""
    return HTMLResponse(
        "<html><head><title>Moodle Chat Backend</title></head><body>"
        "<h1>Moodle Chat Backend</h1>"
        "<p>Open the <a href='/docs'>API docs</a> to test endpoints or POST to <code>/chat</code>.</p>"
        "</body></html>"
    )


@app.get('/favicon.ico')
def favicon():
    """Return no content for favicon requests to avoid 404 noise in logs."""
    return Response(status_code=204)
