"""Calendar entry creation and ICS file handling."""
import os
import datetime
import logging
import re
from typing import Optional, Tuple, List


def pick_api_key(provided: Optional[str]) -> Optional[str]:
    """Pick the API key from provided value or environment."""
    key = (provided or "").strip()
    if key:
        return key
    import os
    env_key = os.getenv("OPENAI_API_KEY", "").strip()
    return env_key or None


def extract_events_from_ics(ics_content: str) -> List[dict]:
    """Extract calendar events from ICS content.
    
    Returns:
        List of event dicts with 'date' and 'title' fields
    """
    events = []
    
    logging.info(f"[ICS] Extracting events from ICS content ({len(ics_content)} chars)")
    
    # Parse ICS format
    # Look for VEVENT blocks
    event_pattern = r'BEGIN:VEVENT.*?END:VEVENT'
    events_text = re.findall(event_pattern, ics_content, re.DOTALL)
    
    logging.info(f"[ICS] Found {len(events_text)} VEVENT blocks")
    
    for event_text in events_text:
        # Extract DTSTART (date) - support multiple formats:
        # - DTSTART;VALUE=DATE:20260204
        # - DTSTART;VALUE=DATE-TIME:20260204T123000Z
        # - DTSTART:20260204T123000Z
        # We want to extract just the date part (YYYYMMDD)
        date_match = re.search(r'DTSTART(?:;VALUE=(?:DATE|DATE-TIME))?:(\d{8})', event_text)
        if not date_match:
            logging.warning(f"[ICS] No DTSTART found in event: {event_text[:100]}...")
            continue
        
        date_str = date_match.group(1)
        # Format as ISO date: YYYYMMDD -> YYYY-MM-DD
        if len(date_str) == 8 and date_str.isdigit():
            date_iso = f"{date_str[0:4]}-{date_str[4:6]}-{date_str[6:8]}"
            logging.info(f"[ICS] Extracted date: {date_str} -> {date_iso}")
        else:
            logging.warning(f"[ICS] Invalid date format: {date_str}")
            continue
        # Extract SUMMARY (title)
        summary_match = re.search(r'SUMMARY:([^\r\n]*)', event_text)
        if not summary_match:
            title = "Termin"
            logging.warning(f"[ICS] No SUMMARY found, using default: {title}")
        else:
            title = summary_match.group(1).strip()
        
        logging.info(f"[ICS] Extracted event: {date_iso} - {title}")
        events.append({
            'date': date_iso,
            'title': title
        })
    
    logging.info(f"[ICS] Total events extracted: {len(events)}")
    return events


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
        + "\nWICHTIG: Verwende DTSTART;VALUE=DATE:YYYYMMDD Format (KEINE Zeitstempel, NUR das Datum)."
        + "\nBeispiel: DTSTART;VALUE=DATE:20260204 (für 4. Februar 2026)"
        + "\nWICHTIG: Füge NUR Abgabetermine/Endtermine/Deadlines hinzu. NICHT beginnende Termine wie 'Öffnet am' oder 'Beginnt am'."
        + "\nÜberspringe alle Termine, die kein Datum haben."
        + "\nWICHTIG: Der Titel (SUMMARY) MUSS das Format 'Beschreibung (Modul)' haben."
        + "\nBeispiel SUMMARY: 'Abgabe Übungsblatt 3 (Mathematik I)'"
        + "\nFalls die Beschreibung bereits das Modul enthält, behalte das Format bei."
    )
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Du bist ein ICS-Generator. WICHTIG: Verwende IMMER DTSTART;VALUE=DATE:YYYYMMDD (nur Datum, kein Zeitstempel). Erstelle NUR Events für Abgabetermine/Endtermine. Ignoriere beginnende Termine. SUMMARY-Format: 'Beschreibung (Modul)'."},
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
