import re
import dateparser

def detect_intent(message: str) -> str:
    message = message.lower()
    if re.search(r"\b(horario|abren|cierran|hora)\b", message):
        return "ask_general"
    elif re.search(r"\b(cita|agendar|reservar|disponible)\b", message):
        return "schedule_appointment"
    elif re.search(r"(?i)(mi nombre es|soy)\s+\w+", message) and re.search(r"\d{10,}", message):
        return "provide_contact"
    else:
        return "unknown"

def extract_contact_info(message: str) -> dict:
    name_match = re.search(r"(?i)(?:mi nombre es|soy)\s+([A-Za-záéíóúÁÉÍÓÚñÑ]+)", message)
    phone_match = re.search(r"\b(\d{10,15})\b", message)
    datetime_match = re.search(r"(lunes|martes|miércoles|jueves|viernes|sábado|domingo).*(\d{1,2}(:\d{2})?\s*(am|pm)?)", message, re.IGNORECASE)

    name = name_match.group(1) if name_match else None
    phone = phone_match.group(1) if phone_match else None
    datetime_str = datetime_match.group(0) if datetime_match else None
    datetime_obj = dateparser.parse(datetime_str, languages=['es']) if datetime_str else None

    return {"name": name, "phone": phone, "datetime": datetime_obj}
