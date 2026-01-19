# backend.py
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, Response, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import os
import logging
import time
import threading
import sys
import webbrowser
import re
import random

# Import modules
from src.models import ChatRequest, CredentialsSaveRequest, CredentialsResponse
from src.credentials import save_credentials, load_credentials, delete_credentials
from src.moodle_scraper import scrape_moodle_text
from src.stine_exam_scraper import scrape_stine_exams
from src.llm import ask_chatgpt_moodle, ask_chatgpt_exams, ask_chatgpt_topic_help, determine_intent, pick_api_key
from src.ics_calendar import make_calendar_entries, extract_events_from_ics
from src.utils import resolve_frontend_dist
from evaluation_logger import start_turn, end_turn
from src.google_calendar import (
    exchange_code_for_token,
    fetch_calendar_events,
    get_user_info,
    refresh_access_token,
    create_calendar_event,
    delete_calendar_event,
    update_calendar_event
)

# Load .env file if present (developer convenience). Requires python-dotenv in requirements.
try:
    from dotenv import load_dotenv
    # load .env from backend directory (where this file lives)
    load_dotenv()
except Exception:
    # If python-dotenv isn't installed, that's okay — environment variables may be set elsewhere.
    pass

# Configure logging to show INFO and above messages in console
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)  # Output to console/terminal
    ]
)

# Note: selenium and bs4 imports are moved into the scraping function so the
# FastAPI app can start even when Selenium/chromedriver aren't installed.

latestMessage = ""

# ============================================================================
# Emotional Response System
# ============================================================================

# Dictionary mit Gefühlskategorien, Keywords und passenden Antworten
EMOTIONAL_PATTERNS = {
    'overwhelmed': {
        'keywords': [
            'zu viel', 'überwältigt', 'überfordert', 'schaffe es nicht', 'schaff es nicht',
            'keine zeit', 'so viel', 'so schwer', 'zu schwer', 'zu viel', 'zu schwierig', 'packe es nicht',
            'pack es nicht', 'komme nicht hinterher', 'komm nicht hinterher'
        ],
        'responses': [
            "Ich verstehe, dass sich das gerade überwältigend anfühlt. Lass uns das Schritt für Schritt angehen.",
            "Das klingt nach einer Menge auf einmal. Keine Sorge, wir nehmen das gemeinsam in Angriff.",
            "Ich merke, dass dich das belastet. Lass uns erstmal sortieren, was am wichtigsten ist.",
            "Das ist verständlich - manchmal ist es einfach viel. Ich helfe dir gerne dabei, Struktur reinzubringen."
        ]
    },
    'stressed': {
        'keywords': [
            'stress', 'gestresst', 'nervös', 'angespannt', 'unter druck', 'panik',
            'kopf platzt', 'wahnsinnig', 'irre', 'verrückt', 'angst', 'ängstlich'
        ],
        'responses': [
            "Ich merke, dass dich das stresst. Atme tief durch - ich bin hier, um dir zu helfen.",
            "Stress ist ganz normal vor wichtigen Terminen. Lass uns gemeinsam schauen, wie ich dich unterstützen kann.",
            "Das klingt stressig. Keine Panik - wir kriegen das gemeinsam hin.",
            "Ich verstehe, dass die Situation belastend ist. Lass uns das zusammen angehen."
        ]
    },
    'frustrated': {
        'keywords': [
            'frustriert', 'genervt', 'ärgerlich', 'wütend', 'sauer', 'verstehe nicht',
            'versteh nicht', 'kapiere nicht', 'kapier nicht', 'keinen sinn', 'sinnlos'
        ],
        'responses': [
            "Frustration gehört zum Lernen dazu. Lass uns das gemeinsam nochmal von vorne anschauen.",
            "Ich verstehe, dass das frustrierend ist. Manchmal hilft ein anderer Blickwinkel - ich versuche es zu erklären.",
            "Das ist nachvollziehbar. Lass uns das Problem zusammen angehen.",
            "Frustration zeigt oft, dass man nah dran ist. Lass mich dir helfen, das zu durchbrechen."
        ]
    },
    'tired': {
        'keywords': [
            'müde', 'erschöpft', 'ausgelaugt', 'kaputt', 'fertig', 'keine energie',
            'kraftlos', 'schlapp', 'erledigt'
        ],
        'responses': [
            "Klingt, als bräuchtest du eine Pause. Denk daran, dass Erholung genauso wichtig ist wie Lernen.",
            "Müdigkeit ist ein Zeichen, dass dein Gehirn hart arbeitet. Vielleicht hilft eine kurze Pause?",
            "Das verstehe ich. Überlege dir, ob du eine Pause brauchst - danach geht's oft besser.",
            "Du klingst erschöpft. Denk dran: Pausen sind produktiv, nicht verschwendete Zeit."
        ]
    },
    'unmotivated': {
        'keywords': [
            'keine lust', 'unmotiviert', 'motivation', 'aufraffen', 'prokrastination',
            'aufschieben', 'keinen bock', 'keine motivation', 'antriebslos'
        ],
        'responses': [
            "Motivation kommt oft erst beim Machen. Lass uns klein anfangen - was ist der erste kleine Schritt?",
            "Verstehe ich. Manchmal hilft es, mit etwas Einfachem zu starten. Was könnten wir zusammen angehen?",
            "Fehlende Motivation ist normal. Lass uns trotzdem einen kleinen Anfang machen - oft kommt der Flow dann von selbst.",
            "Das kenne ich. Wie wäre es, wenn wir mit etwas Leichtem beginnen? Oft wird's dann einfacher."
        ]
    },
    'confused': {
        'keywords': [
            'verwirrt', 'durcheinander', 'unklar', 'verstehe nicht', 'versteh nicht',
            'nicht klar', 'chaos', 'verloren', 'orientierungslos'
        ],
        'responses': [
            "Verwirrung ist okay - das bedeutet, dass dein Gehirn versucht, neue Verbindungen zu knüpfen. Lass uns das klären.",
            "Kein Problem. Lass uns das Schritt für Schritt durchgehen, bis es Sinn ergibt.",
            "Verstehe. Manchmal braucht es eine andere Erklärung. Ich versuche, es klarer zu machen.",
            "Das ist normal bei komplexen Themen. Lass uns das gemeinsam entwirren."
        ]
    },
    'positive': {
        'keywords': [
            'danke', 'super', 'toll', 'prima', 'perfekt', 'genial', 'klasse',
            'vielen dank', 'hilft mir', 'verstehe jetzt', 'versteh jetzt', 'macht sinn'
        ],
        'responses': [
            "Freut mich, dass ich helfen konnte!",
            "Gern geschehen! Ich bin für dich da.",
            "Das freut mich zu hören! Weiter so!",
            "Super, dass es klappt! Sag Bescheid, wenn du noch was brauchst."
        ]
    }
}


