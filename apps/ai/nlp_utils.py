import spacy
import re
import spacy.language as Language
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

# Cargar el modelo de spaCy para español
# Asegúrate de haberlo descargado con 'python -m spacy download es_core_news_sm'
try:
    nlp = spacy.load("es_core_news_sm")
except OSError:
    print("Modelo 'es_core_news_sm' no encontrado. Por favor, ejecuta: python -m spacy download es_core_news_sm")
    exit()

async def detect_intent(text: str) -> str:
    """
    Detecta la intención del mensaje del usuario.
    Se puede mejorar con un modelo de clasificación de texto más sofisticado
    o un enfoque basado en reglas más exhaustivo.
    """
    text_lower = text.lower().strip()

    # Intenciones de Agendamiento
    if any(keyword in text_lower for keyword in ["cita", "agendar", "reservar", "programar", "horario disponible"]):
        if any(keyword in text_lower for keyword in ["mi nombre es", "soy", "me llamo", "nombre"]):
            return "provide_contact_info_followup" # Es una respuesta a una pregunta de nombre dentro de un flujo
        elif any(keyword in text_lower for keyword in ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo", "hoy", "mañana", "tarde", "noche", "a las", "hora", "fecha"]):
            return "schedule_appointment" # Pide agendar con posible fecha/hora
        return "schedule_appointment"
    
    # Intenciones de Cancelación
    if any(keyword in text_lower for keyword in ["cancelar", "anular", "eliminar cita", "no puedo ir", "reprogramar"]):
        return "cancel_appointment"

    # Intenciones de Consulta de Información General (basadas en tu Company.py)
    if any(keyword in text_lower for keyword in ["horario", "abierto", "cierran"]):
        return "ask_general" # Asumiendo que "ask_general" ahora cubre horario
    if any(keyword in text_lower for keyword in ["precio", "costo", "vale", "cuánto cuesta"]):
        return "ask_price"
    if any(keyword in text_lower for keyword in ["ubicacion", "direccion", "donde estan", "lugar"]):
        return "ask_location"
    if any(keyword in text_lower for keyword in ["catalogo", "servicios", "que ofrecen"]):
        return "ask_catalog"
    
    # Intenciones de Saludo/Despedida/Identidad del bot
    if any(keyword in text_lower for keyword in ["hola", "buenas", "que tal"]):
        return "greet"
    if any(keyword in text_lower for keyword in ["adios", "chao", "hasta luego", "nos vemos"]):
        return "farewell"
    if any(keyword in text_lower for keyword in ["quien eres", "eres un bot", "que eres"]):
        return "ask_bot_identity"
    if any(keyword in text_lower for keyword in ["que puedes hacer", "tus funciones", "para que sirves"]):
        return "ask_bot_capabilities"
    
    # Intenciones de confirmación/negación (si ya estamos en un flujo)
    if text_lower in ["si", "sí", "afirmativo", "claro", "ok"]:
        return "affirm"
    if text_lower in ["no", "negativo", "para nada"]:
        return "deny"

    return "unknown"

async def extract_contact_info(text: str) -> Dict[str, Any]:
    """
    Extrae información de contacto (nombre, fecha/hora) del texto usando spaCy.
    """
    text_lower = text.lower().strip()
    doc = nlp(text)
    
    extracted_data = {
        "name": None,
        "datetime": None
    }

    # Extracción de nombres (Entidades PERSON)
    # Puede ser sensible a falsos positivos. Se puede mejorar con reglas.
    names = [ent.text for ent in doc.ents if ent.label_ == "PER"]
    if names:
        # Tomar el nombre más largo o una combinación
        extracted_data["name"] = " ".join(sorted(names, key=len, reverse=True)).title()

    # Extracción de fechas y horas (Entidades DATE y TIME)
    # spaCy es bueno para esto, pero la interpretación puede requerir lógica adicional.
    for ent in doc.ents:
        if ent.label_ == "DATE":
            # Puedes intentar parsear con dateutil.parser para más flexibilidad
            # from dateutil.parser import parse
            try:
                # Intenta interpretar la fecha. spaCy a veces da rangos o fechas relativas
                # Esto es una simplificación y puede requerir lógica más avanzada para fechas relativas
                # (ej. "mañana", "el próximo lunes")
                parsed_date = datetime.strptime(ent.text, "%d de %B de %Y") # Ejemplo de formato
                extracted_data["datetime"] = parsed_date # Podrías necesitar un procesamiento posterior para la hora
            except ValueError:
                # Si no es un formato directo, intentar con parse.
                # Ejemplo muy básico:
                if "hoy" in ent.text.lower():
                    extracted_data["datetime"] = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                elif "mañana" in ent.text.lower():
                    extracted_data["datetime"] = (datetime.now() + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
                # Implementa más lógica para "próximo lunes", etc.
                pass
        
        if ent.label_ == "TIME":
            # Buscar una hora específica. Esto es muy básico.
            # Puedes usar regex o librerías de parsing de tiempo más avanzadas.
            time_match = re.search(r'(\d{1,2}(:\d{2})?)\s*(am|pm|a\.m\.|p\.m\.)?', ent.text, re.IGNORECASE)
            if time_match:
                time_str = time_match.group(1)
                ampm = time_match.group(3)
                
                try:
                    # Parsear la hora. Si no hay am/pm, asumimos 24h.
                    if ampm:
                        parsed_time = datetime.strptime(f"{time_str} {ampm}", "%I:%M %p")
                    else:
                        parsed_time = datetime.strptime(time_str, "%H:%M")
                    
                    # Si ya tenemos una fecha, combinarlas. Si no, usar la fecha actual.
                    if extracted_data["datetime"]:
                        extracted_data["datetime"] = extracted_data["datetime"].replace(
                            hour=parsed_time.hour, minute=parsed_time.minute
                        )
                    else:
                        # Si solo hay hora, usar la fecha actual
                        extracted_data["datetime"] = datetime.now().replace(
                            hour=parsed_time.hour, minute=parsed_time.minute, second=0, microsecond=0
                        )
                except ValueError:
                    pass
        
        # Una forma más robusta de combinar DATE y TIME o encontrar DATETIME directamente
        if ent.label_ == "DATETIME": # Algunas versiones de spaCy podrían tener esta entidad
             try:
                 # Esta es una aproximación, el parsing de fechas y horas es complejo
                 parsed_dt = spacy.util.get_doc_extensions()['date_parser'](ent.text) # Si tienes una extensión personalizada
                 if parsed_dt:
                     extracted_data["datetime"] = parsed_dt
             except Exception:
                 pass
                 
    # Intentar una segunda pasada para combinar o extraer más.
    # Por ejemplo, "lunes a las 3pm" puede ser difícil para spaCy si no lo entrena.
    # Aquí puedes usar regex o dateutil.parser para frases comunes.
    if not extracted_data["datetime"]:
        # Ejemplo muy básico de regex para "lunes a las 3pm"
        match = re.search(r'(lunes|martes|miércoles|miercoles|jueves|viernes|sábado|sabado|domingo)\s*(a las|a la|el)\s*(\d{1,2}(:\d{2})?)\s*(am|pm|a\.m\.|p\.m\.)?', text_lower)
        if match:
            day_of_week_str, _, time_str, _, ampm = match.groups()
            
            # Mapear día de la semana a un número
            day_map = {"lunes":0, "martes":1, "miércoles":2, "miercoles":2, "jueves":3, "viernes":4, "sábado":5, "sabado":5, "domingo":6}
            target_weekday = day_map.get(day_of_week_str)

            if target_weekday is not None:
                today = datetime.now()
                # Calcular la fecha para el próximo día de la semana
                days_ahead = (target_weekday - today.weekday() + 7) % 7
                if days_ahead == 0 and today.time() > datetime.strptime(time_str.split(':')[0], "%H").time(): # Si es hoy pero la hora ya pasó
                    days_ahead = 7
                target_date = today + timedelta(days=days_ahead)

                try:
                    if ampm:
                        parsed_time = datetime.strptime(f"{time_str} {ampm}", "%I:%M %p")
                    else:
                        parsed_time = datetime.strptime(time_str, "%H:%M")
                    
                    extracted_data["datetime"] = target_date.replace(
                        hour=parsed_time.hour, minute=parsed_time.minute, second=0, microsecond=0
                    )
                except ValueError:
                    pass

    return extracted_data