import os
import logging
import unicodedata
from datetime import datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from pytz import timezone as pytz_timezone

logger = logging.getLogger(__name__)

SCOPES = ['https://www.googleapis.com/auth/calendar.events']
SERVICE_ACCOUNT_FILE = '/app/google_service_account.json'

def get_calendar_service():
    try:
        creds = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, scopes=SCOPES
        )
        service = build('calendar', 'v3', credentials=creds)
        logger.info("Servicio de Google Calendar autenticado exitosamente.")
        return service
    except Exception as e:
        logger.error(f"Error al autenticar con Google Calendar: {e}")
        raise

def normalize_name(name):
    """Normaliza el nombre eliminando acentos y pasando a minúsculas."""
    if not name:
        return ""
    return unicodedata.normalize('NFD', name).encode('ascii', 'ignore').decode('utf-8').lower().strip()

async def is_time_slot_available(
    calendar_id: str,
    start_datetime: datetime,
    end_datetime: datetime,
    resource_name: str = None,
    allow_parallel_appointments: bool = True
) -> bool:
    """
    Chequea si hay disponibilidad en el calendario para ese rango de tiempo.
    Si se permite agendar en paralelo y se pasa resource_name, solo hay conflicto si coincide el recurso.
    Si no se permite agendar en paralelo, cualquier evento bloquea el horario.
    """
    service = get_calendar_service()
    if not service:
        logger.error("No se pudo conectar con el servicio de calendario.")
        return False

    if start_datetime.tzinfo is None:
        bogota_tz = pytz_timezone('America/Bogota')
        start_datetime = bogota_tz.localize(start_datetime)
        end_datetime = bogota_tz.localize(end_datetime)

    time_min = start_datetime.isoformat()
    time_max = end_datetime.isoformat()

    try:
        events_result = service.events().list(
            calendarId=calendar_id,
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        events = events_result.get('items', [])

        if not events:
            return True

        if allow_parallel_appointments and resource_name:
            normalized_resource = normalize_name(resource_name)
            for event in events:
                summary = normalize_name(event.get('summary', ''))
                description = normalize_name(event.get('description', ''))
                # Compara el nombre del recurso exacto en summary o description
                if normalized_resource in summary or normalized_resource in description:
                    return False
            return True
        else:
            # Si no se permiten citas en paralelo, cualquier evento bloquea el horario
            return False
    except Exception as e:
        logger.error(f"Error al comprobar disponibilidad: {e}")
        return False

async def create_calendar_event(
    summary: str, 
    description: str, 
    start_datetime: datetime, 
    end_datetime: datetime,
    company_calendar_email: str 
) -> dict:
    """
    Crea un evento en el calendario de Google utilizando la cuenta de servicio.
    NO verifica disponibilidad (esto debe hacerse antes con is_time_slot_available).

    Returns:
        dict: {'status': 'success'|'error', 'event_link': str, 'event_id': str, 'message': str}
    """
    service = get_calendar_service()
    if not service:
        return {
            "status": "error",
            "event_link": "",
            "event_id": "",
            "message": "Error: No se pudo conectar con el servicio de calendario."
        }

    if start_datetime.tzinfo is None:
        bogota_tz = pytz_timezone('America/Bogota')
        start_datetime = bogota_tz.localize(start_datetime)
        end_datetime = bogota_tz.localize(end_datetime)
        logger.info(f"DEBUG: Datetimes convertidos a {bogota_tz}: {start_datetime}, {end_datetime}")

    try:
        calendar_id = company_calendar_email
        event = {
            'summary': summary,
            'description': description,
            'start': {
                'dateTime': start_datetime.isoformat(),
                'timeZone': str(start_datetime.tzinfo),
            },
            'end': {
                'dateTime': end_datetime.isoformat(),
                'timeZone': str(end_datetime.tzinfo),
            },
        }

        event = service.events().insert(calendarId=calendar_id, body=event).execute()
        logger.info(f"Evento creado: {event.get('htmlLink')}")
        return {
            "status": "success",
            "event_link": event.get('htmlLink'),
            "event_id": event.get('id'),
            "message": "Evento creado exitosamente."
        }
    except HttpError as error:
        logger.error(f"Error HTTP al crear evento: {error}")
        return {
            "status": "error",
            "event_link": "",
            "event_id": "",
            "message": f"Error al interactuar con el calendario: {error.content.decode()}"
        }
    except Exception as e:
        logger.error(f"Error inesperado al crear evento: {e}")
        return {
            "status": "error",
            "event_link": "",
            "event_id": "",
            "message": f"Error inesperado: {e}"
        }
    
def delete_calendar_event(calendar_id: str, event_id: str) -> bool:
    """
    Elimina un evento de Google Calendar por su ID usando la cuenta de servicio.
    """
    try:
        service = get_calendar_service()
        service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
        logger.info(f"Evento eliminado correctamente: {event_id}")
        return True
    except Exception as e:
        logger.error(f"Error eliminando evento {event_id} del calendario {calendar_id}: {e}")
        return False