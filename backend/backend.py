# backend.py
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, Response, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
import os
import re
import logging
import asyncio
import datetime
import time
import threading
import sys
import webbrowser
import json
import hashlib
from pathlib import Path
from cryptography.fernet import Fernet

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
latestMessage = ""


# ============================================================================
# Secure Credential Storage (device-based encryption)
# ============================================================================

def _get_credentials_dir() -> Path:
    """Get the directory where encrypted credentials are stored."""
    # Use AppData on Windows, ~/.config on Linux/Mac
    if sys.platform == "win32":
        base = Path(os.getenv("APPDATA", os.path.expanduser("~")))
        cred_dir = base / "StudiBot"
    else:
        cred_dir = Path.home() / ".config" / "studibot"
    
    cred_dir.mkdir(parents=True, exist_ok=True)
    return cred_dir


def _get_device_key() -> bytes:
    """Generate a device-specific encryption key.
    
    This creates a consistent key based on machine-specific data.
    The key is derived from hardware/system identifiers.
    """
    # Combine multiple system identifiers for uniqueness
    identifiers = [
        os.getenv("COMPUTERNAME", ""),  # Windows
        os.getenv("HOSTNAME", ""),       # Linux/Mac
        os.getenv("USERNAME", ""),
        str(Path.home()),
    ]
    
    # Create a stable hash from identifiers
    combined = "|".join(identifiers).encode("utf-8")
    key_material = hashlib.sha256(combined).digest()
    
    # Fernet requires a base64-encoded 32-byte key
    import base64
    return base64.urlsafe_b64encode(key_material)


def _encrypt_data(data: dict) -> bytes:
    """Encrypt a dictionary to bytes using device-specific key."""
    key = _get_device_key()
    cipher = Fernet(key)
    json_data = json.dumps(data).encode("utf-8")
    return cipher.encrypt(json_data)


def _decrypt_data(encrypted: bytes) -> dict:
    """Decrypt bytes back to a dictionary."""
    key = _get_device_key()
    cipher = Fernet(key)
    json_data = cipher.decrypt(encrypted)
    return json.loads(json_data.decode("utf-8"))


def save_credentials(username: str, password: str, api_key: str) -> bool:
    """Save encrypted credentials to local file."""
    try:
        cred_file = _get_credentials_dir() / "credentials.enc"
        data = {
            "username": username,
            "password": password,
            "api_key": api_key,
        }
        encrypted = _encrypt_data(data)
        cred_file.write_bytes(encrypted)
        return True
    except Exception as e:
        logging.error(f"Failed to save credentials: {e}")
        return False


def load_credentials() -> Optional[dict]:
    """Load and decrypt credentials from local file."""
    try:
        cred_file = _get_credentials_dir() / "credentials.enc"
        if not cred_file.exists():
            return None
        encrypted = cred_file.read_bytes()
        return _decrypt_data(encrypted)
    except Exception as e:
        logging.error(f"Failed to load credentials: {e}")
        return None


def delete_credentials() -> bool:
    """Delete stored credentials file."""
    try:
        cred_file = _get_credentials_dir() / "credentials.enc"
        if cred_file.exists():
            cred_file.unlink()
        return True
    except Exception as e:
        logging.error(f"Failed to delete credentials: {e}")
        return False

def _resolve_frontend_dist() -> Optional[str]:
    """Locate the built frontend (Vite dist) folder for static serving.

    Supports running from source as well as PyInstaller onefile bundles (using _MEIPASS).
    Returns an absolute path or None if no build is found.
    """
    candidates = []

    # PyInstaller onefile extracts into a temp dir pointed to by _MEIPASS
    if getattr(sys, "_MEIPASS", None):
        base = sys._MEIPASS  # type: ignore[attr-defined]
        candidates.append(os.path.join(base, "frontend", "dist"))
        candidates.append(os.path.join(base, "dist"))

    here = os.path.abspath(os.path.dirname(__file__))
    project_root = os.path.abspath(os.path.join(here, os.pardir))
    candidates.append(os.path.join(here, "frontend", "dist"))
    candidates.append(os.path.join(project_root, "frontend", "dist"))
    candidates.append(os.path.join(project_root, "dist"))

    for path in candidates:
        index_path = os.path.join(path, "index.html")
        if os.path.isfile(index_path):
            return os.path.abspath(path)
    return None


