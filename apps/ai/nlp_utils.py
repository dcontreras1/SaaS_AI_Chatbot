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

    # Fallback a Gemini si no hay match rápido
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

async def extract_info(message_text, session_data=None, user_phone=None, slot=None, options=None):
    """
    Extrae información relevante de un mensaje. Si se proveen slot y options,
    usa Gemini para deducir el valor adecuado aunque tenga errores ortográficos, etc.
    Si no, intenta extraer nombre y fecha/hora como antes.
    """
    result = {}

    text = message_text.lower().strip()

    # EXTRACCIÓN DE OPCIONES DE SLOT (DOCTOR, SERVICIO, ETC)
    if slot and options:
        prompt = (
            f"Eres un asistente virtual para agendar citas por WhatsApp.\n"
            f"El usuario ha enviado el siguiente mensaje: \"{message_text}\"\n"
            f"Debes extraer el valor para el campo \"{slot}\".\n"
            f"Opciones válidas para este campo: {options}\n"
            f"- Si el usuario menciona una de las opciones (aunque tenga errores ortográficos, palabras extra, o escriba de manera poco formal), devuélvela exactamente como aparece en la lista de opciones.\n"
            f"- Si el usuario no menciona una opción válida, responde con None.\n"
            f"- Si hay varias opciones mencionadas, escoge la que más se parezca a lo que el usuario escribió.\n"
            f"Solo responde con el valor exacto de la opción, o None."
        )
        gemini_resp = await gemini_simple_prompt(prompt)
        value = gemini_resp.strip().replace('"', '').replace("'", "")
        if value.lower() == "none":
            return {slot: None}
        return {slot: value}

    # EXTRACCIÓN DE NOMBRE (si aplica)
    gemini_name_prompt = (
        f"Extrae únicamente el nombre completo del usuario, si es que lo menciona, del siguiente mensaje en español. "
        f"No incluyas frases adicionales, solo el nombre. Si el mensaje no contiene nombre, responde únicamente con 'NO'.\n"
        f"Mensaje: '{message_text}'"
    )
    gemini_name = (await gemini_simple_prompt(gemini_name_prompt)).strip().replace('"', '').replace("'", "")
    if gemini_name.upper() != "NO":
        result["name"] = " ".join([part.capitalize() for part in gemini_name.split()])

    if user_phone:
        result["phone"] = user_phone

    # EXTRACCIÓN DE FECHA Y HORA
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