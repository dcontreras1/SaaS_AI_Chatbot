import os
import json
import logging
from datetime import datetime, timedelta
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from pytz import timezone as pytz_timezone

logger = logging.getLogger(__name__)

# SCOPES necesarios para crear y gestionar eventos en el calendario
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
        raise

async def create_calendar_event(
    summary: str, 
    description: str, 
    start_datetime: datetime, 
    end_datetime: datetime,
    company_calendar_email: str 
) -> str:
    """
    Crea un evento en el calendario de Google utilizando la cuenta de servicio,
    verificando la disponibilidad primero.

    Args:
        summary (str): Título del evento.
        description (str): Descripción del evento.
        start_datetime (datetime): Objeto datetime para la hora de inicio del evento.
                                    Debe ser consciente del tiempo (con zona horaria) o en UTC.
        end_datetime (datetime): Objeto datetime para la hora de finalización del evento.
                                  Debe ser consciente del tiempo (con zona horaria) o en UTC.
        company_calendar_email (str): El correo electrónico del calendario de Google de la empresa
                                      donde se agendará la cita.

    Returns:
        str: Un enlace al evento creado en Google Calendar, o un mensaje de error si hay conflictos
             o si hubo otros problemas.
    """
    service = get_calendar_service()
    if not service:
        return "Error: No se pudo conectar con el servicio de calendario."

    # Asegurarse de que los datetimes sean conscientes de la zona horaria
    # Para la API de Google, es mejor UTC
    if start_datetime.tzinfo is None:
        bogota_tz = pytz_timezone('America/Bogota')
        start_datetime = bogota_tz.localize(start_datetime)
        end_datetime = bogota_tz.localize(end_datetime)
        logger.info(f"DEBUG: Datetimes convertidos a {bogota_tz}: {start_datetime}, {end_datetime}")

    try:
        calendar_id = company_calendar_email 

        # 1. Verificar la disponibilidad
        time_min = start_datetime.isoformat()
        time_max = end_datetime.isoformat()

        logger.info(f"Verificando disponibilidad de {time_min} a {time_max} en el calendario {calendar_id}")
        
        events_result = service.events().list(
            calendarId=calendar_id,
            timeMin=time_min,
            timeMax=time_max,
            maxResults=1,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        events = events_result.get('items', [])

        if events:
            logger.warning(f"Conflicto de horario detectado. Evento existente: {events[0].get('summary')} de {events[0]['start'].get('dateTime')} a {events[0]['end'].get('dateTime')}")
            return "Lo siento, hay un conflicto de horario con otra cita. Por favor, elige otra hora o día."

        # 2. Si no hay conflictos, crear el evento
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
            # Posibilidad de agregar asistentes o recordatorios si lo deseas
            # 'attendees': [{'email': 'attendee@example.com'}],
            # 'reminders': {
            #     'useDefault': False,
            #     'overrides': [
            #         {'method': 'email', 'minutes': 24 * 60},
            #         {'method': 'popup', 'minutes': 10},
            #     ],
            # },
        }

        event = service.events().insert(calendarId=calendar_id, body=event).execute()
        logger.info(f"Evento creado: {event.get('htmlLink')}")
        return event.get('htmlLink')
    except HttpError as error:
        logger.error(f"Error HTTP al crear evento o verificar disponibilidad: {error}")
        return f"Error al interactuar con el calendario: {error.content.decode()}"
    except Exception as e:
        logger.error(f"Error inesperado al crear evento o verificar disponibilidad: {e}")
        return f"Error inesperado: {e}"