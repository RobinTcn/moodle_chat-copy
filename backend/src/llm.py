"""ChatGPT/LLM interaction and intent detection."""
import asyncio
import datetime
import logging
import os
from typing import Optional



def pick_api_key(provided: Optional[str]) -> Optional[str]:
    """Pick the API key from provided value or environment."""
    key = (provided or "").strip()
    if key:
        return key
    env_key = os.getenv("OPENAI_API_KEY", "").strip()
    return env_key or None


def ask_chatgpt_exams(exams_text: str, api_key: Optional[str]) -> str:
    from backend import latestMessage
    """Send exam data to ChatGPT and return formatted response."""
    try:
        from openai import OpenAI
    except ImportError:
        return "Fehler: 'openai' Paket nicht installiert."

    key = pick_api_key(api_key)
    if not key:
        return "Kein API-Key vorhanden. Bitte in der App speichern und erneut versuchen."

    client = OpenAI(api_key=key)
    response = client.chat.completions.create(
        model="gpt-5-mini",
        messages=[
            {"role": "system", "content": "Du bist ein hilfreicher Assistent, der Stine-Prüfungen für den Benutzer zusammenfasst."},
            {"role": "user", "content": "Hier sind meine Stine-Prüfungen:\n" + exams_text + " Hier sind Einschränkungen die beachtet werden sollen: " +  latestMessage }
        ]
    )
    # Normalize the response text and append the calendar question (same wording used elsewhere)
    resp_text = response.choices[0].message.content + "\nSoll ich dir die Termine auch in deinen Kalender eintragen?"
    return resp_text


def ask_chatgpt_moodle(termine: str, api_key: Optional[str]) -> str:
    """Send Moodle appointments to ChatGPT and return formatted response."""
    from backend import latestMessage
    try:
        from openai import OpenAI
    except ImportError:
        return "Fehler: 'openai' Paket nicht installiert."

    key = pick_api_key(api_key)
    if not key:
        return "Kein API-Key vorhanden. Bitte in der App speichern und erneut versuchen."

    client = OpenAI(api_key=key)
    user_message = (
        "Hier sind meine Moodle-Aufgaben:\n" + termine 
        + "Beginne die Nachricht mit 'Hier sind deine Moodle-Aufgaben:'. Heute ist der " + datetime.date.today().isoformat() 
        + ". Nenne die Termine abhängig vom heutigen Datum (z.B. 'morgen', 'in zwei Tagen'). Gib auch immer das jeweilige Modul für die Termine an."
        + " Unterscheide zwischen endenden und beginnenden Terminen."
        + " WICHTIG: Auch wenn mehrere Termine das selbe Datum haben, liste jeden Termin einzeln auf."
        + " WICHTIG: Beachte potentielle terminliche oder fachliche Einschränkungen in folgender Nutzereingabe."
        + "(z.B. Nur Termine für ein bestimmtes Modul oder nur Termine in den nächsten 3 Tagen oder ähnliches. Andere Wünsche in der Nutzeringabe können ignoriert werden)"
        + "Hier die Nutzereingabe: " + latestMessage
    )
    response = client.chat.completions.create(
        model="gpt-5-mini",
        messages=[
            {"role": "system", "content": "Du bist ein hilfreicher Assistent, der Moodle-Aufgaben für den Benutzer zusammenfasst."},
            {"role": "user", "content": user_message}
        ]
    )
    resp_text = response.choices[0].message.content + "\nSoll ich dir die Termine auch in deinen Kalender eintragen?"
    return resp_text


async def determine_intent(message: str, api_key: Optional[str]) -> str:
    """Asynchronously determine the user's intent using ChatGPT.

    Retries on transient errors to be more robust when many requests arrive quickly.
    """
    msg = message.strip()
    # Add calendar_yes/calendar_no so short replies like 'Ja'/'Nein' are classified
    labels = [
        "get_moodle_appointments",
        "get_stine_messages",
        "get_stine_exams",
        "get_mail",
        "greeting",
        "help",
        "calendar_yes",
        "calendar_no",
        "unknown",
    ]

    prompt = (
        "Classify the user's message into exactly one of the following intent labels: "
        + ", ".join(labels)
        + ".\nRespond with only the intent label (one of the labels) and nothing else.\n"
        + "If the user asks about Moodle appointments, deadlines or 'Aufgaben', return 'get_moodle_appointments'.\n"
        + "If the user asks about Stine messages or 'Stine Nachrichten', return 'get_stine_messages'.\n"
        + "If the user asks about Stine exams or 'Stine Prüfungen', return 'get_stine_exams'.\n"
        + "If the user asks about email or 'E-Mail', return 'get_mail'.\n"
        + "If the message is a greeting (hello, hi, hallo) return 'greeting'.\n"
        + "If the user asks for help or how to use the bot return 'help'.\n"
        + "If the user replies with an affirmative like 'ja' (German) or 'yes', return 'calendar_yes'.\n"
        + "If the user replies with a negative like 'nein' (German) or 'no', return 'calendar_no'.\n"
        + f"User message: \"{msg}\"\n"
    )

    # Blocking call will run in a thread to avoid blocking the event loop.
    def _call_openai(inner_prompt: str):
        try:
            from openai import OpenAI
        except Exception:
            raise
        key = pick_api_key(api_key)
        if not key:
            raise RuntimeError("Kein API-Key konfiguriert")
        client = OpenAI(api_key=key)
        response = client.chat.completions.create(
            model="gpt-5-mini",
            messages=[{"role": "user", "content": inner_prompt}]
        )
        return response.choices[0].message.content

    max_retries = 1
    backoff_base = 0.5
    for attempt in range(1, max_retries + 1):
        try:
            response = await asyncio.to_thread(_call_openai, prompt)
            # parse the model response robustly
            intent_text = response.strip().splitlines()[0].strip() if response else ""
            if intent_text in labels:
                return intent_text
            for lab in labels:
                if lab in response:
                    return lab
            logging.info("ChatGPT returned unexpected intent text (attempt %d): %s", attempt, response)
            # If model returned something unexpected, retry a couple times
        except Exception as e:
            logging.warning("Attempt %d: Error calling ChatGPT for intent detection: %s", attempt, e)

        # backoff before retrying
        if attempt < max_retries:
            await asyncio.sleep(backoff_base * (2 ** (attempt - 1)))

    # All retries failed or response couldn't be parsed -> fallback
    logging.error("Intent detection failed after %d attempts for message: %s", max_retries, msg)
    return "unknown"