def detect_emotion(message: str):
    """Erkennt Gefühlsäußerungen in Nachrichten und gibt passende Antwort zurück.
    
    Args:
        message: Die Nachricht des Users
        
    Returns:
        Tuple (emotion_category, response) oder (None, None) wenn keine Gefühlsäußerung erkannt wurde
    """
    msg_lower = message.lower()
    
    # Durchsuche alle Gefühlskategorien
    for category, data in EMOTIONAL_PATTERNS.items():
        for keyword in data['keywords']:
            # Keyword muss als ganzes Wort oder Teil eines Satzes vorkommen
            if keyword in msg_lower:
                # Wähle zufällige Antwort aus den möglichen Antworten
                response = random.choice(data['responses'])
                logging.info(f"[Emotion] Detected '{category}' emotion with keyword '{keyword}'")
                return category, response
    
    return None, None


# ============================================================================
# Global State Management
# ============================================================================

FRONTEND_DIST = resolve_frontend_dist()

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

# Wizard flow - simple sequential steps (1-6)
# Step 1: Ask for module
# Step 2: Ask for topics
# Step 3: Ask which topic to start with (if multiple)
# Step 4: Collect materials
# Step 5: Ask for questions
# Step 6: Answer and offer to continue with next topic

# Cache for scraped data to avoid expensive re-scraping
# Keyed by (username, data_type) -> { 'raw_data': str, 'ts': float }
scraper_cache = {}
cache_lock = threading.Lock()
CACHE_EXPIRY_SECONDS = 3600  # cache expires after 1 hour

if FRONTEND_DIST:
    assets_path = os.path.join(FRONTEND_DIST, "assets")
    if os.path.isdir(assets_path):
        app.mount("/assets", StaticFiles(directory=assets_path), name="assets")


def get_cached_scraped_data(username: str, data_type: str):
    """Get cached scraped data if available and not expired.

    Args:
        username: User identifier
        data_type: Type of data ('moodle' or 'stine_exams')

    Returns:
        Tuple of (raw_data, None) or (None, None) if cache miss/expired
    """
    cache_key = (username, data_type)

    with cache_lock:
        cached = scraper_cache.get(cache_key)
        if cached:
            # Check if cache is still valid
            if time.time() - cached.get('ts', 0) < CACHE_EXPIRY_SECONDS:
                logging.info(f"Cache hit for {data_type} scraped data (user: {username})")
                return cached.get('raw_data'), None
            else:
                # Cache expired, remove it
                logging.info(f"Cache expired for {data_type} scraped data (user: {username})")
                del scraper_cache[cache_key]

    return None, None


def cache_scraped_data(username: str, data_type: str, raw_data: str):
    """Store scraped raw data in cache (ChatGPT responses are regenerated per request)."""
    cache_key = (username, data_type)
    with cache_lock:
        scraper_cache[cache_key] = {
            'raw_data': raw_data,
            'ts': time.time()
        }
    logging.info(f"Cached {data_type} scraped data (user: {username})")


def _build_chat_response(response_text: str, username: str = None, settings: dict = None, suggested_events: list = None, ics_filename: str = None, ics: str = None, is_wizard_message: bool = False, is_settings_message: bool = False):
    """Helper function to build chat response with wizard and settings status."""
    result = {"response": response_text}
    
    # Add wizard status if username provided
    if username:
        with state_lock:
            state = conversation_state.get(username, {})
            wizard = state.get('wizard')
            result["wizard_active"] = bool(wizard and wizard.get('active'))
    
    # Add is_wizard_message flag
    result["is_wizard_message"] = is_wizard_message
    
    # Add is_settings_message flag
    result["is_settings_message"] = is_settings_message
    
    # Add optional fields
    if settings:
        result["settings"] = settings
    if suggested_events:
        result["suggested_events"] = suggested_events
    if ics_filename:
        result["ics_filename"] = ics_filename
    if ics:
        result["ics"] = ics
    
    return result


def _new_wizard_state():
    return {
        'active': True,
        'step': 1,  # Sequential step number
        'module': None,
        'topics': [],
        'current_topic_index': 0,
        'materials': {}
    }


def _parse_topics_list(text: str):
    parts = []
    for raw in text.replace(";", ",").split("\n"):
        parts.extend(raw.split(","))
    topics = [p.strip() for p in parts if p.strip()]
    return topics


def _is_negative_response(text: str):
    """Check if user response signals no/none; avoid substring false positives."""
    lowered = text.strip().lower()
    # Single-word tokens must match whole words to avoid catching words like "linear"
    token_keywords = ["nein", "no", "nope", "kein", "keine", "nö"]
    # Phrases are matched as substrings
    phrase_keywords = [
        "gar keine", "mir egal", "egal", "alle", "alles", "alle themen",
        "keine ahnung", "weiß nicht", "keine idee", "keine spezifischen", "kein topic",
    ]

    for kw in token_keywords:
        if re.search(rf"\b{re.escape(kw)}\b", lowered):
            return True
    for kw in phrase_keywords:
        if kw in lowered:
            return True
    return False


