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
            {"role": "system", "content": "Du bist ein hilfreicher Assistent, der Stine-Prüfungen für den Benutzer zusammenfasst und keine Rückfragen stellt."},
            {"role": "user", "content": " Nutze Markdown. Überschriften mit ##, fettgedruckte Labels mit **, und Aufzählungen mit -.\n"
             " Hier sind meine Stine-Prüfungen:\n" + exams_text + " Hier sind Einschränkungen die beachtet werden sollen: " +  latestMessage }
        ]
    )
    # Normalize the response text and append the calendar question (same wording used elsewhere)
    resp_text = response.choices[0].message.content + "\n\nSoll ich dir die Termine auch in deinen Kalender eintragen?"
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
        " Nutze Markdown. Überschriften mit ##, fettgedruckte Labels mit **, und Aufzählungen mit -.\n"
        " Hier sind meine Moodle-Aufgaben:\n" + termine + "\n\n"
        + "Beginne die Nachricht mit 'Hier sind deine Moodle-Aufgaben:'. Heute ist der " + datetime.date.today().isoformat() + ".\n\n"
        " Nenne die Termine abhängig vom heutigen Datum (z.B. 'morgen', 'in zwei Tagen'). Gib auch immer das jeweilige Modul für die Termine an.\n\n"
        " Unterscheide zwischen endenden und beginnenden Terminen.\n\n"
        " WICHTIG: Auch wenn mehrere Termine das selbe Datum haben, liste jeden Termin einzeln auf.\n\n"
        " WICHTIG: Beachte potentielle terminliche oder fachliche Einschränkungen in folgender Nutzereingabe.\n\n"
        "(z.B. Nur Termine für ein bestimmtes Modul oder nur Termine in den nächsten 3 Tagen oder ähnliches. Andere Wünsche in der Nutzeringabe können ignoriert werden).\n\n"
        " Hier die Nutzereingabe: " + latestMessage
    )
    response = client.chat.completions.create(
        model="gpt-5-mini",
        messages=[
            {"role": "system", "content": "Du bist ein hilfreicher Assistent, der Moodle-Aufgaben für den Benutzer zusammenfasst und keine Rückfragen stellt."},
            {"role": "user", "content": user_message}
        ]
    )
    resp_text = response.choices[0].message.content + "\nSoll ich dir die Termine auch in deinen Kalender eintragen?"
    return resp_text


def ask_chatgpt_topic_help(module: str, topic: str, materials: str, user_question: str, api_key: Optional[str]) -> str:
    """Generate an explanation for a given topic (exercises only if explicitly requested).

    Args:
        module: Course/module name provided by the user.
        topic: Topic the user is working on.
        materials: Free-text hints/notes the user provided (may be empty).
        user_question: Optional question or "keine" if none. If contains "aufgabe" or "übung", include exercises.
        api_key: API key to call the LLM.
    """
    try:
        from openai import OpenAI
    except ImportError:
        return "Fehler: 'openai' Paket nicht installiert."

    key = pick_api_key(api_key)
    if not key:
        return "Kein API-Key vorhanden. Bitte in den Einstellungen hinzufügen."

    client = OpenAI(api_key=key)
    materials_text = materials.strip() if materials else "Keine Materialien angegeben."
    question_text = user_question.strip() if user_question else "keine"
    
    # Check if exercises should be included
    include_exercises = any(kw in question_text.lower() for kw in ["aufgabe", "übung", "exercise"])

    system_msg = (
        "Du bist ein verständlicher Tutor. Antworte auf Deutsch und nutze Markdown. Benutze für deine Antworten immer nur wenige Sätze.\n"
        "Math darf als LaTeX in $...$ oder $$...$$ stehen.\n"
        "WICHTIG: Nutze immer diese Struktur exakt, mit Zeilenumbrüchen wie gezeigt (ersetze Thema mit dem aktuellen Thema):\n\n"
        "## Thema\n\n"
        "**Kurz-Erklärung:** (2-4 Sätze)\n\n"
        "**Kernpunkte:**\n"
        "- Punkt 1\n"
        "- Punkt 2\n"
        "- Punkt 3\n\n"
        "Schreibe Listen IMMER mit '- ' am Anfang jeder Zeile, keine anderen Formate!\n"
        " Nutze Überschriften mit ##, fettgedruckte Labels mit **, und Aufzählungen mit -.\n"
        " Frag nicht selbstständig nach Fragen oder Übungen, sondern warte auf die Nutzeranfrage.\n"
        " Schlage nicht vor, dass du irgendetwas tun kannst, sondern warte auf die Nutzeranfrage."
    )
    
    if include_exercises:
        system_msg += (
            "**Übungsaufgaben (ohne Lösungen):**\n"
            "1. Erste Aufgabe\n"
            "2. Zweite Aufgabe\n"
            "3. Dritte Aufgabe\n\n"
        )
    else:
        system_msg += (
            "Gib KEINE Übungsaufgaben, es sei denn, der Nutzer fragt danach.\n\n"
        )
    
    system_msg += (
        "Wenn eine konkrete Frage gestellt wurde, beantworte sie zuerst kurz.\n"
        "Lade immer zu Zwischenfragen ein.\n"
    )

    user_msg = (
        f"Modul: {module or 'unbekannt'}\n"
        f"Thema: {topic or 'unbekannt'}\n"
        f"Materialhinweise: {materials_text}\n"
        f"Frage: {question_text}"
    )

    response = client.chat.completions.create(
        model="gpt-5-mini",
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg}
        ],
    )
    return response.choices[0].message.content


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
        "start_exam_wizard",
        "stop_exam_wizard",
        "wizard_pick_module",
        "wizard_pick_topics",
        "wizard_pick_order",
        "wizard_collect_materials",
        "wizard_questions_or_walkthrough",
        "wizard_followup",
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
        + "If the user wants to start exam prep (e.g., Klausurvorbereitung, Lernplan, Wizard starten), return 'start_exam_wizard'.\n"
        + "If the user wants to stop or exit the exam prep wizard, return 'stop_exam_wizard'.\n"
        + "If the user provides module names, return 'wizard_pick_module'.\n"
        + "If the user lists topics/chapters, return 'wizard_pick_topics'.\n"
        + "If the user chooses or asks for the learning order, return 'wizard_pick_order'.\n"
        + "If the user provides uploads/links/material, return 'wizard_collect_materials'.\n"
        + "If the user says they have/no questions or wants explanation/Übungen, return 'wizard_questions_or_walkthrough'.\n"
        + "If the user continues within the wizard (follow-ups), return 'wizard_followup'.\n"
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
