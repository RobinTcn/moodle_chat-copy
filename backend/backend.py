# backend.py
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
import re

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

        html = driver.page_source
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(separator="\n", strip=True)
        match = re.search(r"(?<=Aktuelle Termine)(.*?)(?=Zum Kalender)", text, re.DOTALL)
        if not match:
            return "❗ Abschnitt nicht gefunden."

        # Extract matched block and clean common UI/skip-link artifacts that sometimes
        # appear right after the heading (for example 'überspringen' or 'Zum Inhalt').
        block = match.group(1).strip()
        # Remove leading accessibility/skip-link words like 'überspringen' or 'zum inhalt springen'
        block = re.sub(r"(?i)^\s*(?:überspringen\b[:\-\–\—]?\s*|zum inhalt springen\b[:\-\–\—]?\s*|zum inhalt\b[:\-\–\—]?\s*)", "", block)
        # Also guard against accidentally included repeated headings
        block = re.sub(r"(?i)^\s*Aktuelle Termine\s*[:\-\–\—]?\s*", "", block)
        return block if block else "❗ Abschnitt nicht gefunden."

    except Exception as e:
        return f"Fehler beim Scraping: {e}"

    finally:
        try:
            driver.quit()
        except Exception:
            pass

@app.post("/chat")
async def chat(request: ChatRequest):
    msg = request.message.lower()
    if "termin" in msg:
        try:
            termine = scrape_moodle_text(request.username, request.password)
            # scrape_moodle_text returns a string with either the Termine or an error message
            # Return the Termine (or the error message) directly to the frontend.
            response = f"Hier sind deine aktuellen Moodle-Termine:\n{termine}"
            return {"response": response}
        except Exception as e:
            response = f"Fehler beim Abrufen: {e}"
    else:
        response = "Entschuldigung, ich habe dich nicht verstanden. Bitte frage nach Moodle-Terminen."
    return {"response": response}


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