FRONTEND_DIST = _resolve_frontend_dist()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Frontend erlaubt
    allow_methods=["*"],
    allow_headers=["*"]
)

# Simple in-memory conversation state to track when the bot asked the calendar question.
# Keyed by username -> { 'awaiting_calendar': bool, 'ts': float }
conversation_state = {}
state_lock = threading.Lock()
STATE_EXPIRY_SECONDS = 120  # consent expires after 2 minutes

if FRONTEND_DIST:
    assets_path = os.path.join(FRONTEND_DIST, "assets")
    if os.path.isdir(assets_path):
        app.mount("/assets", StaticFiles(directory=assets_path), name="assets")

class ChatRequest(BaseModel):
    message: str
    username: str
    password: str
    api_key: Optional[str] = None


class CredentialsSaveRequest(BaseModel):
    username: str
    password: str
    api_key: str


class CredentialsResponse(BaseModel):
    username: Optional[str] = None
    password: Optional[str] = None
    api_key: Optional[str] = None


def _pick_api_key(provided: Optional[str]) -> Optional[str]:
    key = (provided or "").strip()
    if key:
        return key
    env_key = os.getenv("OPENAI_API_KEY", "").strip()
    return env_key or None

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
        return visible_text

    except Exception as e:
        return f"Fehler beim Scraping: {e}"

    finally:
        try:
            driver.quit()
        except Exception:
            pass

def scrape_stine_exams(username, password):
    URL = "https://www.stine.uni-hamburg.de/scripts/mgrqispi.dll?APPNAME=CampusNet&PRGNAME=EXTERNALPAGES&ARGUMENTS=-N000000000000001,-N000265,-Astartseite"

    try:
        from selenium import webdriver
        from selenium.webdriver.common.by import By
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.common.exceptions import TimeoutException
        from bs4 import BeautifulSoup
    except Exception as e:
        return f"Selenium/bs4 nicht verfügbar: {e}. Installiere 'selenium' und 'beautifulsoup4' und einen passenden ChromeDriver, oder starte den Server mit den Abhängigkeiten."
    
    options = Options()
    options.add_argument("--headless")
    driver = webdriver.Chrome(options=options)
    wait = WebDriverWait(driver, 10)
    try:
        driver.get(URL)

        # click on the login button
        try:
            login_btn = wait.until(EC.element_to_be_clickable((By.XPATH, "//a[contains(., 'Login') or contains(., 'Anmelden')]") ))
            driver.execute_script("arguments[0].click();", login_btn)
        except TimeoutException:
            pass

        # click on UHH login
        try:
            uhh_link = wait.until(EC.element_to_be_clickable((By.XPATH, "//a[contains(@class, 'uhhshib')]") ))
            driver.execute_script("arguments[0].click();", uhh_link)
        except TimeoutException:
            pass


        # Login
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
            # No FIDO prompt — continue anyway
            pass

        # Try to navigate to the 'Meine Prüfungen' page. Prefer following the anchor href
        # (the submenu contains absolute URLs) and fall back to clicking if necessary.
        try:
            exams_elem = wait.until(EC.presence_of_element_located((By.XPATH, "//a[contains(., 'Meine Prüfungen')]") ))
            href = exams_elem.get_attribute("href")
            if href:
                try:
                    driver.get(href)
                    # wait for the target page to load
                    try:
                        wait.until(lambda d: d.execute_script("return document.readyState") == 'complete')
                    except Exception:
                        time.sleep(0.5)
                except Exception:
                    # navigation failed; try clicking as a fallback
                    try:
                        driver.execute_script("arguments[0].click();", exams_elem)
                    except Exception:
                        pass
            else:
                # no href present — try to open the parent menu then click
                try:
                    studie_menu = wait.until(EC.element_to_be_clickable((By.XPATH, "//a[contains(., 'Studium')]") ))
                    driver.execute_script("arguments[0].click();", studie_menu)
                except Exception:
                    pass
                try:
                    exams_click = wait.until(EC.element_to_be_clickable((By.XPATH, "//a[contains(., 'Meine Prüfungen')]") ))
                    driver.execute_script("arguments[0].click();", exams_click)
                except Exception:
                    pass
        except TimeoutException:
            # Couldn't find the element by text — try to locate by href pattern (MYEXAMS) as a fallback
            try:
                exams_elem = driver.find_element(By.XPATH, "//a[contains(@href, 'MYEXAMS') or contains(@href, 'PRGNAME=MYEXAMS')]")
                href = exams_elem.get_attribute("href")
                if href:
                    try:
                        driver.get(href)
                        try:
                            wait.until(lambda d: d.execute_script("return document.readyState") == 'complete')
                        except Exception:
                            time.sleep(0.5)
                    except Exception:
                        try:
                            driver.execute_script("arguments[0].click();", exams_elem)
                        except Exception:
                            pass
            except Exception:
                # Give up gracefully; we'll return whatever page is currently loaded
                pass

        # Now, scrape the whole page text (hopefully the exams page)
        time.sleep(1)  # wait a bit for content to load
        html = driver.page_source
        soup = BeautifulSoup(html, "html.parser")
        visible_text = soup.get_text(separator="\n", strip=True)
        return format_exams_text(visible_text)
    except Exception as e:
        return f"Fehler beim Klick auf die Authentifizierungsoption: {e}"

