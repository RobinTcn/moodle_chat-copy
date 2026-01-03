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

# Import modules
from src.models import ChatRequest, CredentialsSaveRequest, CredentialsResponse
from src.credentials import save_credentials, load_credentials, delete_credentials
from src.moodle_scraper import scrape_moodle_text
from src.stine_exam_scraper import scrape_stine_exams
from src.llm import ask_chatgpt_moodle, ask_chatgpt_exams, ask_chatgpt_topic_help, determine_intent, pick_api_key
from src.ics_calendar import make_calendar_entries, extract_events_from_ics
from src.utils import resolve_frontend_dist
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

# Wizard flow constants
WIZARD_STEP_PICK_MODULE = "pick_module"
WIZARD_STEP_PICK_TOPICS = "pick_topics"
WIZARD_STEP_PICK_ORDER = "pick_order"
WIZARD_STEP_COLLECT_MATERIALS = "collect_materials"
WIZARD_STEP_QUESTIONS = "questions_or_walkthrough"
WIZARD_STEP_FOLLOWUP = "followup"

WIZARD_INTENT_STEPS = {
    "wizard_pick_module": WIZARD_STEP_PICK_MODULE,
    "wizard_pick_topics": WIZARD_STEP_PICK_TOPICS,
    "wizard_pick_order": WIZARD_STEP_PICK_ORDER,
    "wizard_collect_materials": WIZARD_STEP_COLLECT_MATERIALS,
    "wizard_questions_or_walkthrough": WIZARD_STEP_QUESTIONS,
    "wizard_followup": WIZARD_STEP_FOLLOWUP,
}

