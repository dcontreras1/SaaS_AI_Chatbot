import re
from datetime import datetime
import dateparser
from apps.ai.response_generator import call_gemini_api

async def detect_intent(message_text, session_data=None):
    """
    Detección simple de intención por palabras clave en español.
    Puedes mejorar esto usando Gemini si lo deseas.
    """
    greetings = ["hola", "buenos días", "buenas tardes", "buenas noches"]
    farewells = ["adiós", "gracias", "hasta luego", "nos vemos"]

    text = message_text.lower().strip()
    if any(g in text for g in greetings):
        return "greet"
    if any(f in text for f in farewells):
        return "farewell"
    if "agendar" in text or "cita" in text or "reservar" in text:
        return "schedule_appointment"
    if "cancelar" in text or "anular" in text or "eliminar" in text:
        return "cancel_appointment"
    if "quién eres" in text or "eres un bot" in text or "qué puedes hacer" in text:
        return "ask_bot_identity"
    return "unknown"

async def extract_contact_info(message_text):
    """
    Extracción robusta de nombre y fecha/hora usando expresiones regulares y dateparser.
    Si no se detecta nombre por patrones comunes, usa Gemini para intentar identificarlo.
    """
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

    # Si no hay nombre, intenta con Gemini si el mensaje parece solo un nombre
    if not result["name"]:
        gemini_prompt = (
            f"¿El siguiente mensaje contiene únicamente un nombre completo de una persona? "
            f"Si es así, responde solo con el nombre, si no, responde con 'NO'. Mensaje: '{message_text}'"
        )
        gemini_response = await call_gemini_api(gemini_prompt)
        gemini_response = gemini_response.strip().replace('"', '').replace("'", "")
        if gemini_response.upper() != "NO" and len(gemini_response.split()) >= 2:
            result["name"] = gemini_response

    # Buscar fecha/hora con dateparser
    parsed_dt = dateparser.parse(
        message_text,
        languages=['es'],
        settings={'PREFER_DATES_FROM': 'future', 'RELATIVE_BASE': datetime.now()}
    )
    if parsed_dt:
        result["datetime"] = parsed_dt

    return result