def format_exams_text(raw_text: str) -> str:
    # First, cut everything before "Veranstaltung/Modul Name Datum"
    pattern = r"Wählen Sie ein Semester"
    match = re.search(pattern, raw_text)
    if match:
        raw_text = raw_text[match.start():]
    
    # Second, ignore words like "Abmelden", "Ausgewählt", "Termin wechseln" as well as "Kontakt", "Impressum", "Barrierefreiheit", "Datenschutz"
    lines = []
    for line in raw_text.splitlines():
        lower_line = line.lower()
        if any(x in lower_line for x in ["abmelden", "ausgewählt", "termin wechseln", "kontakt", "impressum", "barrierefreiheit", "datenschutz"]):
            continue
        lines.append(line.strip())
    return "\n".join(lines)

def ask_chatgpt_exams(exams_text: str, api_key: Optional[str]) -> str:
    """Send a prompt to ChatGPT and return the response text."""
    try:
        from openai import OpenAI
    except ImportError:
        return "Fehler: 'openai' Paket nicht installiert."

    key = _pick_api_key(api_key)
    if not key:
        return "Kein API-Key vorhanden. Bitte in der App speichern und erneut versuchen."

    client = OpenAI(api_key=key)
    response = client.chat.completions.create(
        model="gpt-5-mini",
        messages=[
            {"role": "system", "content": "Du bist ein hilfreicher Assistent, der Stine-Prüfungen für den Benutzer zusammenfasst."},
            {"role": "user", "content": "Hier sind meine Stine-Prüfungen:\n" + exams_text}
        ]
    )
    # Normalize the response text and append the calendar question (same wording used elsewhere)
    resp_text = response.choices[0].message.content + "\nSoll ich dir die Termine auch in deinen Kalender eintragen?"
    global latestMessage
    latestMessage = resp_text
    return resp_text

def ask_chatgpt_moodle(termine: str, api_key: Optional[str]) -> str:
    """Send a prompt to ChatGPT and return the response text."""
    try:
        from openai import OpenAI
    except ImportError:
        return "Fehler: 'openai' Paket nicht installiert."

    key = _pick_api_key(api_key)
    if not key:
        return "Kein API-Key vorhanden. Bitte in der App speichern und erneut versuchen."

    client = OpenAI(api_key=key)
    user_message = (
        "Hier sind meine Moodle-Aufgaben:\n" + termine 
        + "Beginne die Nachricht mit 'Hier sind deine Moodle-Aufgaben:'. Heute ist der " + datetime.date.today().isoformat() 
        + ". Nenne die Termine abhängig vom heutigen Datum (z.B. 'morgen', 'in zwei Tagen'). Gib auch immer das jeweilige Modul für die Termine an."
        + " Unterscheide zwischen endenden und beginnenden Terminen."
        + " WICHTIG: Auch wenn mehrere Termine das selbe Datum haben, liste jeden Termin einzeln auf."
    )
    response = client.chat.completions.create(
        model="gpt-5-mini",
        messages=[
            {"role": "system", "content": "Du bist ein hilfreicher Assistent, der Moodle-Aufgaben für den Benutzer zusammenfasst."},
            {"role": "user", "content": user_message}
        ]
    )
    resp_text = response.choices[0].message.content + "\nSoll ich dir die Termine auch in deinen Kalender eintragen?"
    global latestMessage
    latestMessage = resp_text
    return resp_text


