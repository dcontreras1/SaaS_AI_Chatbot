import os
import logging
import re
from datetime import datetime, timezone, timedelta
from sqlalchemy.future import select
from sqlalchemy.exc import NoResultFound, MultipleResultsFound
import uuid

from typing import Optional, List

from twilio.twiml.messaging_response import MessagingResponse

from db.database import get_db_session
from db.models.messages import Message
from db.models.company import Company
from db.models.appointment import Appointment 

from apps.ai.gemini_client import get_api_response
from apps.ai.nlp_utils import extract_contact_info, detect_intent
from apps.ai.prompts import build_prompt
from apps.calendar.calendar_integration import create_calendar_event

from pytz import timezone as pytz_timezone 

logger = logging.getLogger(__name__)

APPOINTMENT_CONTINUATION_INTENTS = [
    "schedule_appointment",
    "provide_contact", 
    "provide_contact_info_followup" 
]

async def handle_incoming_message(message_data: dict) -> str:
    logger.info(f"DEBUG TWILIO WEBHOOK DATA RECIBIDA: {message_data}")

    user_number = message_data.get("From", "").replace("whatsapp:", "")
    bot_number = message_data.get("To", "").replace("whatsapp:", "")
    message_text = message_data.get("Body", "")

    message_sid = message_data.get("MessageSid")
    if not message_sid:
        message_sid = str(uuid.uuid4())
        logger.warning(f"MessageSid no recibido de Twilio para mensaje de {user_number}. Generando UUID: {message_sid}")
    
    twilio_response = MessagingResponse()
    response_text = ""

    logger.info("DEBUG HANDLER: Iniciando handle_incoming_message.")
    logger.info(f"Procesando mensaje - De: {user_number}, Para: {bot_number}, Mensaje: {message_text}, SID: {message_sid}")

    async with get_db_session() as db_session:
        logger.info(f"DEBUG HANDLER: Sesión OBTENIDA (ID: {id(db_session)}, Tipo: {type(db_session)})")

        company: Optional[Company] = None
        try:
            result = await db_session.execute(
                select(Company).where(Company.company_number == f"whatsapp:{bot_number}")
            )
            company = result.scalar_one_or_none()

            if not company:
                logger.error(f"Compañía con número {bot_number} no encontrada en la base de datos.")
                response_text = "Lo siento, este número de bot no está asociado a ninguna empresa en nuestro sistema. Por favor, verifica el número."
                twilio_response.message(response_text)
                return str(twilio_response)
        except Exception as e:
            logger.error(f"Error al cargar información de la compañía por número: {e}", exc_info=True)
            response_text = "Hubo un error interno al intentar obtener la información de la empresa. Por favor, intenta más tarde."
            twilio_response.message(response_text)
            return str(twilio_response)

        try:
            new_incoming_message = Message(
                message_sid=message_sid,
                body=message_text,
                timestamp=datetime.now(timezone.utc).replace(tzinfo=None),
                direction="in",
                sender_phone_number=user_number,
                company_id=company.id
            )
            db_session.add(new_incoming_message)
            logger.info(f"Mensaje entrante de {user_number} para {company.name} registrado con SID: {message_sid}")
        except Exception as e:
            logger.error(f"ERROR: No se pudo registrar el mensaje entrante en la DB: {e}", exc_info=True)

        history_limit = 5 
        messages_history: List[Message] = []
        try:
            result = await db_session.execute(
                select(Message)
                .where(
                    Message.company_id == company.id,
                    Message.sender_phone_number.in_([user_number, f"whatsapp:{bot_number}"])
                )
                .order_by(Message.timestamp.desc())
                .limit(history_limit * 2) 
            )
            raw_history = result.scalars().all()
            raw_history.reverse()

            formatted_history = []
            user_msg_count = 0
            model_msg_count = 0
            
            for msg in raw_history:
                if msg.sender_phone_number == user_number and user_msg_count < history_limit:
                    formatted_history.append({"role": "user", "parts": [msg.body]})
                    user_msg_count += 1
                elif msg.sender_phone_number == f"whatsapp:{bot_number}" and model_msg_count < history_limit:
                    formatted_history.append({"role": "model", "parts": [msg.body]})
                    model_msg_count += 1
                
                if user_msg_count >= history_limit and model_msg_count >= history_limit:
                    break
            
            logger.info(f"Historial de mensajes formateado y limitado para empresa {company.name}: {formatted_history}")

        except Exception as e:
            logger.error(f"Error al cargar historial de mensajes para empresa {company.name}: {e}", exc_info=True)
            formatted_history = []

        current_intent = await detect_intent(message_text)
        logger.info(f"Intención detectada del mensaje actual: {current_intent}")

        current_message_entities = await extract_contact_info(message_text)
        logger.info(f"Entidades extraídas del mensaje actual: {current_message_entities}")

        last_bot_message_content = ""
        if formatted_history:
            for item in reversed(formatted_history):
                if item["role"] == "model" and item["parts"]:
                    last_bot_message_content = item["parts"][0]
                    break

        # --- GESTIÓN DE SLOTS Y FLUJO DE AGENDAMIENTO ---
        temp_appointment_datetime: Optional[datetime] = None
        temp_client_name: Optional[str] = None
        temp_client_phone: str = user_number # El número del usuario siempre es el teléfono del cliente

        # Reconstruir slots a partir del historial del USUARIO
        for item in formatted_history:
            if item["role"] == "user":
                hist_entities = await extract_contact_info(item["parts"][0])
                if hist_entities.get('datetime'):
                    temp_appointment_datetime = hist_entities.get('datetime')
                if hist_entities.get('name'):
                    temp_client_name = hist_entities.get('name')
                # if hist_entities.get('email'): # Eliminado: No se extrae el email
                #    temp_client_email = hist_entities.get('email')

        # Determinar si estamos en un flujo de agendamiento
        in_appointment_flow = False
        if current_intent in APPOINTMENT_CONTINUATION_INTENTS:
            in_appointment_flow = True
            logger.info(f"DEBUG SLOTS: Intención actual '{current_intent}' indica flujo de agendamiento.")
        elif any(keyword in last_bot_message_content.lower() for keyword in ["fecha y hora", "nombre completo"]): # Ajustada la condición
            if current_intent not in ["ask_general", "unknown"]:
                in_appointment_flow = True
                logger.info("DEBUG SLOTS: Último mensaje del bot es de agendamiento y la intención actual no es de cambio de tema.")
            else:
                logger.info("DEBUG SLOTS: Último mensaje del bot es de agendamiento, pero la intención actual es 'ask_general' o 'unknown', asumiendo cambio de tema y saliendo del flujo.")
        
        # Si NO estamos en el flujo de agendamiento, reinicializamos los slots (excepto el teléfono)
        if not in_appointment_flow:
            logger.info("DEBUG SLOTS: Bot NO en flujo de agendamiento. Reiniciando slots de agendamiento.")
            temp_appointment_datetime = None
            temp_client_name = None
            # temp_client_email = None # Eliminado

        # Sobrescribir o llenar slots con la información del mensaje *actual*
        if current_message_entities.get('datetime'):
            temp_appointment_datetime = current_message_entities.get('datetime')
        if current_message_entities.get('name'):
            temp_client_name = current_message_entities.get('name')
        # if current_message_entities.get('email'): # Eliminado
        #    temp_client_email = current_message_entities.get('email')

        logger.info(f"DEBUG SLOTS: Slots finales después de procesar historial y mensaje actual - Fecha/Hora: {temp_appointment_datetime}, Nombre: {temp_client_name}") # Log ajustado

        # Lógica principal de respuesta del bot
        if in_appointment_flow:
            if not temp_appointment_datetime:
                logger.info("DEBUG: Agendamiento - Falta fecha/hora.")
                response_text = "Para agendar tu cita, por favor, proporciona la fecha y hora en el formato **DD/MM/YY HH:MM** (ejemplo: 02/06/25 16:00)."
            elif not temp_client_name:
                logger.info("DEBUG: Agendamiento - Falta nombre.")
                response_text = "Para agendar tu cita, necesito tu nombre completo, por favor."
            else: # Todos los slots necesarios (fecha/hora y nombre) están llenos
                logger.info(f"DEBUG: Agendamiento - Toda la información recopilada: Nombre={temp_client_name}, Teléfono={temp_client_phone}, Fecha/Hora={temp_appointment_datetime}")

                # --- VERIFICACIÓN DEL CALENDARIO DE LA EMPRESA ---
                if not company.calendar_email:
                    logger.error(f"La empresa {company.name} (ID: {company.id}) no tiene configurado un 'calendar_email'. No se puede agendar la cita en Google Calendar.")
                    response_text = "Lo siento, no puedo agendar citas en este momento. La empresa no tiene un calendario de citas configurado. Por favor, intenta de nuevo más tarde o contacta directamente con el negocio."
                else:
                    event_summary = f"Cita con {temp_client_name} - {company.name}"
                    event_description = (
                        f"Cita agendada para {temp_client_name} en {company.name}.\n"
                        f"Contacto: {temp_client_phone}.\n"
                        f"Mensaje original: {message_text}" 
                    )
                    
                    appointment_end_datetime = temp_appointment_datetime + timedelta(hours=1) # Duración por defecto de 1 hora

                    try:
                        # --- LLAMADA ACTUALIZADA A create_calendar_event ---
                        calendar_response_link = await create_calendar_event(
                            summary=event_summary,
                            description=event_description,
                            start_datetime=temp_appointment_datetime,
                            end_datetime=appointment_end_datetime,
                            company_calendar_email=company.calendar_email # PASAMOS EL EMAIL DEL CALENDARIO DE LA EMPRESA
                        )
                        # --------------------------------------------------

                        if calendar_response_link and "http" in calendar_response_link:
                            bogota_tz = pytz_timezone('America/Bogota')
                            if temp_appointment_datetime.tzinfo is None:
                                temp_appointment_datetime = temp_appointment_datetime.replace(tzinfo=timezone.utc)
                            
                            local_datetime_str = temp_appointment_datetime.astimezone(bogota_tz).strftime('%d de %B a las %I:%M %p')

                            response_text = (
                                f"¡Perfecto, {temp_client_name}! Tu cita ha sido agendada para el {local_datetime_str}. "
                                f"Te esperamos."
                            )
                            logger.info(f"Cita agendada con éxito en Google Calendar. Enlace (INTERNO): {calendar_response_link}")

                            new_appointment = Appointment(
                                company_id=company.id,
                                scheduled_for=temp_appointment_datetime,
                                client_phone_number=temp_client_phone,
                                client_name=temp_client_name,
                            )
                            db_session.add(new_appointment)
                            logger.info(f"Cita guardada en DB para {temp_client_name} ({temp_client_phone}) en {company.name}. Enlace GCal: {calendar_response_link}")

                        else:
                            response_text = calendar_response_link 
                            logger.warning(f"Cita no agendada debido a: {response_text}")

                    except Exception as e:
                        logger.error(f"Error general al agendar cita o guardar en DB: {e}", exc_info=True) 
                        response_text = (
                            "Lo siento, hubo un problema al intentar agendar tu cita. "
                            "Por favor, asegúrate de que todos los datos sean correctos o ¿podrías intentar nuevamente "
                            "o contactarnos directamente?"
                        )
        
        if not response_text:
            logger.info(f"DEBUG: Consultando a Gemini. Flujo de agendamiento: {in_appointment_flow}. Response_text ya lleno: {bool(response_text)}")
            company_info_for_prompt = {
                'name': company.name,
                'industry': company.industry,
                'catalog_url': company.catalog_url,
                'schedule': company.schedule
            }
            messages_for_gemini = build_prompt(user_message=message_text, company=company_info_for_prompt, chat_history=formatted_history)
            response_text = await get_api_response(messages=messages_for_gemini)


        try:
            bot_response_message = Message(
                message_sid=f"bot-{uuid.uuid4()}",
                body=response_text,
                timestamp=datetime.now(timezone.utc).replace(tzinfo=None),
                direction="out",
                sender_phone_number=f"whatsapp:{bot_number}",
                company_id=company.id
            )
            db_session.add(bot_response_message)
            logger.info(f"Respuesta del bot '{response_text[:50]}...' para {user_number} registrada como saliente.")
        except Exception as e:
            logger.error(f"ERROR: No se pudo registrar la respuesta del bot en la DB: {e}", exc_info=True)

        try:
            await db_session.commit()
            logger.info("Cambios en la base de datos confirmados.")
        except Exception as e:
            logger.error(f"ERROR: Fallo al confirmar la transacción de la base de datos. {e}", exc_info=True)
            await db_session.rollback()
            logger.info("Transacción de la base de datos revertida debido a un error.")

    if not isinstance(response_text, str):
        logger.error(f"La respuesta generada no es una cadena de texto: {type(response_text)} - {response_text}", exc_info=True)
        response_text = "Lo siento, ha ocurrido un error interno al generar mi respuesta."

    twilio_response.message(response_text)
    return str(twilio_response)