def _extract_topic_index(user_text: str, topics):
    """Extract topic index from ordinal words or numbers. Returns index (0-based) or None."""
    if not topics:
        return None
    lowered = user_text.strip().lower()
    
    # Check for ordinal numbers: 1., 2., 3., etc.
    import re
    ordinal_match = re.search(r'\b(\d+)\.?\b', lowered)
    if ordinal_match:
        num = int(ordinal_match.group(1))
        idx = num - 1  # Convert to 0-based
        if 0 <= idx < len(topics):
            return idx
    
    # Check for German ordinal words
    ordinal_words = {
        'erste': 0, 'erstes': 0, 'ersten': 0,
        'zweite': 1, 'zweites': 1, 'zweiten': 1,
        'dritte': 2, 'drittes': 2, 'dritten': 2,
        'vierte': 3, 'viertes': 3, 'vierten': 3,
        'fünfte': 4, 'fünftes': 4, 'fünften': 4,
        'sechste': 5, 'sechstes': 5, 'sechsten': 5,
        'siebte': 6, 'siebtes': 6, 'siebten': 6,
        'achte': 7, 'achtes': 7, 'achten': 7,
        'neunte': 8, 'neuntes': 8, 'neunten': 8,
        'zehnte': 9, 'zehntes': 9, 'zehnten': 9,
    }
    
    for word, idx in ordinal_words.items():
        if word in lowered and idx < len(topics):
            return idx
    
    return None


def _pick_topic_from_input(user_text: str, topics):
    if not topics:
        return None
    lowered = user_text.strip().lower()
    if not lowered:
        return None
    
    # First try to extract ordinal index
    idx = _extract_topic_index(user_text, topics)
    if idx is not None:
        return topics[idx]
    
    # Exact match
    for t in topics:
        if lowered == t.lower():
            return t
    # partial match
    for t in topics:
        if lowered in t.lower():
            return t
    return None


