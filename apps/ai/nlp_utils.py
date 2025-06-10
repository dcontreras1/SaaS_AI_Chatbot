import re
from datetime import datetime
import dateparser
from apps.ai.response_generator import gemini_simple_prompt

COMMON_WORDS = {
    "cita", "citas", "agendar", "agendamiento", "reservar", "reserva", "cancelar", "cancelación",
    "horario", "horarios", "disponibilidad", "programar", "confirmar", "confirmación",
    "agenda", "atención", "día", "fecha", "hora", "minuto", "reprogramar",
    "información", "turno", "turnos", "solicitar", "solicitud",
    "hola", "buenos días", "buenas tardes", "buenas noches", "adiós", "gracias"
}

def clean_for_dateparser(text):
    text = re.sub(r"\b(el|la|los|las|del|de|a|para|el día|día)\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text)
    return text.strip()

async def detect_intent(message_text, session_data=None):
    greetings = ["hola", "buenos días", "buenas tardes", "buenas noches"]
    farewells = ["adiós", "gracias", "hasta luego", "nos vemos"]

    text = message_text.lower().strip()
    if any(g in text for g in greetings):
        return "greet"
    if any(f in text for f in farewells):
        return "farewell"
    if "horario" in text or "atención" in text:
        return "ask_schedule"
    if "agendar" in text or "cita" in text or "reservar" in text:
        return "schedule_appointment"
    if "cancelar" in text and ("cita" in text or "reserva" in text):
        return "cancel_appointment"
    if "confirmar" in text:
        return "confirm_appointment"
    if "reprogramar" in text or ("cambiar" in text and ("cita" in text or "reserva" in text)):
        return "reschedule_appointment"
    if "información" in text:
        return "ask_information"

    # Si ninguna de las intenciones anteriores coincide, usar Gemini
    gemini_prompt = (
        f"Dada la conversación y el siguiente mensaje: '{message_text}', "
        f"¿cuál es la intención principal del usuario? Elige entre 'greet', 'farewell', "
        f"'schedule_appointment', 'cancel_appointment', 'confirm_appointment', "
        f"'reschedule_appointment', 'ask_schedule', 'ask_information', 'unknown'. "
        f"Considera también el estado de la sesión: {session_data}. "
        f"Responde solo con la intención detectada."
    )
    intent_from_gemini = await gemini_simple_prompt(gemini_prompt)
    intent_from_gemini = intent_from_gemini.strip().lower()

    if intent_from_gemini in [
        'greet', 'farewell', 'schedule_appointment', 'cancel_appointment',
        'confirm_appointment', 'reschedule_appointment', 'ask_schedule',
        'ask_information', 'unknown'
    ]:
        return intent_from_gemini
    return "unknown"

async def extract_info(message_text, session_data=None, user_phone=None):
    result = {}

    text = message_text.lower().strip()

    # Extraer nombre (opcional)
    name_match = re.search(r"(me llamo|soy|mi nombre es)\s+([a-záéíóúüñ\s]+)", text)
    if name_match:
        name_parts = name_match.group(2).split()
        result["name"] = " ".join([part.capitalize() for part in name_parts if part])

    # El número de teléfono siempre proviene del canal/session/contexto
    if user_phone:
        result["phone"] = user_phone

    # Extraer fecha y hora usando dateparser
    cleaned_text_for_dateparser = clean_for_dateparser(text)
    parsed_dt = dateparser.parse(
        cleaned_text_for_dateparser,
        languages=['es'],
        settings={
            'PREFER_DATES_FROM': 'future',
            'RELATIVE_BASE': datetime.now(),
            'DATE_ORDER': 'DMY'
        }
    )
    if parsed_dt:
        result["datetime"] = parsed_dt
    else:
        # INTENTAR CON GEMINI si dateparser no lo encuentra
        gemini_prompt = (
            f"Extrae la fecha y hora exactas (en formato ISO 8601:YYYY-MM-DD HH:MM) del siguiente mensaje en español. "
            f"Si el mensaje no contiene fecha/hora o no es claro, responde solo con 'NO'. "
            f"Considera el contexto de la conversación: {session_data}. "
            f"Mensaje: '{message_text}'"
        )
        gemini_response = await gemini_simple_prompt(gemini_prompt)
        gemini_response = gemini_response.strip().replace('"', '').replace("'", "")

        if gemini_response.upper() != "NO":
            try:
                if "T" in gemini_response:
                    possible_dt = gemini_response.replace("T", " ")
                else:
                    possible_dt = gemini_response

                parsed_from_gemini = dateparser.parse(
                    possible_dt,
                    languages=['es'],
                    settings={
                        'PREFER_DATES_FROM': 'future',
                        'RELATIVE_BASE': datetime.now(),
                        'DATE_ORDER': 'DMY'
                    }
                )
                if parsed_from_gemini:
                    result["datetime"] = parsed_from_gemini
            except Exception as e:
                print(f"DEBUG: Error parsing datetime from Gemini response '{gemini_response}': {e}")

    return result