async def determine_intent(message: str, api_key: Optional[str]) -> str:
    """Asynchronously determine the user's intent by asking Gemini.

    Retries on transient errors to be more robust when many requests arrive quickly.
    """
    msg = message.strip()
    # Add calendar_yes/calendar_no so short replies like 'Ja'/'Nein' are classified
    labels = [
        "get_moodle_appointments",
        "get_stine_messages",
        "get_stine_exams",
        "get_mail",
        "greeting",
        "help",
        "calendar_yes",
        "calendar_no",
        "unknown",
    ]

    prompt = (
        "Classify the user's message into exactly one of the following intent labels: "
        + ", ".join(labels)
        + ".\nRespond with only the intent label (one of the labels) and nothing else.\n"
        + "If the user asks about Moodle appointments, deadlines or 'Aufgaben', return 'get_moodle_appointments'.\n"
        + "If the user asks about Stine messages or 'Stine Nachrichten', return 'get_stine_messages'.\n"
        + "If the user asks about Stine exams or 'Stine Prüfungen', return 'get_stine_exams'.\n"
        + "If the user asks about email or 'E-Mail', return 'get_mail'.\n"
        + "If the message is a greeting (hello, hi, hallo) return 'greeting'.\n"
        + "If the user asks for help or how to use the bot return 'help'.\n"
        + "If the user replies with an affirmative like 'ja' (German) or 'yes', return 'calendar_yes'.\n"
        + "If the user replies with a negative like 'nein' (German) or 'no', return 'calendar_no'.\n"
        + f"User message: \"{msg}\"\n"
    )

    # Blocking call will run in a thread to avoid blocking the event loop.
    def _call_openai(inner_prompt: str):
        try:
            from openai import OpenAI
        except Exception:
            raise
        key = _pick_api_key(api_key)
        if not key:
            raise RuntimeError("Kein API-Key konfiguriert")
        client = OpenAI(api_key=key)
        response = client.chat.completions.create(
            model="gpt-5-mini",
            messages=[{"role": "user", "content": inner_prompt}]
        )
        return response.choices[0].message.content

    max_retries = 1
    backoff_base = 0.5
    for attempt in range(1, max_retries + 1):
        try:
            response = await asyncio.to_thread(_call_openai, prompt)
            # parse the model response robustly
            intent_text = response.strip().splitlines()[0].strip() if response else ""
            if intent_text in labels:
                return intent_text
            for lab in labels:
                if lab in response:
                    return lab
            logging.info("ChatGPT returned unexpected intent text (attempt %d): %s", attempt, response)
            # If model returned something unexpected, retry a couple times
        except Exception as e:
            logging.warning("Attempt %d: Error calling ChatGPT for intent detection: %s", attempt, e)

        # backoff before retrying
        if attempt < max_retries:
            await asyncio.sleep(backoff_base * (2 ** (attempt - 1)))

    # All retries failed or response couldn't be parsed -> fallback
    logging.error("Intent detection failed after %d attempts for message: %s", max_retries, msg)
    return "unknown"

def make_calendar_entries(termine: str, api_key: Optional[str]):
    # ask ChatGPT to parse the dates into calendar entries
    try:
        from openai import OpenAI
    except ImportError:
        return "Fehler: 'openai' Paket nicht installiert."

    key = _pick_api_key(api_key)
    if not key:
        return None, "Kein API-Key vorhanden. Bitte in der App speichern und erneut versuchen."

    client = OpenAI(api_key=key)
    user_message = (
        "Hier sind meine Termine:\n" + termine
        + "\nFormatiere diese Termine als Kalender-Einträge im ICS-Format. Antworte nur mit dem reinen ICS-Dateiinhalt ohne zusätzliche Erklärungen."
        + "\nÜberspringe alle Termine, die kein Datum haben."
    )
    response = client.chat.completions.create(
        model="gpt-5-mini",
        messages=[
            {"role": "system", "content": "Du bist ein hilfreicher Assistent, der Termine als ics Dateien formatiert."},
            {"role": "user", "content": user_message}
        ]
    )
    # Persist the raw ICS text to a timestamped debug file for troubleshooting and return filename.
    ics_content = response.choices[0].message.content or ""
    saved_basename = None
    try:
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        debug_dir = os.path.dirname(__file__)
        debug_path = os.path.join(debug_dir, f"debug_ics_response_{timestamp}.ics")
        with open(debug_path, "w", encoding="utf-8") as f:
            f.write(ics_content)
        saved_basename = os.path.basename(debug_path)
        logging.info("Wrote ICS debug file: %s", debug_path)
    except Exception as e:
        logging.warning("Could not write ICS debug file: %s", e)

    # Return a tuple (basename or None, raw_text)
    return saved_basename, ics_content