# Cache for scraped data to avoid expensive re-scraping
# Keyed by (username, data_type) -> { 'data': str, 'ts': float }
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
        Tuple of (raw_data, chatgpt_response) or (None, None) if cache miss/expired
    """
    cache_key = (username, data_type)
    
    with cache_lock:
        cached = scraper_cache.get(cache_key)
        if cached:
            # Check if cache is still valid
            if time.time() - cached.get('ts', 0) < CACHE_EXPIRY_SECONDS:
                logging.info(f"Cache hit for {data_type} scraped data (user: {username})")
                return cached.get('raw_data'), cached.get('chatgpt_response')
            else:
                # Cache expired, remove it
                logging.info(f"Cache expired for {data_type} scraped data (user: {username})")
                del scraper_cache[cache_key]
    
    return None, None


def cache_scraped_data(username: str, data_type: str, raw_data: str, chatgpt_response: str = None):
    """Store scraped data and optional ChatGPT response in cache.
    
    Args:
        username: User identifier
        data_type: Type of data ('moodle' or 'stine_exams')
        raw_data: Raw scraped data to cache
        chatgpt_response: Optional ChatGPT formatted response
    """
    cache_key = (username, data_type)
    with cache_lock:
        scraper_cache[cache_key] = {
            'raw_data': raw_data,
            'chatgpt_response': chatgpt_response,
            'ts': time.time()
        }
    logging.info(f"Cached {data_type} scraped data (user: {username})")


def _new_wizard_state():
    return {
        'active': True,
        'step': WIZARD_STEP_PICK_MODULE,
        'module': None,
        'topics': [],
        'order': [],
        'order_index': 0,
        'current_topic': None,
        'materials': {}
    }


def _parse_topics_list(text: str):
    parts = []
    for raw in text.replace(";", ",").split("\n"):
        parts.extend(raw.split(","))
    topics = [p.strip() for p in parts if p.strip()]
    return topics


def _pick_topic_from_input(user_text: str, topics):
    if not topics:
        return None
    lowered = user_text.strip().lower()
    if not lowered:
        return None
    # numeric selection (1-based)
    if lowered.isdigit():
        idx = int(lowered) - 1
        if 0 <= idx < len(topics):
            return topics[idx]
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
    step = wizard.get('step', WIZARD_STEP_PICK_MODULE)
    response = None

    if step == WIZARD_STEP_PICK_MODULE:
        wizard['module'] = msg
        wizard['step'] = WIZARD_STEP_PICK_TOPICS
        response = f"Alles klar, Modul '{msg}'.\n\n Geht es für dich um ein oder mehrere bestimmte Themen oder Kapitel? Bitte liste diese auf, getrennt durch Kommas."

    elif step == WIZARD_STEP_PICK_TOPICS:
        topics = _parse_topics_list(msg)
        if not topics:
            response = "Ich habe keine Themen erkannt. Bitte liste die Themen oder Kapitel, getrennt durch Kommas oder Zeilenumbrüche."
        else:
            wizard['topics'] = topics
            wizard['step'] = WIZARD_STEP_PICK_ORDER
            topic_list = "\n- " + "\n- ".join(topics)
            response = (
                f"Verstanden. Ich habe diese Themen gespeichert:{topic_list}\n\n"
                "Mit was möchtest du anfangen? Wenn du unsicher bist, schreibe 'Vorschlag', dann schlage ich eine Reihenfolge vor."
            )

    elif step == WIZARD_STEP_PICK_ORDER:
        topics = wizard.get('topics', [])
        choice = _pick_topic_from_input(msg, topics)
        if 'vorschlag' in msg.lower() or not choice:
            order = topics
            choice = topics[0] if topics else None
            note = "Dann fangen wir doch einfach mit dem ersten Thema an." if topics else "Keine Themen vorhanden."
        else:
            order = [choice] + [t for t in topics if t != choice]
            note = f"Wir starten mit '{choice}'."

        if not choice:
            response = "Ich konnte kein Thema auswählen. Bitte nenne ein Thema oder schreibe 'Vorschlag'."
        else:
            wizard['order'] = order
            wizard['current_topic'] = choice
            wizard['order_index'] = 0
            wizard['step'] = WIZARD_STEP_COLLECT_MATERIALS
            response = (
                f"{note} Wenn du möchtest, lade Folien, Aufgaben oder Altklausuren hoch oder beschreibe den Stoff kurz.\n\n"
                " Wenn nicht, schreibe 'kein upload'."
            )

    elif step == WIZARD_STEP_COLLECT_MATERIALS:
        current_topic = wizard.get('current_topic')
        wizard.setdefault('materials', {})[current_topic] = msg
        wizard['step'] = WIZARD_STEP_QUESTIONS
        response = (
            f"Alles klar zu '{current_topic}'. Hast du bereits konkrete Fragen?"
            " Falls nein, starte ich mit einer kurzen Erklärung des Themas."
        )

    elif step == WIZARD_STEP_QUESTIONS:
        current_topic = wizard.get('current_topic')
        module = wizard.get('module')
        materials = wizard.get('materials', {}).get(current_topic, "")
        wizard['step'] = WIZARD_STEP_FOLLOWUP
        low = msg.lower()
        if any(tok in low for tok in ["keine", "kein", "nein"]):
            ai_resp = ask_chatgpt_topic_help(module, current_topic, materials, "keine", api_key)
            response = ai_resp + "\n\nStell jederzeit Zwischenfragen oder schreibe 'weiter' für das nächste Thema."
        else:
            ai_resp = ask_chatgpt_topic_help(module, current_topic, materials, msg, api_key)
            response = ai_resp + "\n\nWenn du fertig bist, schreibe 'weiter' für das nächste Thema."

    elif step == WIZARD_STEP_FOLLOWUP:
        current_topic = wizard.get('current_topic')
        order = wizard.get('order', [])
        idx = wizard.get('order_index', 0)
        low = msg.lower()
        if any(tok in low for tok in ["weiter", "nächste", "next"]):
            next_idx = idx + 1
            if next_idx < len(order):
                wizard['order_index'] = next_idx
                wizard['current_topic'] = order[next_idx]
                wizard['step'] = WIZARD_STEP_COLLECT_MATERIALS
                response = (
                    f"Nächstes Thema: '{order[next_idx]}'. Lade kurz Materialien hoch oder beschreibe den Stoff."
                    " Wenn du nichts hast, schreibe 'kein upload'."
                )
            else:
                wizard['active'] = False
                wizard['step'] = WIZARD_STEP_PICK_MODULE
                response = "Du hast alle Themen durchgearbeitet. Wizard beendet."
        else:
            module = wizard.get('module')
            materials = wizard.get('materials', {}).get(current_topic, "")
            ai_resp = ask_chatgpt_topic_help(module, current_topic, materials, msg, api_key)
            response = ai_resp + "\n\nSchreibe 'weiter' für das nächste Thema oder frag weiter zu diesem Thema."

    # update timestamp and persist wizard state
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

    # Use ChatGPT to classify the user's intent. If ChatGPT fails, determine_intent
    # will return 'unknown' and we fall back to a simple keyword check.
    username = request.username
    api_key = pick_api_key(request.api_key)
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

    wizard_state = state.get('wizard') if state else None
    wizard_active = bool(wizard_state and wizard_state.get('active'))
    msg_low = request.message.strip().lower()
    stop_keywords = ("exit")

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
                    return {"response": "Bitte gib eine Zahl zwischen 0 und 30 ein."}
                
                # Save to state and ask next question
                with state_lock:
                    conversation_state[username]['reminder_days_tasks'] = days
                    conversation_state[username]['settings_step'] = 'ask_exam_days'
                    conversation_state[username]['ts'] = time.time()
                
                return {"response": f"Gut, ich erinnere dich {days} Tag(e) vor Aufgaben-Deadlines.\n\nWie viele Tage vor einer Klausur möchtest du erinnert werden? (z.B. 7 für eine Woche vorher)"}
            except ValueError:
                return {"response": "Bitte gib eine gültige Zahl ein (z.B. 1, 3, 7)."}
        
        elif step == 'ask_exam_days':
            # Try to parse the number
            try:
                days = int(msg)
                if days < 0 or days > 30:
                    return {"response": "Bitte gib eine Zahl zwischen 0 und 30 ein."}
                
                # Save settings and clear state
                task_days = state.get('reminder_days_tasks', 1)
                
                with state_lock:
                    if username in conversation_state:
                        del conversation_state[username]
                
                # Return settings to frontend for storage
                return {
                    "response": f"Alles klar! Deine Erinnerungseinstellungen wurden gespeichert:\n- Aufgaben: {task_days} Tag(e) vorher\n- Klausuren: {days} Tag(e) vorher\n\nIch werde dich entsprechend benachrichtigen!",
                    "settings": {
                        "reminder_days_tasks": task_days,
                        "reminder_days_exams": days
                    }
                }
            except ValueError:
                return {"response": "Bitte gib eine gültige Zahl ein (z.B. 1, 3, 7)."}
        
        # Fallback: should not reach here
        with state_lock:
            if username in conversation_state:
                del conversation_state[username]
        return {"response": "Ein Fehler ist aufgetreten. Bitte versuche es erneut."}

    # While wizard is active: skip intent detection; only allow explicit stop keyword
    if wizard_active:
        if any(msg_low.strip() == kw for kw in stop_keywords):
            with state_lock:
                user_state = conversation_state.get(username, {})
                user_state.pop('wizard', None)
                user_state['ts'] = time.time()
                conversation_state[username] = user_state
            return {"response": "Wizard beendet. Sag Bescheid, wenn ich wieder helfen soll."}

        wizard_response = _handle_wizard_message(username, request.message, state, api_key)
        if wizard_response:
            return {"response": wizard_response}
        # If wizard handler could not process, keep user in wizard and prompt to continue or stop
        return {"response": "Ich bin im Klausur-Wizard. Bitte beantworte die letzte Frage oder schreibe 'wizard beenden' zum Abbrechen."}

    # Quick keywords for starting the wizard without LLM
    if intent is None:
        if any(kw in msg_low for kw in ["klausurvorbereitung", "exam wizard", "exam prep", "vorbereitung", "lernplan", "wizard starten"]):
            intent = "start_exam_wizard"
        elif any(msg_low.strip() == kw for kw in stop_keywords):
            intent = "stop_exam_wizard"

    # Fast keyword-based intent detection to avoid unnecessary LLM calls
    if intent is None:
        # Check for settings/reminders
        if any(word in msg_low for word in ["einstellung", "erinnerung", "benachrichtigung", "notification", "settings", "reminder"]):
            intent = "settings"
        elif any(word in msg_low for word in ["klausurvorbereitung", "exam wizard", "exam prep", "vorbereitung", "lernplan", "wizard starten"]):
            intent = "start_exam_wizard"
        elif any(msg_low.strip() == kw for kw in stop_keywords):
            intent = "stop_exam_wizard"
        # Check for common Moodle-related keywords
        elif any(word in msg_low for word in ["moodle", "aufgabe", "termin", "deadline", "abgabe"]):
            intent = "get_moodle_appointments"
        # Check for Stine exam keywords
        elif any(word in msg_low for word in ["prüfung", "klausur", "exam"]):
            intent = "get_stine_exams"
        # Check for Stine messages
        elif "nachricht" in msg_low and "stine" in msg_low:
            intent = "get_stine_messages"
        # Check for email
        elif any(word in msg_low for word in ["mail", "e-mail", "email"]):
            intent = "get_mail"
        # Check for greetings
        elif any(word in msg_low for word in ["hallo", "hi", "hey", "guten tag", "servus"]):
            intent = "greeting"
        # Check for help
        elif any(word in msg_low for word in ["hilfe", "help", "wie funktioniert", "was kannst du"]):
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

    wizard_step_intents = set(WIZARD_INTENT_STEPS.keys())
    
    # Route based on detected intent
    if intent == "start_exam_wizard":
        base_state = state or {}
        wizard = _new_wizard_state()
        with state_lock:
            conversation_state[username] = {**base_state, 'wizard': wizard, 'ts': time.time()}
        return {"response": "Gern helfe ich dir bei der Klausurvorbereitung.\n\n"
                 " Du kannst den Vorbereitungs-Wizard jederzeit mit 'exit' abbrechen.\n\n"
                 " Damit ich dir helfen kann, muss ich dir zunächst ein paar Fragen stellen.\n"
                 " 1. Um welches Modul geht es?"}

    elif intent == "stop_exam_wizard":
        with state_lock:
            user_state = conversation_state.get(username, {})
            user_state.pop('wizard', None)
            user_state['ts'] = time.time()
            conversation_state[username] = user_state
        return {"response": "Wizard beendet. Sag Bescheid, wenn ich wieder helfen soll."}

    elif intent in wizard_step_intents:
        if not wizard_active:
            base_state = state or {}
            wizard = _new_wizard_state()
            with state_lock:
                conversation_state[username] = {**base_state, 'wizard': wizard, 'ts': time.time()}
            return {"response": "Ich starte den Klausur-Wizard. Welches Modul?"}
        wizard_response = _handle_wizard_message(username, request.message, state or {}, api_key)
        if wizard_response:
            return {"response": wizard_response}
        # fall through if no response

    if intent == "get_moodle_appointments":
        logging.info("[Chat] Processing Moodle appointments request")
        try:
            # Check cache first for scraped data AND ChatGPT response
            cached_data, cached_response = get_cached_scraped_data(username, 'moodle')
            if cached_data and cached_response:
                logging.info("[Chat] Using cached Moodle data and response")
                termine = cached_data
                response = cached_response
            else:
                # Cache miss - scrape and cache the data
                logging.info("[Chat] Cache miss - starting Moodle scraper")
                logging.info(f"[Chat] Username for scraper: {request.username}")
                termine = scrape_moodle_text(request.username, request.password)
                logging.info(f"[Chat] Scraper returned {len(termine)} characters")
                
                # Check if scraper returned an error
                if any(error_keyword in termine for error_keyword in ["Fehler", "nicht verfügbar", "Selenium", "WebDriver", "Chrome", "Failed", "Exception"]):
                    logging.warning(f"[Chat] Scraper returned error: {termine[:100]}")
                    return {"response": "Moodle ist gerade nicht erreichbar. Bitte versuche es später noch einmal."}
                
                # Ask ChatGPT to format the data
                logging.info("[Chat] Asking ChatGPT to format Moodle data")
                response = ask_chatgpt_moodle(termine, api_key)
                logging.info(f"[Chat] ChatGPT response length: {len(response)}")
                
                # Cache both raw data and ChatGPT response
                cache_scraped_data(username, 'moodle', termine, response)
            logging.info(f"[Chat] ChatGPT response length: {len(response)}")
            
            # If ChatGPT asked whether to add events to calendar, mark state so the next short reply
            # can be interpreted as consent/denial. We only set this for the requesting user.
            if response and "Soll ich dir die Termine auch in deinen Kalender eintragen?" in response:
                with state_lock:
                    # IMPORTANT: Store RAW scraper data, not formatted response
                    conversation_state[username] = { 'awaiting_calendar': True, 'raw_termine': termine, 'ts': time.time() }
                logging.info("[Chat] Calendar option offered - raw data stored in state")
            return {"response": response}
        except Exception as e:
            response = f"Fehler beim Abrufen: {e}"
            return {"response": response}
    elif intent == "get_stine_messages":
        return {"response": "Die Funktion zum Abrufen von Stine-Nachrichten ist noch nicht implementiert."}
    elif intent == "get_stine_exams":
        try:
            # Check cache first for scraped data AND ChatGPT response
            cached_data, cached_response = get_cached_scraped_data(username, 'stine_exams')
            if cached_data and cached_response:
                logging.info("[Chat] Using cached STINE data and response")
                exams_text = cached_data
                response = cached_response
            else:
                # Cache miss - scrape and cache the data
                exams_text = scrape_stine_exams(request.username, request.password)
                
                # Check if scraper returned an error
                if any(error_keyword in exams_text for error_keyword in ["Fehler", "nicht verfügbar", "Selenium", "WebDriver", "Chrome", "Failed", "Exception"]):
                    logging.warning(f"[Chat] STINE scraper returned error: {exams_text[:100]}")
                    return {"response": "STINE ist gerade nicht erreichbar. Bitte versuche es später noch einmal."}
                
                # Ask ChatGPT to format the data
                response = ask_chatgpt_exams(exams_text, api_key)
                
                # Cache both raw data and ChatGPT response
                cache_scraped_data(username, 'stine_exams', exams_text, response)
            
            # If ChatGPT asked whether to add events to calendar, mark state so the next short reply
            # can be interpreted as consent/denial. We only set this for the requesting user.
            if response and "Soll ich dir die Termine auch in deinen Kalender eintragen?" in response:
                with state_lock:
                    # IMPORTANT: Store RAW scraper data, not formatted response
                    conversation_state[username] = { 'awaiting_calendar': True, 'raw_termine': exams_text, 'ts': time.time() }
                logging.info("[Chat] Calendar option offered for STINE exams - raw data stored in state")
            return {"response": response}
        except Exception as e:
            response = f"Fehler beim Abrufen der Stine-Prüfungen: {e}"
            return {"response": response}
    elif intent == "get_mail":
        return {"response": "Die Funktion zum Abrufen von E-Mails ist noch nicht implementiert."}
    elif intent == "settings":
        # Start settings configuration dialog
        with state_lock:
            conversation_state[username] = {
                'configuring_settings': True,
                'settings_step': 'ask_task_days',
                'ts': time.time()
            }
        return {"response": "Lass uns deine Erinnerungseinstellungen konfigurieren! \n\nWie viele Tage vor einer Aufgaben-Deadline möchtest du erinnert werden? (z.B. 1 für einen Tag vorher, 3 für drei Tage vorher)"}
    elif intent == "greeting":
        return {"response": "Hallo! Ich kann dir bei Moodle-Terminen helfen. Frag z. B. 'Welche Termine habe ich?'"}
    elif intent == "help":
        return {"response": f"Du kannst nach 'Terminen' fragen. \n Formuliere z. B. 'Was sind meine Termine?'"}
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
            return {"response": "Fehler: Keine Termine verfügbar. Bitte erneut anfragen."}
        
        try:
            logging.info(f"[Chat] Calendar YES - using raw data ({len(termine)} chars)")
            _, ics_content = make_calendar_entries(termine, api_key)
            
            # Extract events from ICS for suggested_events
            suggested_events = extract_events_from_ics(ics_content)
            
            logging.info(f"[Chat] Calendar YES - extracted {len(suggested_events)} events")
            
            # Return only the suggested events as buttons, no ICS file download
            resp = {"suggested_events": suggested_events}
            return resp
        except Exception as e:
            response = f"Fehler beim Erstellen der Kalender-Einträge: {e}"
            logging.error(f"[Chat] Calendar entry creation failed: {e}")
            return {"response": response}
    elif intent == "calendar_no":
        # clear awaiting flag for this user
        with state_lock:
            if username in conversation_state:
                del conversation_state[username]
        return {"response": "Alles klar. Mit was kann ich dir sonst helfen?"}
    else:
        return {"response": "Entschuldigung, ich habe dich nicht verstanden. Du kannst nach Moodle-Terminen fragen oder den Klausur-Wizard starten."}


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
