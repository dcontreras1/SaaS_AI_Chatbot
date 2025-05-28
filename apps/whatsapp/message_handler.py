import os
import logging
from datetime import datetime, timezone
from sqlalchemy.future import select
from sqlalchemy.exc import NoResultFound, MultipleResultsFound
from typing import Optional

from twilio.twiml.messaging_response import MessagingResponse

from db.database import get_db_session
from db.models.client import Client
from db.models.unknown_client import UnknownClient
from db.models.messages import Message
from db.models.company import Company

from apps.ai.gemini_client import get_api_response 
from apps.ai.nlp_utils import extract_contact_info, detect_intent
from apps.ai.predict_next_steps import predict_next_steps
from apps.ai.prompts import build_prompt 
from apps.calendar.calendar_integration import create_calendar_event

logger = logging.getLogger(__name__)

async def handle_incoming_message(message_data: dict) -> str:
    """
    Maneja los mensajes entrantes de WhatsApp, interactúa con la IA,
    guarda el historial de mensajes y coordina acciones.
    """
    user_number = message_data.get("From", "").replace("whatsapp:", "")
    bot_number = message_data.get("To", "").replace("whatsapp:", "")
    message_text = message_data.get("Body", "")

    # Inicia la respuesta TwilioML
    twilio_response = MessagingResponse()
    response_text = "" # Inicializa la respuesta que enviará el bot

    logger.info("DEBUG HANDLER: Iniciando handle_incoming_message.")
    logger.info(f"Procesando mensaje - De: {user_number}, Para: {bot_number}, Mensaje: {message_text}")

    async with get_db_session() as db_session:
        logger.info(f"DEBUG HANDLER: Sesión OBTENIDA (ID: {id(db_session)}, Tipo: {type(db_session)})")
        
        # Obtener información de la compañía basada en el número del bot
        company: Optional[Company] = None
        try:
            result = await db_session.execute(
            select(Company).where(Company.company_number == f"whatsapp:{bot_number}")
            )
            
            company = result.scalar_one_or_none()
            
            if not company:
                logger.error(f"Compañía con número {bot_number} no encontrada en la base de datos. Asegúrate de que el número de Twilio configurado para recibir mensajes sea el mismo que el 'company_number' en tu DB.")
                response_text = "Lo siento, este número de bot no está asociado a ninguna empresa en nuestro sistema. Por favor, verifica el número."
                twilio_response.message(response_text)
                await db_session.commit() # Confirma el posible registro de UnknownClient si se hizo antes
                return str(twilio_response)
        except Exception as e:
            logger.error(f"Error al cargar información de la compañía por número: {e}", exc_info=True)
            response_text = "Hubo un error interno al intentar obtener la información de la empresa. Por favor, intenta más tarde."
            twilio_response.message(response_text)
            await db_session.commit() # Confirma el posible registro de UnknownClient si se hizo antes
            return str(twilio_response)
        # FIN: Obtener información de la compañía

        # Guardar el mensaje entrante en la base de datos
        new_message = Message(
            content=message_text,
            timestamp=datetime.now(timezone.utc).replace(tzinfo=None),
            direction="in",
            sender=user_number,
            company_id=company.id
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
                logger.error(f"Error al manejar cliente desconocido: {e}", exc_info=True)

        # Detección de intención
        intent = await detect_intent(message_text)
        logger.info(f"Intención detectada: {intent}")

        # Extracción de entidades
        entities = await extract_contact_info(message_text)
        logger.info(f"Entidades extraídas: {entities}")

        # Lógica de respuesta basada en la intención
        if intent == "schedule_appointment":
            # Lógica para programar cita
            try:
                appointment_datetime = entities.get('datetime') 
                if appointment_datetime:
                    if appointment_datetime.tzinfo is not None:
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
                logger.error(f"Error al programar cita: {e}", exc_info=True)
                response_text = "Lo siento, hubo un error al intentar programar la cita. Por favor, inténtalo de nuevo más tarde."
        elif intent in ["ask_general", "unknown", "fallback", "provide_contact"]:
            # diccionario de información de la compañía usando el objeto 'company' cargado
            company_info_for_prompt = {
                'name': company.name,
                'industry': company.industry,
                'catalog_url': company.catalog_url,
                'schedule': company.schedule
            }
            
            # Construir el prompt para la API de Gemini con la información REAL de la empresa
            messages_for_gemini = build_prompt(user_message=message_text, company=company_info_for_prompt)
            
            # Llamar a get_api_response con la lista de mensajes
            response_text = await get_api_response(messages=messages_for_gemini)
        
        # Confirmar los cambios en la base de datos
        await db_session.commit()
        logger.info("Cambios en la base de datos confirmados.")

    # Generar el TwilioML para enviar la respuesta
    if not isinstance(response_text, str):
        logger.error(f"La respuesta generada no es una cadena de texto: {type(response_text)} - {response_text}", exc_info=True)
        response_text = "Lo siento, ha ocurrido un error al generar mi respuesta."

    twilio_response.message(response_text)
    return str(twilio_response) # Retorna el XML como una cadena