@app.get('/download_ics/{filename}')
def download_ics(filename: str):
    """Serve a previously saved ICS debug file. Only allow filenames starting with the expected prefix to
    avoid exposing arbitrary files.
    """
    if not filename.startswith("debug_ics_response_") or not filename.endswith('.ics'):
        return Response(status_code=404)
    debug_dir = os.path.dirname(__file__)
    path = os.path.join(debug_dir, filename)
    if not os.path.isfile(path):
        return Response(status_code=404)
    # Use FileResponse to stream the file and suggest a download filename
    return FileResponse(path, media_type='text/calendar', filename=filename)

@app.post("/chat")
async def chat(request: ChatRequest):
    # Use Gemini to classify the user's intent. If Gemini fails, determine_intent
    # will return 'unknown' and we fall back to a simple keyword check.
    username = request.username
    api_key = _pick_api_key(request.api_key)
    if not api_key:
        return {"response": "Kein API-Key gesetzt. Bitte den ChatGPT-Key beim Start speichern oder in den Einstellungen hinzufügen."}

    # Check and expire any old conversation state for this user
    with state_lock:
        state = conversation_state.get(username)
        if state:
            if time.time() - state.get('ts', 0) > STATE_EXPIRY_SECONDS:
                # expired
                del conversation_state[username]
                state = None

    # If the bot previously asked about adding to calendar, interpret simple yes/no locally
    intent = None
    if state and state.get('awaiting_calendar'):
        # Interpret a short affirmative/negative reply without calling Gemini
        msg_low = request.message.strip().lower()
        if msg_low in ("ja", "j", "yes", "y", "klar", "gerne"):
            intent = "calendar_yes"
        elif msg_low in ("nein", "n", "no"):
            intent = "calendar_no"
        # If message isn't a clear yes/no, fall back to full intent detection (below)

    if intent is None:
        intent = await determine_intent(request.message, api_key)
    else:
        # If we already set intent based on local short-reply parsing, keep it.
        pass

    # Safety: if Gemini returned calendar_yes/calendar_no but we did not previously ask the
    # calendar question for this user, ignore those labels to avoid accidental triggers.
    if intent in ("calendar_yes", "calendar_no"):
        if not (state and state.get('awaiting_calendar')):
            # Treat as unknown so normal routing/keyword checks apply.
            intent = "unknown"
    # Route based on detected intent
    if intent == "get_moodle_appointments":
        try:
            termine = scrape_moodle_text(request.username, request.password)
            response = ask_chatgpt_moodle(termine, api_key)
            # If ChatGPT asked whether to add events to calendar, mark state so the next short reply
            # can be interpreted as consent/denial. We only set this for the requesting user.
            if response and "Soll ich dir die Termine auch in deinen Kalender eintragen?" in response:
                with state_lock:
                    conversation_state[username] = { 'awaiting_calendar': True, 'ts': time.time() }
            return {"response": response}
        except Exception as e:
            response = f"Fehler beim Abrufen: {e}"
            return {"response": response}
    elif intent == "get_stine_messages":
        return {"response": "Die Funktion zum Abrufen von Stine-Nachrichten ist noch nicht implementiert."}
    elif intent == "get_stine_exams":
        try:
            exams_text = scrape_stine_exams(request.username, request.password)
            response = ask_chatgpt_exams(exams_text, api_key)
            # If ChatGPT asked whether to add events to calendar, mark state so the next short reply
            # can be interpreted as consent/denial. We only set this for the requesting user.
            if response and "Soll ich dir die Termine auch in deinen Kalender eintragen?" in response:
                with state_lock:
                    conversation_state[username] = { 'awaiting_calendar': True, 'ts': time.time() }
            return {"response": response}
        except Exception as e:
            response = f"Fehler beim Abrufen der Stine-Prüfungen: {e}"
            return {"response": response}
    elif intent == "get_mail":
        return {"response": "Die Funktion zum Abrufen von E-Mails ist noch nicht implementiert."}
    elif intent == "greeting":
        return {"response": "Hallo! Ich kann dir bei Moodle-Terminen helfen. Frag z. B. 'Welche Termine habe ich?'"}
    elif intent == "help":
        return {"response": f"Du kannst nach 'Terminen' fragen. \n Formuliere z. B. 'Was sind meine Termine?'"}
    elif intent == "calendar_yes":
        # proceed to create calendar entries
        with state_lock:
            if username in conversation_state:
                del conversation_state[username]
        try:
            termine = latestMessage
            saved_basename, ics_content = make_calendar_entries(termine, api_key)
            resp = {"response": "Hier sind die Kalender-Einträge im ICS-Format:", "ics": ics_content}
            if saved_basename:
                resp["ics_filename"] = saved_basename
            return resp
        except Exception as e:
            response = f"Fehler beim Erstellen der Kalender-Einträge: {e}"
            return {"response": response}
    elif intent == "calendar_no":
        # clear awaiting flag for this user
        with state_lock:
            if username in conversation_state:
                del conversation_state[username]
        return {"response": "Alles klar. Mit was kann ich dir sonst helfen?"}
    else:
        return {"response": "Entschuldigung, ich habe dich nicht verstanden. Bitte frage nach Moodle-Terminen."}


