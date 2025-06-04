# apps/ai/nlp_utils.py
import re
from datetime import datetime
import dateparser
from apps.ai.response_generator import call_gemini_api # Asegúrate de que esta importación sea correcta

COMMON_WORDS = {
    "cita", "horario", "agenda", "atención", "precio", "servicio", "servicios",
    "catálogo", "reserva", "cancelar", "información", "hola", "buenos días", "buenas tardes", "buenas noches",
    "disponibilidad", "doctor", "doctora", "especialidad", "especialista"
}

def clean_for_dateparser(text):
    text = re.sub(r"\\b(el|la|los|las|del|de|a|para|el día|día)\\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\\s+", " ", text)
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
    if "cancelar" in text and ("cita" in text or "reserva" in text):
        return "cancel_appointment"
    if "precio" in text or "costo" in text or "valor" in text:
        return "ask_pricing"
    if "catálogo" in text or "servicios" in text or "productos" in text:
        return "ask_catalog"
    if "ayuda" in text or "puedes hacer" in text or "funcionalidades" in text:
        return "ask_bot_capabilities"
    if "quién eres" in text or "eres un bot" in text or "tu nombre" in text:
        return "ask_bot_identity"

    # Si ninguna de las intenciones anteriores coincide, usar Gemini
    gemini_prompt = (
        f"Dada la conversación y el siguiente mensaje: '{message_text}', "
        f"¿cuál es la intención principal del usuario? Elige entre 'greet', 'farewell', "
        f"'schedule_appointment', 'cancel_appointment', 'ask_schedule', 'ask_catalog', "
        f"'ask_pricing', 'ask_bot_identity', 'ask_bot_capabilities', 'ask_for_help', 'unknown', 'provide_contact_info'. "
        f"Considera también el estado de la sesión: {session_data}. " # Aquí se puede usar session_data
        f"Responde solo con la intención detectada."
    )
    intent_from_gemini = await call_gemini_api(gemini_prompt)
    intent_from_gemini = intent_from_gemini.strip().lower()

    if intent_from_gemini in [
        'greet', 'farewell', 'schedule_appointment', 'cancel_appointment',
        'ask_schedule', 'ask_catalog', 'ask_pricing', 'ask_bot_identity',
        'ask_bot_capabilities', 'ask_for_help', 'unknown', 'provide_contact_info'
    ]:
        return intent_from_gemini
    return "unknown" # Fallback si Gemini devuelve algo inesperado


async def extract_contact_info(message_text, session_data=None): # MODIFICADO: Aceptar session_data
    result = {
        "name": None,
        "phone": None,
        "datetime": None,
        "cancel_id": None
    }
    
    text = message_text.lower()

    # Extraer nombre (simple, buscar patrones comunes o capitalización)
    # Esto es una extracción muy básica. Para producción se necesitaría un NLP más avanzado.
    name_patterns = [
        r"(?:mi nombre es|soy)\s+([a-záéíóúüñ\s]+)",
        r"([a-záéíóúüñ]+\s+[a-záéíóúüñ]+(?:\s+[a-záéíóúüñ]+)?)" # Nombres con 2 o 3 palabras
    ]
    for pattern in name_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            # Capitalizar el nombre extraído
            name_parts = match.group(1).strip().split()
            result["name"] = " ".join([part.capitalize() for part in name_parts if part])
            break

    # Extraer número de teléfono (asumiendo formato colombiano o similar)
    phone_patterns = [
        r"(\+?\d{1,3}[\s-]?\d{3}[\s-]?\d{3}[\s-]?\d{4})\b",  # +XX XXX XXX XXXX o XXX XXX XXXX
        r"\b(3\d{9})\b" # Números de 10 dígitos que empiezan por 3 (Colombia)
    ]
    for pattern in phone_patterns:
        match = re.search(pattern, message_text) # Usar message_text original para el teléfono
        if match:
            result["phone"] = match.group(1).replace(" ", "").replace("-", "")
            break

    # Extraer ID de cancelación (números puros que podrían ser IDs)
    cancel_id_match = re.search(r"\b(id|número de cita|cita número)?\s*(\d+)\b", text, re.IGNORECASE)
    if cancel_id_match:
        result["cancel_id"] = int(cancel_id_match.group(2))

    # Extraer fecha y hora usando dateparser
    cleaned_text_for_dateparser = clean_for_dateparser(text)
    parsed_dt = dateparser.parse(
        cleaned_text_for_dateparser,
        languages=['es'],
        settings={
            'PREFER_DATES_FROM': 'future', # Preferir fechas futuras
            'RELATIVE_BASE': datetime.now(),
            'DATE_ORDER': 'DMY' # Día, Mes, Año
        }
    )
    if parsed_dt:
        result["datetime"] = parsed_dt
    else:
        # INTENTAR CON GEMINI si dateparser no lo encuentra
        # Usar session_data en el prompt para dar contexto a Gemini
        gemini_prompt = (
            f"Extrae la fecha y hora exactas (en formato ISO 8601:YYYY-MM-DD HH:MM) del siguiente mensaje en español. "
            f"Si el mensaje no contiene fecha/hora o no es claro, responde solo con 'NO'. "
            f"Considera el contexto de la conversación: {session_data}. " # Pasar session_data al prompt de Gemini
            f"Mensaje: '{message_text}'"
        )
        gemini_response = await call_gemini_api(gemini_prompt)
        gemini_response = gemini_response.strip().replace('"', '').replace("'", "")
        
        if gemini_response.upper() != "NO":
            try:
                # Gemini puede dar solo día, o con hora, o con T. Soportamos ambos
                if "T" in gemini_response:
                    # Si viene con 'T', lo reemplazamos por un espacio para dateparser
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
                # Log the parsing error from Gemini's response but don't re-raise
                print(f"DEBUG: Error parsing datetime from Gemini response '{gemini_response}': {e}")


    return result