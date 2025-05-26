import os
import json
import logging
from datetime import datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from pytz import timezone as pytz_timezone

logger = logging.getLogger(__name__)

# SCOPES necesarios para crear y gestionar eventos en el calendario
# 'https://www.googleapis.com/auth/calendar.events' para crear, editar y eliminar eventos.
# 'https://www.googleapis.com/auth/calendar' para acceso completo al calendario (incluyendo metadatos).
SCOPES = ['https://www.googleapis.com/auth/calendar.events']

# La ruta donde se montará el archivo de credenciales dentro del contenedor
SERVICE_ACCOUNT_FILE = '/app/google_service_account.json'

def get_calendar_service():
    """
    Obtiene un objeto de servicio autenticado para interactuar con Google Calendar API.
    Las credenciales se cargan desde un archivo JSON de cuenta de servicio.
    """
    try:
        creds = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, scopes=SCOPES
        )
        service = build('calendar', 'v3', credentials=creds)
        logger.info("Servicio de Google Calendar autenticado exitosamente.")
        return service
    except Exception as e:
        logger.error(f"Error al autenticar con Google Calendar: {e}")
        raise # Vuelve a levantar la excepción para que el llamador la maneje

async def create_calendar_event(summary: str, description: str, start_datetime: datetime, end_datetime: datetime) -> str:
    """
    Crea un evento en el calendario de Google utilizando la cuenta de servicio.

    Args:
        summary (str): Título del evento.
        description (str): Descripción del evento.
        start_datetime (datetime): Objeto datetime para la hora de inicio del evento.
                                   Debe ser consciente del tiempo (con zona horaria) o en UTC.
        end_datetime (datetime): Objeto datetime para la hora de finalización del evento.
                                 Debe ser consciente del tiempo (con zona horaria) o en UTC.

    Returns:
        str: Un enlace al evento creado en Google Calendar, o una cadena de error.
    """
    service = get_calendar_service()
    if not service:
        return "Error: No se pudo conectar con el servicio de calendario."

    # Asegurarse de que los datetimes sean conscientes de la zona horaria
    # Para la API de Google, es mejor UTC o una zona horaria IANA válida.
    if start_datetime.tzinfo is None:
        # Asumiendo que los datetimes se generan en UTC o necesitas una zona específica como Cali
        # Para Cali (Colombia) es America/Bogota (-05:00)
        bogota_tz = pytz_timezone('America/Bogota')
        start_datetime = bogota_tz.localize(start_datetime)
        end_datetime = bogota_tz.localize(end_datetime)
        logger.info(f"DEBUG: Datetimes convertidos a {bogota_tz}: {start_datetime}, {end_datetime}")

    event = {
        'summary': summary,
        'description': description,
        'start': {
            'dateTime': start_datetime.isoformat(),
            'timeZone': str(start_datetime.tzinfo), # Usar la zona horaria del objeto datetime
        },
        'end': {
            'dateTime': end_datetime.isoformat(),
            'timeZone': str(end_datetime.tzinfo),
        },
        # podrían añadir más datos, por ejemplo:
        # 'attendees': [{'email': 'attendee@example.com'}],
        # 'reminders': {
        #     'useDefault': False,
        #     'overrides': [
        #         {'method': 'email', 'minutes': 24 * 60},
        #         {'method': 'popup', 'minutes': 10},
        #     ],
        # },
    }

    try:
        # 'primary' se refiere al calendario principal de la cuenta de servicio.
        # Si quieres usar un calendario específico, pon su ID aquí.
        event = service.events().insert(calendarId='primary', body=event).execute()
        logger.info(f"Evento creado: {event.get('htmlLink')}")
        return event.get('htmlLink')
    except HttpError as error:
        logger.error(f"Error HTTP al crear evento: {error}")
        return f"Error al crear evento: {error.content.decode()}"
    except Exception as e:
        logger.error(f"Error inesperado al crear evento: {e}")
        return f"Error inesperado: {e}"