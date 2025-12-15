"""Stine exam scraping functionality."""
import re
import time
import logging
from typing import Optional


def scrape_stine_exams(username: str, password: str) -> str:
    """Scrape exam information from Stine."""
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

    finally:
        try:
            driver.quit()
        except Exception:
            pass


def format_exams_text(raw_text: str) -> str:
    """Format and clean exam text for LLM processing."""
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
