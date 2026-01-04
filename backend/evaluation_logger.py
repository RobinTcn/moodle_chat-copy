# evaluation_logger.py
import json
import os
import time
import uuid
import hashlib
import re
import getpass
import platform
from datetime import datetime
from typing import Optional
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Any


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _config_dir() -> Path:
    return Path.home() / ".config" / "studibot"


def _log_path(conv_id: Optional[str] = None) -> Path:
    # Zeitstempel für "pro Session / Start"
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    # Nutzer/Host nur als Info (optional)
    user = re.sub(r"[^A-Za-z0-9._-]+", "_", getpass.getuser())
    host = re.sub(r"[^A-Za-z0-9._-]+", "_", platform.node())

    # conv_id kurz machen 
    conv = (conv_id or "unknown").strip()
    conv_safe = re.sub(r"[^A-Za-z0-9._-]+", "_", conv)
    conv_short = conv_safe[:8]  # z.B. 05da097b statt ganze UUID

    return _config_dir() / f"eval_{ts}__{user}@{host}__conv-{conv_short}.jsonl"


def _pseudonymize_user(username: str) -> str:
    """
    Pseudonymisierte User-ID (stabil, aber ohne Klarname im Log).
    SALT kann per Env gesetzt werden, damit Hash nicht trivial ist.
    """
    salt = os.getenv("STUDIBOT_LOG_SALT", "studibot_default_salt_change_me")
    raw = (salt + "|" + username).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _append_jsonl(record: dict[str, Any]) -> None:
    conv_id = record.get("conv_id")
    path = _log_path(record.get("conv_id"))


    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


@dataclass
class TurnTimer:
    conv_id: str
    turn_id: str
    user_id: str
    ts_user: str
    t0: float  # perf_counter start


def start_turn(username: str, conv_id: Optional[str] = None, user_message: Optional[str] = None) -> TurnTimer:
    conv = conv_id or str(uuid.uuid4())
    turn = str(uuid.uuid4())
    user_id = _pseudonymize_user(username)
    ts_user = _utc_iso()

    if user_message is not None:
        _append_jsonl({
            "event": "user_message",
            "conv_id": conv,
            "turn_id": turn,
            "user_id": user_id,
            "ts": ts_user,
            "text": user_message,
            "text_len": len(user_message),
        })

    return TurnTimer(conv_id=conv, turn_id=turn, user_id=user_id, ts_user=ts_user, t0=time.perf_counter())


def end_turn(timer: TurnTimer, bot_message: str, intent: Optional[str] = None) -> dict[str, Any]:
    ts_bot = _utc_iso()
    duration_ms = int((time.perf_counter() - timer.t0) * 1000)

    record = {
        "event": "assistant_message",
        "conv_id": timer.conv_id,
        "turn_id": timer.turn_id,
        "user_id": timer.user_id,
        "ts": ts_bot,
        "duration_ms": duration_ms,
        "intent": intent,
        "text": bot_message,
        "text_len": len(bot_message),
    }
    _append_jsonl(record)
    return {"conv_id": timer.conv_id, "turn_id": timer.turn_id, "ts": ts_bot, "duration_ms": duration_ms}