def _handle_wizard_message(username: str, message: str, state: dict, api_key: str = None):
    wizard = (state or {}).get('wizard')
    if not wizard or not wizard.get('active'):
        return None

    msg = message.strip()
    msg_low = msg.lower()
    
    # Check for cancellation keywords at any step
    cancel_keywords = ["exit", "abbruch", "abbrechen", "stop", "beenden", "nein danke", "nicht mehr"]
    if any(kw in msg_low for kw in cancel_keywords):
        # Delete wizard state completely on cancellation
        with state_lock:
            if username in conversation_state:
                conversation_state[username].pop('wizard', None)
                if not conversation_state[username]:  # Remove empty state
                    del conversation_state[username]
        return "Wizard beendet. Sag Bescheid, wenn ich wieder helfen soll."
    
    step = wizard.get('step', 1)
    response = None
    topics = wizard.get('topics', [])
    current_idx = wizard.get('current_topic_index', 0)
    current_topic = topics[current_idx] if topics and current_idx < len(topics) else None

    if step == 1:  # Ask for module
        # Check if user gives a negative/unsure response
        if _is_negative_response(msg) or any(kw in msg_low for kw in ["weiß nicht", "keine ahnung", "unsicher", "keins"]):
            response = "Um dir bei der Vorbereitung helfen zu können, muss ich wissen, um welches Modul es geht. Bitte gib den Modulnamen an."
        elif not msg or len(msg) < 2 or not any(c.isalnum() for c in msg):
            response = "Bitte gib einen gültigen Modulnamen ein oder schreibe 'exit' zum Abbrechen."
        else:
            wizard['module'] = msg
            wizard['step'] = 2
            response = f"Alles klar, Modul '{msg}'.\n\nGeht es für dich um ein oder mehrere bestimmte Themen oder Kapitel? Wenn ja, liste diese auf, getrennt durch Kommas. Wenn du keine konkreten Themen hast, ist es auch okay."

    elif step == 2:  # Ask for topics
        if _is_negative_response(msg):
            wizard['topics'] = [wizard.get('module', 'Allgemein')]
            wizard['step'] = 4  # Skip topic selection
            response = "Alles klar, dann arbeiten wir über das ganze Modul. \n\nBeschreibe gerne den Stoff kurz.\n\nWenn du das gerade nicht möchtest, schreibe 'kein upload'."
        else:
            topics_parsed = _parse_topics_list(msg)
            # Filter out negative responses from parsed topics
            topics_parsed = [t for t in topics_parsed if not _is_negative_response(t) and t.lower() not in ["keins", "keine", "keine Ahnung", "unsicher", "weiß nicht"]]
            
            if not topics_parsed:
                response = "Ich habe keine Themen erkannt. Bitte liste die Themen oder Kapitel, getrennt durch Kommas. Wenn du keine spezifischen Themen hast, schreibe einfach 'nein' oder 'keine'."
            else:
                wizard['topics'] = topics_parsed
                if len(topics_parsed) == 1:
                    wizard['step'] = 4  # Skip topic selection if only one topic
                    response = f"Verstanden. Wir arbeiten zum Thema '{topics_parsed[0]}'.\n\nBeschreibe gerne den Stoff kurz. \n\nWenn du das gerade nicht möchtest, schreibe 'kein upload'."
                else:
                    wizard['step'] = 3
                    topic_list = "\n- " + "\n- ".join(topics_parsed)
                    response = f"Verstanden. Ich habe diese Themen gespeichert:{topic_list}\n\nMit was möchtest du anfangen? Wenn du unsicher bist, schreibe 'Vorschlag'."

    elif step == 3:  # Ask which topic to start with
        topics = wizard.get('topics', [])
        
        # Try to pick topic by name or ordinal number
        choice = _pick_topic_from_input(msg, topics)
        
        if 'vorschlag' in msg_low or not choice:
            choice = topics[0] if topics else None
            note = "Dann fangen wir mit dem ersten Thema an."
        else:
            # Reorder topics to start with chosen one
            topics = [choice] + [t for t in topics if t != choice]
            wizard['topics'] = topics
            note = f"Okay, wir starten mit '{choice}'."
        
        if not choice:
            response = "Ich konnte kein Thema auswählen. Bitte nenne ein Thema oder schreibe 'Vorschlag'."
        else:
            wizard['step'] = 4
            response = f"{note} \n\nBeschreibe gerne den Stoff kurz. \n\nWenn du das gerade nicht möchtest, schreibe 'kein upload'."

    elif step == 4:  # Collect materials
        # If user just repeats the topic name or says they have no upload, skip storing as material
        no_materials = _is_negative_response(msg) or msg_low in ["kein upload", "kein", "keine", "kein material"]
        repeats_topic = current_topic and msg_low == current_topic.strip().lower()

        wizard.setdefault('materials', {})
        if not no_materials and not repeats_topic:
            wizard['materials'][current_topic] = msg

        wizard['step'] = 5
        response = (
            f"Alles klar zu '{current_topic}'. "
            "Hast du bereits konkrete Fragen? Falls nein, starte ich mit einer kurzen Erklärung des Themas."
        )

    elif step == 5:  # Ask for questions and provide answer
        module = wizard.get('module')
        materials = wizard.get('materials', {}).get(current_topic, "")
        wizard['step'] = 6
        if any(tok in msg_low for tok in ["keine", "kein", "nein"]):
            ai_resp = ask_chatgpt_topic_help(module, current_topic, materials, "keine", api_key)
            response = ai_resp + "\n\nStell jederzeit Zwischenfragen oder schreibe 'weiter' für das nächste Thema."
        else:
            ai_resp = ask_chatgpt_topic_help(module, current_topic, materials, msg, api_key)
            response = ai_resp + "\n\nWenn du fertig bist, schreibe 'weiter' für das nächste Thema."

    elif step == 6:  # Follow-up questions or next topic
        if any(tok in msg_low for tok in ["weiter", "nächste", "next"]):
            next_idx = current_idx + 1
            if next_idx < len(topics):
                wizard['current_topic_index'] = next_idx
                wizard['step'] = 4  # Back to collect materials
                response = f"Nächstes Thema: '{topics[next_idx]}'. \n\nBeschreibe gerne den Stoff kurz. \n\nWenn du das gerade nicht möchtest, schreibe 'kein upload'."
            else:
                # All topics done - end wizard
                with state_lock:
                    if username in conversation_state:
                        conversation_state[username].pop('wizard', None)
                        if not conversation_state[username]:
                            del conversation_state[username]
                return "Du hast alle Themen durchgearbeitet. Wizard beendet. Sag Bescheid, wenn ich wieder helfen soll!"
        else:
            # Follow-up question
            module = wizard.get('module')
            materials = wizard.get('materials', {}).get(current_topic, "")
            ai_resp = ask_chatgpt_topic_help(module, current_topic, materials, msg, api_key)
            response = ai_resp + "\n\nSchreibe 'weiter' für das nächste Thema oder frag weiter zu diesem Thema."

    # Update timestamp and persist wizard state
    with state_lock:
        conversation_state[username] = state or {}
        conversation_state[username]['wizard'] = wizard
        conversation_state[username]['ts'] = time.time()

    return response


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
    global latestMessage
    latestMessage = request.message

    # === EVAL LOG START (Turn beginnt sobald Message im Backend ankommt) ===
    timer = start_turn(username=request.username, conv_id=request.conv_id, user_message=request.message)

    # ================================================================

    # Use ChatGPT to classify the user's intent. If ChatGPT fails, determine_intent
    # will return 'unknown' and we fall back to a simple keyword check.
    username = request.username
    api_key = pick_api_key(request.api_key)

    if not api_key:
        msg = "Kein API-Key gesetzt. Bitte den ChatGPT-Key beim Start speichern oder in den Einstellungen hinzufügen."
        end_turn(timer, bot_message=msg, intent="no_api_key")
        return _build_chat_response(msg, username)


    # Check and expire any old conversation state for this user
    with state_lock:
        state = conversation_state.get(username)
        if state:
            if time.time() - state.get('ts', 0) > STATE_EXPIRY_SECONDS:
                # expired
                del conversation_state[username]
                state = None

    wizard_state = state.get('wizard') if state else None
    wizard_active = bool(wizard_state and wizard_state.get('active'))
    msg_low = request.message.strip().lower()
    stop_keywords = ("exit")

    # ================================================================
    # Emotional Response Detection
    # ================================================================
    # Erkenne Gefühlsäußerungen BEVOR Intent-Detection läuft
    emotion_category, emotion_response = detect_emotion(request.message)
    
    # Allow global exit to cancel the wizard if it's active
    if wizard_active and msg_low.strip() == "exit":
        with state_lock:
            user_state = conversation_state.get(username, {})
            user_state.pop('wizard', None)
            user_state['ts'] = time.time()
            conversation_state[username] = user_state
        end_turn(timer, bot_message="Wizard beendet. Sag Bescheid, wenn ich wieder helfen soll.", intent="stop_exam_wizard")
        return _build_chat_response("Wizard beendet. Sag Bescheid, wenn ich wieder helfen soll.", username, is_wizard_message=True)

    # If the bot previously asked about adding to calendar, interpret simple yes/no locally
    intent = None
    if state and state.get('awaiting_calendar'):
        # Interpret a short affirmative/negative reply without calling ChatGPT
        if msg_low in ("ja", "j", "yes", "y", "klar", "gerne"):
            intent = "calendar_yes"
        elif msg_low in ("nein", "n", "no"):
            intent = "calendar_no"
        # If message isn't a clear yes/no, fall back to full intent detection (below)
    
    # If the bot is in settings configuration mode, handle settings dialog
    elif state and state.get('configuring_settings'):
        step = state.get('settings_step', 'ask_task_days')
        msg = request.message.strip()
        
        if step == 'ask_task_days':
            # Try to parse the number
            try:
                days = int(msg)
                if days < 0 or days > 30:
                    msg = "Bitte gib eine Zahl zwischen 0 und 30 ein."
                    end_turn(timer, bot_message=msg, intent="settings")
                    return _build_chat_response(msg, username, is_settings_message=True)

                
                # Save to state and ask next question
                with state_lock:
                    conversation_state[username]['reminder_days_tasks'] = days
                    conversation_state[username]['settings_step'] = 'ask_exam_days'
                    conversation_state[username]['ts'] = time.time()
                
                msg = f"Gut, ich erinnere dich {days} Tag(e) vor Aufgaben-Deadlines.\n\nWie viele Tage vor einer Klausur möchtest du erinnert werden? (z.B. 7 für eine Woche vorher)"
                end_turn(timer, bot_message=msg, intent="settings")
                return _build_chat_response(msg, username, is_settings_message=True)

            except ValueError:
                msg = "Bitte gib eine gültige Zahl ein (z.B. 1, 3, 7)."
                end_turn(timer, bot_message=msg, intent="settings")
                return _build_chat_response(msg, username, is_settings_message=True)

        
        elif step == 'ask_exam_days':
            # Try to parse the number
            try:
                days = int(msg)
                if days < 0 or days > 30:
                    msg = "Bitte gib eine Zahl zwischen 0 und 30 ein."
                    end_turn(timer, bot_message=msg, intent="settings")
                    return _build_chat_response(msg, username, is_settings_message=True)

                
                # Save settings and clear state
                task_days = state.get('reminder_days_tasks', 1)
                
                with state_lock:
                    if username in conversation_state:
                        del conversation_state[username]
                
                # Return settings to frontend for storage
                msg = f"Alles klar! Deine Erinnerungseinstellungen wurden gespeichert:\n- Aufgaben: {task_days} Tag(e) vorher\n- Klausuren: {days} Tag(e) vorher\n\nIch werde dich entsprechend benachrichtigen!"
                end_turn(timer, bot_message=msg, intent="settings")
                return _build_chat_response(msg, username, settings={"reminder_days_tasks": task_days, "reminder_days_exams": days}, is_settings_message=True)

            except ValueError:
                msg = "Bitte gib eine gültige Zahl ein (z.B. 1, 3, 7)."
                end_turn(timer, bot_message=msg, intent="settings")
                return _build_chat_response(msg, username, is_settings_message=True)

        
        # Fallback: should not reach here
        with state_lock:
            if username in conversation_state:
                del conversation_state[username]
        msg = "Ein Fehler ist aufgetreten. Bitte versuche es erneut."
        end_turn(timer, bot_message=msg, intent="settings")
        return _build_chat_response(msg, username, is_settings_message=True)


    # While wizard is active: skip intent detection; only allow explicit stop keyword
    if wizard_active:
        if any(msg_low.strip() == kw for kw in stop_keywords):
            with state_lock:
                user_state = conversation_state.get(username, {})
                user_state.pop('wizard', None)
                user_state['ts'] = time.time()
                conversation_state[username] = user_state
            return _build_chat_response("Wizard beendet. Sag Bescheid, wenn ich wieder helfen soll.", username, is_wizard_message=True)

        wizard_response = _handle_wizard_message(username, request.message, state, api_key)
        if wizard_response:
            return _build_chat_response(wizard_response, username, is_wizard_message=True)
        # If wizard handler could not process, keep user in wizard and prompt to continue or stop
        return _build_chat_response("Ich bin im Klausur-Wizard. Bitte beantworte die letzte Frage oder schreibe 'wizard beenden' zum Abbrechen.", username, is_wizard_message=True)

    # Quick keywords for starting the wizard without LLM
    if intent is None:
        if any(kw in msg_low for kw in ["klausurvorbereitung", "exam wizard", "wizard starten"]):
            intent = "start_exam_wizard"
            wizard_active = True

    # Fast keyword-based intent detection to avoid unnecessary LLM calls
    if intent is None:
        # Check for settings/reminders
        if any(msg_low.strip() == kw for kw in ["settings", "/settings", "einstellungen", "erinnerungseinstellungen"]):
            intent = "settings"
        # Check for common Moodle-related keywords
        elif msg_low == "/moodle":
            intent = "get_moodle_appointments"
        # Check for Stine exam keywords
        elif msg_low in ["/exams", "/stine"]:
            intent = "get_stine_exams"
        # Check for mail keywords
        elif msg_low == "/mail":
            intent = "get_mail"
        # Check for help
        elif msg_low in ["hilfe", "/help"]:
            intent = "help"

    # If no keyword match, use LLM for intent detection
    if intent is None:
        intent = await determine_intent(request.message, api_key)
    else:
        # If we already set intent based on local short-reply parsing, keep it.
        pass

    # Safety: if ChatGPT returned calendar_yes/calendar_no but we did not previously ask the
    # calendar question for this user, ignore those labels to avoid accidental triggers.
    if intent in ("calendar_yes", "calendar_no"):
        if not (state and state.get('awaiting_calendar')):
            # Treat as unknown so normal routing/keyword checks apply.
            intent = "unknown"
    
    logging.info(f"[Chat] Detected intent: {intent}")
    logging.info(f"[Chat] Username: {username}")
    logging.info(f"[Chat] Has password: {bool(request.password)}")
    
    # Route based on detected intent
    if intent == "start_exam_wizard":
        base_state = state or {}
        wizard = _new_wizard_state()
        with state_lock:
            conversation_state[username] = {**base_state, 'wizard': wizard, 'ts': time.time()}
        response_msg = ("Gern helfe ich dir bei der Klausurvorbereitung.\n\n"
                 " Du kannst den Vorbereitungs-Wizard jederzeit mit 'exit' abbrechen.\n\n"
                 " Damit ich dir helfen kann, muss ich dir zunächst ein paar Fragen stellen.\n"
                 " 1. Um welches Modul geht es?")
        return _build_chat_response(response_msg, username, is_wizard_message=True)

    elif intent == "stop_exam_wizard":
        with state_lock:
            if username in conversation_state:
                conversation_state[username].pop('wizard', None)
                if not conversation_state[username]:
                    del conversation_state[username]
        end_turn(timer, bot_message="Wizard beendet. Sag Bescheid, wenn ich wieder helfen soll.", intent="stop_exam_wizard")
        return _build_chat_response("Wizard beendet. Sag Bescheid, wenn ich wieder helfen soll.", username, is_wizard_message=True)

    # Any other intent while wizard is active: reset wizard and process the intent normally
    if wizard_active and intent not in ("start_exam_wizard", "stop_exam_wizard"):
        logging.info(f"[Chat] Wizard interrupted by intent '{intent}' - resetting wizard")
        with state_lock:
            if username in conversation_state:
                conversation_state[username].pop('wizard', None)
                if not conversation_state[username]:
                    del conversation_state[username]
        # Continue processing the intent below

    if intent == "get_moodle_appointments":
        # Wenn Gefühlsäußerung erkannt wurde, füge empathische Antwort hinzu
        emotion_prefix = ""
        if emotion_response:
            emotion_prefix = f"{emotion_response} "
            logging.info(f"[Chat] Adding emotional response to Moodle request: {emotion_category}")
        
        logging.info("[Chat] Processing Moodle appointments request")
        try:
            # Check cache first for scraped data
            cached_data, _ = get_cached_scraped_data(username, 'moodle')
            if cached_data:
                logging.info("[Chat] Using cached Moodle raw data; regenerating response for current query")
                termine = cached_data
            else:
                # Cache miss - scrape and cache the data
                logging.info("[Chat] Cache miss - starting Moodle scraper")
                logging.info(f"[Chat] Username for scraper: {request.username}")
                termine = scrape_moodle_text(request.username, request.password)
                logging.info(f"[Chat] Scraper returned {len(termine)} characters")
                
                # Check if scraper returned an error
                if any(error_keyword in termine for error_keyword in ["Fehler", "nicht verfügbar", "Selenium", "WebDriver", "Chrome", "Failed", "Exception"]):
                    logging.warning(f"[Chat] Scraper returned error: {termine[:100]}")
                    msg = "Moodle ist gerade nicht erreichbar. Bitte versuche es später noch einmal."
                    end_turn(timer, bot_message=msg, intent=intent)
                    return _build_chat_response(msg, username)

                # Cache raw data only
                cache_scraped_data(username, 'moodle', termine)

            # Always regenerate the ChatGPT answer so user constraints in the latest message are applied
            logging.info("[Chat] Asking ChatGPT to format Moodle data for current query")
            response = ask_chatgpt_moodle(termine, api_key)
            
            # Füge empathische Antwort vor die eigentliche Antwort
            if emotion_prefix:
                response = emotion_prefix + response
            
            logging.info(f"[Chat] ChatGPT response length: {len(response)}")
            
            # If ChatGPT asked whether to add events to calendar, mark state so the next short reply
            # can be interpreted as consent/denial. We only set this for the requesting user.
            if response and "Soll ich dir die Termine auch in deinen Kalender eintragen?" in response:
                with state_lock:
                    # IMPORTANT: Store RAW scraper data, not formatted response
                    conversation_state[username] = { 'awaiting_calendar': True, 'raw_termine': termine, 'ts': time.time() }
                logging.info("[Chat] Calendar option offered - raw data stored in state")
            end_turn(timer, bot_message=response, intent=intent)
            return _build_chat_response(response, username)

        except Exception as e:
            response = f"Fehler beim Abrufen: {e}"
            end_turn(timer, bot_message=response, intent=intent)
            return _build_chat_response(response, username)

    elif intent == "get_stine_messages":
        msg = "Die Funktion zum Abrufen von Stine-Nachrichten ist noch nicht implementiert."
        end_turn(timer, bot_message=msg, intent=intent)
        return _build_chat_response(msg, username)

    elif intent == "get_stine_exams":
        # Wenn Gefühlsäußerung erkannt wurde, füge empathische Antwort hinzu
        emotion_prefix = ""
        if emotion_response:
            emotion_prefix = f"{emotion_response} "
            logging.info(f"[Chat] Adding emotional response to STINE request: {emotion_category}")
        
        try:
            # Check cache first for scraped data
            cached_data, _ = get_cached_scraped_data(username, 'stine_exams')
            if cached_data:
                logging.info("[Chat] Using cached STINE raw data; regenerating response for current query")
                exams_text = cached_data
            else:
                # Cache miss - scrape and cache the data
                exams_text = scrape_stine_exams(request.username, request.password)
                
                # Check if scraper returned an error
                if any(error_keyword in exams_text for error_keyword in ["Fehler", "nicht verfügbar", "Selenium", "WebDriver", "Chrome", "Failed", "Exception"]):
                    logging.warning(f"[Chat] STINE scraper returned error: {exams_text[:100]}")
                    msg = "STINE ist gerade nicht erreichbar. Bitte versuche es später noch einmal."
                    end_turn(timer, bot_message=msg, intent=intent)
                    return _build_chat_response(msg, username)

                # Cache raw data only
                cache_scraped_data(username, 'stine_exams', exams_text)

            # Always regenerate the ChatGPT answer so user constraints in the latest message are applied
            response = ask_chatgpt_exams(exams_text, api_key)
            
            # Füge empathische Antwort vor die eigentliche Antwort
            if emotion_prefix:
                response = emotion_prefix + response
            
            # If ChatGPT asked whether to add events to calendar, mark state so the next short reply
            # can be interpreted as consent/denial. We only set this for the requesting user.
            if response and "Soll ich dir die Termine auch in deinen Kalender eintragen?" in response:
                with state_lock:
                    # IMPORTANT: Store RAW scraper data, not formatted response
                    conversation_state[username] = { 'awaiting_calendar': True, 'raw_termine': exams_text, 'ts': time.time() }
                logging.info("[Chat] Calendar option offered for STINE exams - raw data stored in state")
            end_turn(timer, bot_message=response, intent=intent)
            return _build_chat_response(response, username)

        except Exception as e:
            response = f"Fehler beim Abrufen der Stine-Prüfungen: {e}"
            end_turn(timer, bot_message=response, intent=intent)
            return _build_chat_response(response, username)

    elif intent == "get_mail":
        msg = "Die Funktion zum Abrufen von E-Mails ist noch nicht implementiert."
        end_turn(timer, bot_message=msg, intent=intent)
        return _build_chat_response(msg, username)

    elif intent == "settings":
        # Start settings configuration dialog
        with state_lock:
            conversation_state[username] = {
                'configuring_settings': True,
                'settings_step': 'ask_task_days',
                'ts': time.time()
            }
        msg = "**Lass uns deine Erinnerungseinstellungen konfigurieren!** \n\nWie viele Tage vor einer Aufgaben-Deadline möchtest du erinnert werden? (z.B. 1 für einen Tag vorher, 3 für drei Tage vorher)"
        end_turn(timer, bot_message=msg, intent=intent)
        return _build_chat_response(msg, username, is_settings_message=True)

    elif intent == "greeting":
        msg = "Hallo! Wie kann ich dir helfen?"
        end_turn(timer, bot_message=msg, intent=intent)
        return _build_chat_response(msg, username)

    elif intent == "help":
        msg = "Ich kann dir bei folgenden Dingen helfen:\n\n" \
                         "- Moodle-Termine und Deadlines abrufen\n" \
                         "- Stine-Prüfungstermine abrufen\n" \
                         "- Erinnerungseinstellungen konfigurieren\n" \
                         "- Kalendertermine hinzufügen\n" \
                         " - dich bei der Klausurvorbereitung unterstützen\n\n"
        end_turn(timer, bot_message=msg, intent=intent)
        return _build_chat_response(msg, username)

    elif intent == "calendar_yes":
        # proceed to create calendar entries
        termine = None
        with state_lock:
            if username in conversation_state:
                state = conversation_state[username]
                # Get the RAW data (not formatted response)
                termine = state.get('raw_termine', '')
                del conversation_state[username]
        
        if not termine:
            logging.error("[Chat] Calendar YES: No raw data found in state")
            msg = "Fehler: Keine Termine verfügbar. Bitte erneut anfragen."
            end_turn(timer, bot_message=msg, intent=intent)
            return _build_chat_response(msg, username)

        
        try:
            logging.info(f"[Chat] Calendar YES - using raw data ({len(termine)} chars)")
            _, ics_content = make_calendar_entries(termine, api_key)
            
            # Extract events from ICS for suggested_events
            suggested_events = extract_events_from_ics(ics_content)
            
            logging.info(f"[Chat] Calendar YES - extracted {len(suggested_events)} events")
            
            # Return only the suggested events as buttons, no ICS file download
            result = _build_chat_response("", username, suggested_events=suggested_events)
            end_turn(timer, bot_message=f"suggested_events returned ({len(suggested_events)} events)", intent=intent)
            return result

        except Exception as e:
            response = f"Fehler beim Erstellen der Kalender-Einträge: {e}"
            logging.error(f"[Chat] Calendar entry creation failed: {e}")
            end_turn(timer, bot_message=response, intent=intent)
            return _build_chat_response(response, username)

    elif intent == "calendar_no":
        # clear awaiting flag for this user
        with state_lock:
            if username in conversation_state:
                del conversation_state[username]
        msg = "Alles klar. Mit was kann ich dir sonst helfen?"
        end_turn(timer, bot_message=msg, intent=intent)
        return _build_chat_response(msg, username)

    else:
        # Wenn eine Gefühlsäußerung erkannt wurde, aber kein spezifischer Intent
        if emotion_response:
            # Prüfe, ob die Nachricht auch eine Frage/Anfrage enthält
            help_keywords = ['hilfe', 'helfen', 'unterstützen', 'kannst du', 'könntest du', 'würdest du']
            wizard_keywords = ['klausur', 'prüfung', 'vorbereitung', 'lernen', 'thema']
            
            if any(kw in msg_low for kw in help_keywords):
                if any(kw in msg_low for kw in wizard_keywords):
                    # Kombination aus Gefühl + Klausurvorbereitung-Anfrage
                    combined_msg = f"{emotion_response} Ich kann dir bei der Klausurvorbereitung helfen! Möchtest du den Klausur-Wizard starten? (Schreibe 'Klausurvorbereitung' oder 'Hilfe' für mehr Optionen)"
                else:
                    # Allgemeine Hilfe-Anfrage
                    combined_msg = f"{emotion_response} Ich kann dir bei verschiedenen Dingen helfen:\n\n" \
                                 "- Moodle-Termine und Deadlines abrufen\n" \
                                 "- Stine-Prüfungstermine abrufen\n" \
                                 "- Klausurvorbereitung\n" \
                                 "- Kalendertermine hinzufügen\n\n" \
                                 "Was kann ich für dich tun?"
                end_turn(timer, bot_message=combined_msg, intent=f"{emotion_category}_with_help")
                return _build_chat_response(combined_msg, username)
            else:
                # Nur Gefühlsäußerung, keine konkrete Anfrage
                msg = f"{emotion_response} Wie kann ich dir noch helfen?"
                end_turn(timer, bot_message=msg, intent=emotion_category)
                return _build_chat_response(msg, username)
        
        # Keine Gefühlsäußerung und kein Intent erkannt
        msg = "Entschuldigung, ich habe dich nicht verstanden. Du erhälst eine Auflistung meiner Funktionen, wenn du 'Hilfe' schreibst."
        end_turn(timer, bot_message=msg, intent=intent)
        return _build_chat_response(msg, username)


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


