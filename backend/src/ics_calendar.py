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


def _normalize_ics_dates(ics_content: str) -> str:
    """Ensure ICS dates are not stuck in an outdated year.

    OpenAI occasionally invents years (e.g., 2024) when the input text omits the
    year. We assume the current calendar year is the correct default; if the
    month is already past in the current year, roll forward to next year.
    """
    today = datetime.date.today()
    current_year = today.year
    current_month = today.month

    def _replace(tag: str, text: str) -> str:
        pattern = rf"({tag}(?:;VALUE=(?:DATE|DATE-TIME))?:)(\d{{8}})"

        def repl(match: re.Match) -> str:
            prefix, date_str = match.groups()
            try:
                year = int(date_str[0:4])
                month = int(date_str[4:6])
                day = int(date_str[6:8])
            except ValueError:
                return match.group(0)

            if year < current_year:
                target_year = current_year
                if month < current_month:
                    target_year += 1
                fixed = f"{target_year:04d}{month:02d}{day:02d}"
                logging.info(f"[ICS] Normalized {tag} year {date_str} -> {fixed}")
                return f"{prefix}{fixed}"

            return match.group(0)

        return re.sub(pattern, repl, text)

    normalized = _replace("DTSTART", ics_content)
    normalized = _replace("DTEND", normalized)
    return normalized


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
    today = datetime.date.today()
    current_year = today.year
    next_year = current_year + 1

    user_message = (
        "Hier sind meine Termine:\n" + termine
        + "\nFormatiere diese Termine als Kalender-Einträge im ICS-Format. Antworte nur mit dem reinen ICS-Dateiinhalt ohne zusätzliche Erklärungen."
        + "\nWICHTIG: Verwende DTSTART;VALUE=DATE:YYYYMMDD Format (KEINE Zeitstempel, NUR das Datum)."
        + f"\nHeutiges Jahr: {current_year}. Wenn im Text kein Jahr steht, verwende {current_year}; nur wenn der Monat bereits vergangen ist, nutze {next_year}."
        + "\nNutze niemals vergangene Jahre."  # Avoid model defaulting to outdated years
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
            {"role": "system", "content": f"Du bist ein ICS-Generator. Heutiges Jahr ist {current_year}. Wenn im Text kein Jahr steht, verwende {current_year} (oder {next_year}, falls der Monat schon vorbei ist). Verwende IMMER DTSTART;VALUE=DATE:YYYYMMDD (nur Datum, kein Zeitstempel). Erstelle NUR Events für Abgabetermine/Endtermine. Ignoriere beginnende Termine. SUMMARY-Format: 'Beschreibung (Modul)'."},
            {"role": "user", "content": user_message}
        ]
    )
    # Persist the raw ICS text to a timestamped debug file for troubleshooting and return filename.
    ics_content = response.choices[0].message.content or ""
    ics_content = _normalize_ics_dates(ics_content)
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
