import os
import logging
from datetime import datetime, timezone
from sqlalchemy.future import select
from sqlalchemy.exc import NoResultFound, MultipleResultsFound
from typing import Optional, List

from twilio.twiml.messaging_response import MessagingResponse

from db.database import get_db_session
from db.models.client import Client
from db.models.unknown_client import UnknownClient
from db.models.messages import Message
from db.models.company import Company

from apps.ai.gemini_client import get_api_response 
from apps.ai.nlp_utils import extract_contact_info, detect_intent
from apps.ai.prompts import build_prompt 
from apps.calendar.calendar_integration import create_calendar_event

logger = logging.getLogger(__name__)

async def handle_incoming_message(message_data: dict) -> str:
    user_number = message_data.get("From", "").replace("whatsapp:", "")
    bot_number = message_data.get("To", "").replace("whatsapp:", "")
    message_text = message_data.get("Body", "")

    twilio_response = MessagingResponse()
    response_text = ""

    logger.info("DEBUG HANDLER: Iniciando handle_incoming_message.")
    logger.info(f"Procesando mensaje - De: {user_number}, Para: {bot_number}, Mensaje: {message_text}")

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
                await db_session.commit() 
                return str(twilio_response)
        except Exception as e:
            logger.error(f"Error al cargar información de la compañía por número: {e}", exc_info=True)
            response_text = "Hubo un error interno al intentar obtener la información de la empresa. Por favor, intenta más tarde."
            twilio_response.message(response_text)
            await db_session.commit()
            return str(twilio_response)

        new_message = Message(
            content=message_text,
            timestamp=datetime.now(timezone.utc).replace(tzinfo=None),
            direction="in",
            sender=user_number,
            company_id=company.id
        )
        db_session.add(new_message)

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

        history_limit = 5 
        messages_history: List[Message] = []
        try:
            result = await db_session.execute(
                select(Message)
                .where(Message.sender.in_([user_number, f"whatsapp:{bot_number}"]))
                .order_by(Message.timestamp.desc())
                .limit(history_limit * 2) 
            )
            messages_history = result.scalars().all()
            messages_history.reverse() 
            
            formatted_history = []
            for msg in messages_history:
                if msg.sender == user_number:
                    formatted_history.append({"role": "user", "parts": [msg.content]})
                elif msg.sender == f"whatsapp:{bot_number}":
                    formatted_history.append({"role": "model", "parts": [msg.content]})
            logger.info(f"Historial de mensajes formateado: {formatted_history}")
            
        except Exception as e:
            logger.error(f"Error al cargar historial de mensajes: {e}", exc_info=True)
            formatted_history = []

        intent = await detect_intent(message_text)
        logger.info(f"Intención detectada: {intent}")

        entities = await extract_contact_info(message_text)
        logger.info(f"Entidades extraídas: {entities}")

        last_bot_message_content = ""
        if formatted_history:
            for item in reversed(formatted_history):
                if item["role"] == "model" and item["parts"]:
                    last_bot_message_content = item["parts"][0]
                    break
        
        # --- Lógica de Manejo de Flujo de Citas Reforzado ---
        # 1. Si el bot acaba de pedir fecha/hora O nombre/teléfono
        # 2. Y el mensaje actual del usuario contiene la información que se pidió
        # Entonces, forzamos la intención a 'schedule_appointment' y procesamos.

        # Escenario 1: Bot pidió fecha/hora y usuario la dio.
        if "Necesito la fecha y hora específicas" in last_bot_message_content and entities.get('datetime'):
            intent = "schedule_appointment"
            logger.info(f"Intención sobrescrita a 'schedule_appointment' por contexto (respuesta a fecha/hora).")
        
        # Escenario 2: Bot pidió nombre/teléfono y usuario dio el nombre/teléfono.
        # Es crucial que el bot pida ambas cosas juntas si es posible o sepa qué está esperando.
        # El mensaje del bot era "Para poder agendar tu cita... necesito tu nombre y un número de teléfono".
        # Si el usuario responde con el nombre, pero no el teléfono (o viceversa), debemos seguir pidiendo.
        
        # Guardamos los datos de la cita que se han recopilado hasta ahora en la sesión (o en un cliente si lo tienes)
        # Para este ejemplo, vamos a intentar mantenerlos a nivel de la interacción
        # Una solución más robusta implicaría persistir estos datos en el `Client` o una tabla `Session`
        
        # Si la intención es agendar, y la conversación está en curso, recopilamos los datos
        appointment_in_progress = False
        temp_appointment_datetime = None
        temp_client_name = None
        temp_client_phone = None

        # Reconstruir el estado de la cita si el historial lo sugiere
        for i in range(len(formatted_history) - 1, -1, -1): # Recorre el historial hacia atrás
            item = formatted_history[i]
            if item["role"] == "model" and "Para poder agendar tu cita" in item["parts"][0]:
                # Si el bot preguntó por nombre/teléfono, extrae lo que ya se había dicho
                # Esto es un poco rudimentario; un sistema de slots lo haría mejor.
                # Por ahora, parseamos el mensaje del bot para recuperar la fecha/hora que ya tenía
                temp_extracted_entities = await extract_contact_info(item["parts"][0])
                if temp_extracted_entities.get('datetime'):
                    temp_appointment_datetime = temp_extracted_entities.get('datetime')
                appointment_in_progress = True
                break # Encontramos la última pregunta de cita, detenemos

        # Recopilar información del mensaje actual
        if entities.get('datetime'):
            temp_appointment_datetime = entities.get('datetime')
        if entities.get('name'):
            temp_client_name = entities.get('name')
        if entities.get('phone'):
            temp_client_phone = entities.get('phone')

        # Si estamos en un flujo de agendamiento (ya sea por intención inicial o por contexto)
        if intent == "schedule_appointment" or appointment_in_progress:
            # Si tenemos fecha/hora pero nos falta nombre/teléfono
            if temp_appointment_datetime and (not temp_client_name or not temp_client_phone):
                # Si ya el bot preguntó por nombre/teléfono (con el mensaje específico)
                if "necesito tu nombre y un número de teléfono de contacto" in last_bot_message_content:
                    # Si el usuario solo dio el nombre
                    if temp_client_name and not temp_client_phone:
                        response_text = f"Gracias, {temp_client_name}. Ahora necesito tu número de teléfono de contacto para completar la reserva."
                    # Si el usuario solo dio el teléfono
                    elif temp_client_phone and not temp_client_name:
                        response_text = f"Gracias por tu número de teléfono. También necesito tu nombre completo, por favor."
                    # Si el usuario no dio ninguno o la info es insuficiente, re-pedir ambos
                    else: # Si el mensaje no contenía ni nombre ni telefono, o no se extrajeron bien
                         response_text = "Para agendar tu cita, necesito tu nombre y un número de teléfono de contacto. ¿Podrías proporcionármelos?"

                # Si el bot NO ha pedido explícitamente nombre/teléfono aún, pero ya tenemos fecha/hora
                else:
                    # En la primera vez que se tiene la fecha/hora, pedir nombre y teléfono
                    response_text = f"¡Perfecto! Ya tengo la fecha y hora: {temp_appointment_datetime.strftime('%d/%m/%Y a las %H:%M')}. Ahora necesito tu nombre y un número de teléfono de contacto para poder agendar tu cita."
                
                # Para evitar que entre en el flujo de confirmación de Gemini más abajo.
                # Y no intentamos crear el evento aún.
                intent = "schedule_appointment_pending_info" # Nuevo estado para indicar que falta info

            # Si ya tenemos toda la información (fecha/hora, nombre y teléfono)
            elif temp_appointment_datetime and temp_client_name and temp_client_phone:
                # ¡Tenemos todo para agendar!
                logger.info(f"DEBUG: Toda la información recopilada: Nombre={temp_client_name}, Teléfono={temp_client_phone}, Fecha/Hora={temp_appointment_datetime}")
                
                event_summary = f"Cita con {temp_client_name}"
                event_description = f"Cita agendada para {temp_client_name}. Contacto: {temp_client_phone}. Mensaje original: {message_text}"
                
                await create_calendar_event(
                    summary=event_summary,
                    description=event_description,
                    start_datetime=temp_appointment_datetime,
                    end_datetime=temp_appointment_datetime 
                )
                response_text = f"¡Perfecto! Tu cita ha sido programada para el {temp_appointment_datetime.strftime('%d/%m/%Y a las %H:%M')}. Te esperamos, {temp_client_name}."
                intent = "schedule_appointment_confirmed" # Estado final

            else:
                # Si llegó aquí y es 'schedule_appointment' pero no tiene fecha/hora
                # (ej. "quiero una cita" sin fecha/hora)
                response_text = "Necesito la fecha y hora específicas para programar tu cita. ¿Podrías proporcionármelas?"
                intent = "schedule_appointment_pending_info" # Mantenemos el estado de cita pendiente

        # --- Fin de Lógica de Flujo de Citas Reforzado ---

        # Si el intent no es 'schedule_appointment' o 'schedule_appointment_pending_info' o 'schedule_appointment_confirmed',
        # entonces vamos a Gemini para una respuesta general.
        # Esto previene que Gemini genere respuestas raras en medio del flujo de agendamiento.
        if intent not in ["schedule_appointment_pending_info", "schedule_appointment_confirmed"]:
            company_info_for_prompt = {
                'name': company.name,
                'industry': company.industry,
                'catalog_url': company.catalog_url,
                'schedule': company.schedule
            }
            # Se incluye el historial para Gemini
            messages_for_gemini = build_prompt(user_message=message_text, company=company_info_for_prompt, chat_history=formatted_history)
            response_text = await get_api_response(messages=messages_for_gemini)
        
        await db_session.commit()
        logger.info("Cambios en la base de datos confirmados.")

    if not isinstance(response_text, str):
        logger.error(f"La respuesta generada no es una cadena de texto: {type(response_text)} - {response_text}", exc_info=True)
        response_text = "Lo siento, ha ocurrido un error al generar mi respuesta."

    twilio_response.message(response_text)
    return str(twilio_response)