# ============================================================================
# Google Calendar API Endpoints
# ============================================================================

@app.post("/api/google/oauth/callback")
async def google_oauth_callback(data: dict):
    """
    Handle OAuth callback - exchange authorization code for tokens
    """
    logging.info(f"OAuth callback received with data keys: {list(data.keys())}")
    
    code = data.get("code")
    redirect_uri = data.get("redirect_uri")
    
    if not code or not redirect_uri:
        logging.error(f"Missing code or redirect_uri. Code present: {bool(code)}, redirect_uri: {redirect_uri}")
        return {"success": False, "message": "Missing code or redirect_uri"}
    
    logging.info(f"Exchanging authorization code for tokens...")
    # Exchange code for tokens
    token_data = exchange_code_for_token(code, redirect_uri)
    
    if not token_data:
        error_msg = "Failed to exchange code for token - check backend logs for Google API response"
        logging.error(error_msg)
        return {"success": False, "message": error_msg, "debug": "Check server logs"}
    
    logging.info("Successfully exchanged code for tokens, fetching user info...")
    # Fetch user info
    access_token = token_data.get("access_token")
    user_info = get_user_info(access_token)
    
    if not user_info:
        logging.error("Failed to fetch user info")
        return {"success": False, "message": "Failed to fetch user info"}
    
    logging.info(f"Successfully authenticated user: {user_info.get('email')}")
    return {
        "success": True,
        "access_token": access_token,
        "refresh_token": token_data.get("refresh_token"),
        "expires_in": token_data.get("expires_in"),
        "user": {
            "email": user_info.get("email"),
            "name": user_info.get("name"),
            "picture": user_info.get("picture"),
        }
    }


