import re
from datetime import datetime
import dateparser
from apps.ai.response_generator import call_gemini_api

COMMON_WORDS = {
    "cita", "horario", "agenda", "atención", "precio", "servicio", "servicios",
    "catálogo", "reserva", "cancelar", "información", "hola", "buenos días", "buenas tardes", "buenas noches",
    "disponibilidad", "doctor", "doctora", "especialidad", "especialista"
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
    # Intención específica para horario de atención
    if "horario" in text or "atención" in text:
        return "ask_schedule"
    if "agendar" in text or "cita" in text or "reservar" in text:
        return "schedule_appointment"
    if "cancelar" in text or "anular" in text or "eliminar" in text:
        return "cancel_appointment"
    if "quién eres" in text or "eres un bot" in text or "qué puedes hacer" in text:
        return "ask_bot_identity"
    return "unknown"

async def extract_contact_info(message_text):
    result = {"name": None, "datetime": None}

    # Buscar nombre usando patrones comunes
    patterns = [
        r"mi nombre es ([a-zA-ZáéíóúÁÉÍÓÚñÑ ]+)",
        r"soy ([a-zA-ZáéíóúÁÉÍÓÚñÑ ]+)",
        r"me llamo ([a-zA-ZáéíóúÁÉÍÓÚñÑ ]+)",
    ]
    for pattern in patterns:
        name_match = re.search(pattern, message_text, re.IGNORECASE)
        if name_match:
            name = name_match.group(1).strip()
            if name and len(name) > 1:
                result["name"] = name
                break

    # Si no hay nombre, intenta con patrón de mensaje corto (2-4 palabras solo letras), pero filtra palabras comunes
    if not result["name"]:
        parts = message_text.strip().split()
        parts_lower = [p.lower() for p in parts]
        if (
            1 < len(parts) <= 4 and
            all(re.match(r"^[a-zA-ZáéíóúÁÉÍÓÚñÑ]+$", part) for part in parts) and
            not any(word in COMMON_WORDS for word in parts_lower)
        ):
            result["name"] = message_text.strip()
        else:
            # Si no, intenta con Gemini
            gemini_prompt = (
                f"¿El siguiente mensaje contiene únicamente un nombre completo de una persona? "
                f"Si es así, responde solo con el nombre, si no, responde con 'NO'. Mensaje: '{message_text}'"
            )
            gemini_response = await call_gemini_api(gemini_prompt)
            gemini_response = gemini_response.strip().replace('"', '').replace("'", "")
            if gemini_response.upper() != "NO" and len(gemini_response.split()) >= 2:
                result["name"] = gemini_response

    # Fecha/hora: primero intenta con dateparser
    msg_for_date = clean_for_dateparser(message_text)
    parsed_dt = dateparser.parse(
        msg_for_date,
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
        # INTENTAR CON GEMINI
        gemini_prompt = (
            f"Extrae la fecha y hora exactas (en formato ISO 8601: YYYY-MM-DD HH:MM) del siguiente mensaje en español. "
            f"Si el mensaje no contiene fecha/hora, responde solo con 'NO'. "
            f"Mensaje: '{message_text}'"
        )
        gemini_response = await call_gemini_api(gemini_prompt)
        gemini_response = gemini_response.strip().replace('"', '').replace("'", "")
        # Intenta parsear la respuesta de Gemini a datetime
        if gemini_response.upper() != "NO":
            try:
                # Gemini puede dar solo día, o con hora, o con T. Soportamos ambos
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
            except Exception:
                pass

    return result