@app.get("/health")
def health():
    return {"status": "ok"}


# ============================================================================
# Credential Management Endpoints
# ============================================================================

@app.post("/credentials/save")
def api_save_credentials(req: CredentialsSaveRequest):
    """Save encrypted credentials to local device storage."""
    success = save_credentials(req.username, req.password, req.api_key)
    if success:
        return {"success": True, "message": "Credentials saved successfully"}
    else:
        return {"success": False, "message": "Failed to save credentials"}


@app.get("/credentials/load")
def api_load_credentials() -> CredentialsResponse:
    """Load encrypted credentials from local device storage."""
    creds = load_credentials()
    if creds:
        return CredentialsResponse(
            username=creds.get("username"),
            password=creds.get("password"),
            api_key=creds.get("api_key")
        )
    else:
        return CredentialsResponse()


@app.delete("/credentials/delete")
def api_delete_credentials():
    """Delete stored credentials from local device storage."""
    success = delete_credentials()
    if success:
        return {"success": True, "message": "Credentials deleted successfully"}
    else:
        return {"success": False, "message": "Failed to delete credentials"}


@app.get("/", response_class=HTMLResponse)
def root():
    if FRONTEND_DIST:
        index_path = os.path.join(FRONTEND_DIST, "index.html")
        if os.path.isfile(index_path):
            return FileResponse(index_path, media_type="text/html")
    return HTMLResponse(
        "<html><head><title>Moodle Chat Backend</title></head><body>"
        "<h1>Moodle Chat Backend</h1>"
        "<p>Open the <a href='/docs'>API docs</a> to test endpoints or POST to <code>/chat</code>.</p>"
        "</body></html>"
    )


@app.get("/{full_path:path}", response_class=HTMLResponse)
def spa_fallback(full_path: str):
    if FRONTEND_DIST:
        index_path = os.path.join(FRONTEND_DIST, "index.html")
        if os.path.isfile(index_path):
            return FileResponse(index_path, media_type="text/html")
    return Response(status_code=404)


@app.get('/favicon.ico')
def favicon():
    """Return no content for favicon requests to avoid 404 noise in logs."""
    return Response(status_code=204)



if __name__ == "__main__":
    def _open_browser():
        try:
            time.sleep(1)
            webbrowser.open("http://127.0.0.1:8000")
        except Exception:
            pass

    threading.Thread(target=_open_browser, daemon=True).start()
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