@app.post("/api/google/calendar/events")
async def get_calendar_events(data: dict):
    """
    Fetch Google Calendar events for a given time range
    """
    logging.info("Calendar events endpoint called")
    access_token = data.get("access_token")
    time_min = data.get("time_min")
    time_max = data.get("time_max")
    
    if not access_token:
        logging.error("Missing access_token in calendar events request")
        return {"success": False, "message": "Missing access_token"}
    
    logging.info(f"Fetching calendar events from {time_min} to {time_max}")
    events = fetch_calendar_events(access_token, time_min, time_max)
    logging.info(f"Retrieved {len(events)} calendar events")
    
    return {
        "success": True,
        "events": events
    }


@app.post("/api/google/oauth/refresh")
async def refresh_token_endpoint(data: dict):
    """
    Refresh access token using refresh token
    """
    refresh_token = data.get("refresh_token")
    
    if not refresh_token:
        return {"success": False, "message": "Missing refresh_token"}
    
    token_data = refresh_access_token(refresh_token)
    
    if not token_data:
        return {"success": False, "message": "Failed to refresh token"}
    
    return {
        "success": True,
        "access_token": token_data.get("access_token"),
        "expires_in": token_data.get("expires_in"),
    }


@app.post("/api/google/calendar/create")
async def create_calendar_event_endpoint(data: dict):
    """
    Create an event in Google Calendar
    """
    logging.info("Create calendar event endpoint called")
    logging.info(f"Received data: {data}")
    
    access_token = data.get("access_token")
    event_title = data.get("title")
    event_date = data.get("date")
    
    logging.info(f"access_token present: {bool(access_token)}")
    logging.info(f"title: {event_title}")
    logging.info(f"date: {event_date}")
    
    if not access_token or not event_title or not event_date:
        logging.error(f"Missing required fields. access_token: {bool(access_token)}, title: {bool(event_title)}, date: {bool(event_date)}")
        return {"success": False, "message": "Missing access_token, title, or date"}
    
    logging.info(f"Creating event: {event_title} on {event_date}")
    created_event = create_calendar_event(access_token, event_title, event_date)
    
    if not created_event:
        logging.error("Failed to create calendar event")
        return {"success": False, "message": "Failed to create event in Google Calendar"}
    
    logging.info(f"Event created successfully: {created_event.get('id')}")
    
    return {
        "success": True,
        "event_id": created_event.get("id"),
        "event": {
            "id": f"google-{created_event.get('id')}",
            "date": event_date,
            "text": event_title,
            "source": "google"
        }
    }


