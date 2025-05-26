import os
import logging
from datetime import datetime, timezone
from sqlalchemy.future import select
from sqlalchemy.exc import NoResultFound, MultipleResultsFound
from typing import Optional

from db.database import get_db_session
from db.models.client import Client
from db.models.unknown_client import UnknownClient
from db.models.messages import Message
from apps.whatsapp.whatsapp_api import send_whatsapp_message
from apps.ai.openai_client import get_api_response
from apps.ai.nlp_utils import extract_contact_info, detect_intent
from apps.ai.predict_next_steps import predict_next_steps
from apps.calendar.calendar_integration import create_calendar_event

logger = logging.getLogger(__name__)

async def handle_incoming_message(message_data: dict):
    """
    Maneja los mensajes entrantes de WhatsApp, interactúa con la IA,
    guarda el historial de mensajes y coordina acciones.
    """
    user_number = message_data.get("From", "").replace("whatsapp:", "")
    bot_number = message_data.get("To", "").replace("whatsapp:", "")
    message_text = message_data.get("Body", "")

    logger.info("DEBUG HANDLER: Iniciando handle_incoming_message sin sesión inyectada para prueba.")

    async with get_db_session() as db_session:
        logger.info(f"DEBUG HANDLER: Sesión OBTENIDA MANUALMENTE (ID: {id(db_session)}, Tipo: {type(db_session)})")
        logger.info(f"Procesando mensaje - De: {user_number}, Para: {bot_number}, Mensaje: {message_text}")

        # Guardar el mensaje entrante en la base de datos
        new_message = Message(
            content=message_text,
            timestamp=datetime.now(timezone.utc).replace(tzinfo=None),
            direction="in",
            sender=user_number,
            company_id=1 # Asumiendo un company_id fijo por ahora
        )
        db_session.add(new_message)

        # Buscar cliente existente o registrar como desconocido
        client: Optional[Client] = None
        try:
            result = await db_session.execute(select(Client).where(Client.phone_number == user_number))
            client = result.scalar_one_or_none()
        except MultipleResultsFound:
            logger.warning(f"Se encontraron múltiples clientes para el número {user_number}. Usando el primero.")
            result = await db_session.execute(select(Client).where(Client.phone_number == user_number))
            client = result.scalars().first()

        if not client:
            try:
                result = await db_session.execute(select(UnknownClient).where(UnknownClient.phone_number == user_number))
                unknown_client = result.scalar_one_or_none()
                if not unknown_client:
                    new_unknown_client = UnknownClient(phone_number=user_number, first_seen=datetime.now(timezone.utc).replace(tzinfo=None))
                    db_session.add(new_unknown_client)
                    logger.info(f"Nuevo cliente desconocido registrado: {user_number}")
                else:
                    logger.info(f"Cliente desconocido existente: {user_number}")
            except Exception as e:
                logger.error(f"Error al manejar cliente desconocido: {e}")

        # Detección de intención
        intent = await detect_intent(message_text)
        logger.info(f"Intención detectada: {intent}")

        # Extracción de entidades (ej. para programación de citas)
        entities = await extract_contact_info(message_text)
        logger.info(f"Entidades extraídas: {entities}")

        response_text = ""

        if intent == "schedule_appointment":
            # Lógica para programar cita
            try:
                appointment_datetime_str = entities.get('datetime')
                if appointment_datetime_str:
                    appointment_datetime = datetime.fromisoformat(appointment_datetime_str.replace('Z', '+00:00'))
                    appointment_datetime = appointment_datetime.replace(tzinfo=None)

                    event_summary = f"Cita con {entities.get('name', user_number)}"
                    event_description = f"Contacto: {entities.get('phone', user_number)}. Mensaje original: {message_text}"
                    calendar_event_link = await create_calendar_event(
                        summary=event_summary,
                        description=event_description,
                        start_datetime=appointment_datetime,
                        end_datetime=appointment_datetime
                    )
                    response_text = f"¡Perfecto! Hemos programado tu cita para el {appointment_datetime.strftime('%d/%m/%Y a las %H:%M')}. Aquí tienes el enlace al evento: {calendar_event_link}"
                else:
                    response_text = "Necesito más información para programar tu cita, como la fecha y hora. ¿Podrías proporcionármelas?"
            except Exception as e:
                logger.error(f"Error al programar cita: {e}")
                response_text = "Lo siento, hubo un error al intentar programar la cita. Por favor, inténtalo de nuevo más tarde."
        elif intent == "ask_general":
            response_text = await get_api_response(message_text)
        elif intent == "fallback":
            response_text = await get_api_response(message_text)
        else:
            response_text = await get_api_response(message_text)

        # Enviar la respuesta de vuelta al usuario
        if not isinstance(response_text, str):
            logger.error(f"La respuesta generada no es una cadena de texto: {type(response_text)} - {response_text}")
            response_text = "Lo siento, ha ocurrido un error al generar mi respuesta."

        await send_whatsapp_message(user_number, response_text)

        # Confirmar los cambios en la base de datos
        await db_session.commit()
        logger.info("Cambios en la base de datos confirmados.")

    return {"status": "success", "message": "Mensaje procesado"}