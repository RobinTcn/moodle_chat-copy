"""Moodle web scraping functionality."""
import re
import time
import logging
from typing import Optional


TARGET = "https://lernen.min.uni-hamburg.de/my/"


def scrape_moodle_text(username: str, password: str, headless: bool = True, max_wait: int = 25) -> str:
    """Scrape current appointments/tasks from Moodle."""
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