@app.post("/api/google/calendar/delete")
async def delete_calendar_event_endpoint(data: dict):
    """
    Delete an event from Google Calendar
    """
    logging.info("Delete calendar event endpoint called")
    
    access_token = data.get("access_token")
    event_id = data.get("event_id")
    
    if not access_token or not event_id:
        logging.error(f"Missing required fields. access_token: {bool(access_token)}, event_id: {bool(event_id)}")
        return {"success": False, "message": "Missing access_token or event_id"}
    
    # Remove 'google-' prefix if present
    if event_id.startswith("google-"):
        event_id = event_id[7:]
    
    logging.info(f"Deleting event: {event_id}")
    success = delete_calendar_event(access_token, event_id)
    
    if not success:
        logging.error("Failed to delete calendar event")
        return {"success": False, "message": "Failed to delete event from Google Calendar"}
    
    logging.info(f"Event deleted successfully: {event_id}")
    
    return {
        "success": True,
        "message": "Event deleted successfully"
    }


@app.post("/api/google/calendar/update")
async def update_calendar_event_endpoint(data: dict):
    """
    Update an event in Google Calendar
    """
    logging.info("Update calendar event endpoint called")
    
    access_token = data.get("access_token")
    event_id = data.get("event_id")
    event_title = data.get("title")
    event_date = data.get("date")
    
    if not access_token or not event_id or not event_title or not event_date:
        logging.error(f"Missing required fields. access_token: {bool(access_token)}, event_id: {bool(event_id)}, title: {bool(event_title)}, date: {bool(event_date)}")
        return {"success": False, "message": "Missing access_token, event_id, title, or date"}
    
    # Remove 'google-' prefix if present
    if event_id.startswith("google-"):
        event_id = event_id[7:]
    
    logging.info(f"Updating event: {event_id}")
    updated_event = update_calendar_event(access_token, event_id, event_title, event_date)
    
    if not updated_event:
        logging.error("Failed to update calendar event")
        return {"success": False, "message": "Failed to update event in Google Calendar"}
    
    logging.info(f"Event updated successfully: {event_id}")
    
    return {
        "success": True,
        "event_id": updated_event.get("id"),
        "event": {
            "id": f"google-{updated_event.get('id')}",
            "date": event_date,
            "text": event_title,
            "source": "google"
        }
    }



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
    import subprocess
    import uvicorn
    import socket

    # Function to check if server is ready
    def wait_for_server(host, port, timeout=30):
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(1)
                result = sock.connect_ex((host, port))
                sock.close()
                if result == 0:
                    return True
            except Exception:
                pass
            time.sleep(0.5)
        return False

    # Start FastAPI server in a separate thread
    def start_server():
        uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
    
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()
    
    # Wait for server to be ready
    print("Starting server...")
    if wait_for_server("127.0.0.1", 8000):
        print("Server is ready!")
        
        # Try to open in Chrome app mode (standalone window)
        url = "http://127.0.0.1:8000"
        try:
            # Common Chrome paths on Windows
            chrome_paths = [
                os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
                os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
                os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
            ]
            
            chrome_path = None
            for path in chrome_paths:
                if os.path.exists(path):
                    chrome_path = path
                    break
            
            if chrome_path:
                # Open Chrome in app mode (standalone window without browser UI)
                subprocess.Popen([chrome_path, f"--app={url}", "--window-size=1200,800"])
            else:
                # Fallback to default browser
                webbrowser.open(url)
        except Exception:
            # Fallback to default browser
            webbrowser.open(url)
    else:
        print("Server failed to start!")
    
    # Keep the main thread alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
