"""Calendar entry creation and ICS file handling."""
import os
import datetime
import logging
from typing import Optional, Tuple


def pick_api_key(provided: Optional[str]) -> Optional[str]:
    """Pick the API key from provided value or environment."""
    key = (provided or "").strip()
    if key:
        return key
    import os
    env_key = os.getenv("OPENAI_API_KEY", "").strip()
    return env_key or None


def make_calendar_entries(termine: str, api_key: Optional[str]) -> Tuple[Optional[str], str]:
    """Parse dates from appointment text and create ICS format calendar entries.
    
    Returns:
        Tuple of (saved_filename_or_none, ics_content)
    """
    # ask ChatGPT to parse the dates into calendar entries
    try:
        from openai import OpenAI
    except ImportError:
        return None, "Fehler: 'openai' Paket nicht installiert."

    key = pick_api_key(api_key)
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
