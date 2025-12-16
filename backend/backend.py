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
from src.llm import ask_chatgpt_moodle, ask_chatgpt_exams, determine_intent, pick_api_key
from src.ics_calendar import make_calendar_entries
from src.utils import resolve_frontend_dist

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

# Cache for ChatGPT responses to avoid expensive re-scraping and re-processing
# Keyed by (username, data_type) -> { 'response': str, 'ts': float }
response_cache = {}
cache_lock = threading.Lock()
CACHE_EXPIRY_SECONDS = 3600  # cache expires after 1 hour

if FRONTEND_DIST:
    assets_path = os.path.join(FRONTEND_DIST, "assets")
    if os.path.isdir(assets_path):
        app.mount("/assets", StaticFiles(directory=assets_path), name="assets")


def get_cached_response(username: str, data_type: str):
    """Get cached ChatGPT response if available and not expired.
    
    Args:
        username: User identifier
        data_type: Type of data ('moodle' or 'stine_exams')
    
    Returns:
        Cached response string or None if cache miss/expired
    """
    cache_key = (username, data_type)
    
    with cache_lock:
        cached = response_cache.get(cache_key)
        if cached:
            # Check if cache is still valid
            if time.time() - cached.get('ts', 0) < CACHE_EXPIRY_SECONDS:
                logging.info(f"Cache hit for {data_type} response (user: {username})")
                return cached['response']
            else:
                # Cache expired, remove it
                logging.info(f"Cache expired for {data_type} response (user: {username})")
                del response_cache[cache_key]
    
    return None


def cache_response(username: str, data_type: str, response: str):
    """Store ChatGPT response in cache.
    
    Args:
        username: User identifier
        data_type: Type of data ('moodle' or 'stine_exams')
        response: ChatGPT response to cache
    """
    cache_key = (username, data_type)
    with cache_lock:
        response_cache[cache_key] = {'response': response, 'ts': time.time()}
    logging.info(f"Cached {data_type} response (user: {username})")


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

    # If the bot previously asked about adding to calendar, interpret simple yes/no locally
    intent = None
    if state and state.get('awaiting_calendar'):
        # Interpret a short affirmative/negative reply without calling ChatGPT
        msg_low = request.message.strip().lower()
        if msg_low in ("ja", "j", "yes", "y", "klar", "gerne"):
            intent = "calendar_yes"
        elif msg_low in ("nein", "n", "no"):
            intent = "calendar_no"
        # If message isn't a clear yes/no, fall back to full intent detection (below)

    # Fast keyword-based intent detection to avoid unnecessary LLM calls
    if intent is None:
        msg_low = request.message.strip().lower()
        # Check for common Moodle-related keywords
        if any(word in msg_low for word in ["moodle", "aufgabe", "termin", "deadline", "abgabe"]):
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
    # Route based on detected intent
    if intent == "get_moodle_appointments":
        try:
            # Check cache first
            cached_response = get_cached_response(username, 'moodle')
            if cached_response:
                response = cached_response
            else:
                # Cache miss - scrape and process
                termine = scrape_moodle_text(request.username, request.password)
                response = ask_chatgpt_moodle(termine, api_key)
                # Cache the response
                cache_response(username, 'moodle', response)
            
            # If ChatGPT asked whether to add events to calendar, mark state so the next short reply
            # can be interpreted as consent/denial. We only set this for the requesting user.
            if response and "Soll ich dir die Termine auch in deinen Kalender eintragen?" in response:
                latestMessage = response
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
            # Check cache first
            cached_response = get_cached_response(username, 'stine_exams')
            if cached_response:
                response = cached_response
            else:
                # Cache miss - scrape and process
                exams_text = scrape_stine_exams(request.username, request.password)
                response = ask_chatgpt_exams(exams_text, api_key)
                # Cache the response
                cache_response(username, 'stine_exams', response)
            
            # If ChatGPT asked whether to add events to calendar, mark state so the next short reply
            # can be interpreted as consent/denial. We only set this for the requesting user.
            if response and "Soll ich dir die Termine auch in deinen Kalender eintragen?" in response:
                latestMessage = response
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
