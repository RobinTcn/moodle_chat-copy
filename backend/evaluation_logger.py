import json
import os
import time
import uuid
import hashlib
import re
import getpass
import platform
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Any

# Cache: (conv_id, session_id) -> Path (damit pro Session nur eine Datei entsteht)
_SESSION_LOG_PATHS: dict[tuple[str, str], Path] = {}

# Fallback: wenn niemand eine session_id übergibt, bleibt es pro Prozess eine Session
_DEFAULT_SESSION_ID = os.getenv("STUDIBOT_SESSION_ID") or str(uuid.uuid4())


def new_session_id() -> str:
    """Beim Öffnen eines Chats einmal aufrufen und dann bei jeder Nachricht mitschicken."""
    return str(uuid.uuid4())


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _config_dir() -> Path:
    # Logs im "logs" Ordner im Projekt-Root speichern
    return Path(__file__).parent.parent / "logs"


def _safe_id(s: str, max_len: int = 32) -> str:
    s = (s or "unknown").strip()
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", s)
    return s[:max_len] if max_len else s


def _log_path(conv_id: str, session_id: str) -> Path:
    conv_safe = _safe_id(conv_id, max_len=48)
    sess_safe = _safe_id(session_id, max_len=48)

    key = (conv_safe, sess_safe)
    if key in _SESSION_LOG_PATHS:
        return _SESSION_LOG_PATHS[key]

    # Einmaliger Zeitstempel PRO SESSION (nicht pro Nachricht)
    session_ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    user = _safe_id(getpass.getuser(), max_len=48)
    host = _safe_id(platform.node(), max_len=80)

    conv_short = conv_safe[:12]
    sess_short = sess_safe[:8]

    path = _config_dir() / f"eval_{session_ts}__{user}@{host}__conv-{conv_short}__sess-{sess_short}.jsonl"
    _SESSION_LOG_PATHS[key] = path
    return path


def _pseudonymize_user(username: str) -> str:
    """
    Pseudonymisierte User-ID (stabil, aber ohne Klarname im Log).
    SALT kann per Env gesetzt werden, damit Hash nicht trivial ist.
    """
    salt = os.getenv("STUDIBOT_LOG_SALT", "studibot_default_salt_change_me")
    raw = (salt + "|" + username).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _append_jsonl(record: dict[str, Any]) -> None:
    conv_id = record.get("conv_id") or "unknown"
    session_id = record.get("session_id") or _DEFAULT_SESSION_ID

    path = _log_path(conv_id, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


@dataclass
class TurnTimer:
    conv_id: str
    session_id: str
    turn_id: str
    user_id: str
    ts_user: str
    t0: float  # perf_counter start


def start_turn(
    username: str,
    conv_id: Optional[str] = None,
    session_id: Optional[str] = None,
    user_message: Optional[str] = None
) -> TurnTimer:
    # conv_id = "Conversation" (kann stabil sein)
    conv = conv_id or str(uuid.uuid4())

    # session_id = "Chat-Öffnung" (muss pro Öffnung neu sein!)
    sess = session_id or _DEFAULT_SESSION_ID

    turn = str(uuid.uuid4())
    user_id = _pseudonymize_user(username)
    ts_user = _utc_iso()

    if user_message is not None:
        _append_jsonl({
            "event": "user_message",
            "conv_id": conv,
            "session_id": sess,
            "turn_id": turn,
            "user_id": user_id,
            "ts": ts_user,
            "text": user_message,
            "text_len": len(user_message),
        })

    return TurnTimer(
        conv_id=conv,
        session_id=sess,
        turn_id=turn,
        user_id=user_id,
        ts_user=ts_user,
        t0=time.perf_counter()
    )


def end_turn(timer: TurnTimer, bot_message: str, intent: Optional[str] = None) -> dict[str, Any]:
    ts_bot = _utc_iso()
    duration_ms = int((time.perf_counter() - timer.t0) * 1000)

    record = {
        "event": "assistant_message",
        "conv_id": timer.conv_id,
        "session_id": timer.session_id,
        "turn_id": timer.turn_id,
        "user_id": timer.user_id,
        "ts": ts_bot,
        "duration_ms": duration_ms,
        "intent": intent,
        "text": bot_message,
        "text_len": len(bot_message),
    }
    _append_jsonl(record)
    return {
        "conv_id": timer.conv_id,
        "session_id": timer.session_id,
        "turn_id": timer.turn_id,
        "ts": ts_bot,
        "duration_ms": duration_ms
    }
