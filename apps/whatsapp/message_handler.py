import logging
from typing import Dict, Any, Optional
from datetime import datetime, timedelta, timezone
import uuid
import re
import json

from twilio.twiml.messaging_response import MessagingResponse
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm.attributes import flag_modified

from apps.whatsapp.chat_session_repository import get_or_create_session, update_session_data, clear_session_slots
from apps.whatsapp import message_repository
from apps.ai.response_generator import generate_response
from apps.ai.nlp_utils import detect_intent, extract_contact_info
from db.database import get_db_session
from db.models.company import Company
from db.models.appointment import Appointment

logger = logging.getLogger(__name__)

RESPONSES = {
    "greet": "¡Hola! Soy el asistente virtual de {company_name}. ¿En qué puedo ayudarte hoy?",
    "farewell": "¡Adiós! Que tengas un excelente día.",
    "ask_bot_identity": "Soy un asistente virtual, diseñado para ayudarte con tus consultas y agendar citas para {company_name}.",
    "ask_bot_capabilities": "Puedo proporcionarte información sobre nuestro horario, precios, ubicación, catálogo de servicios y agendar citas. ¿Qué necesitas?",
    "appointment_name_request": "Para agendar tu cita, necesito tu nombre completo, por favor.",
    "appointment_datetime_request": "Necesito la fecha y hora para tu cita. ¿Podrías indicarme el día y la hora, por ejemplo: 'el lunes a las 3pm' o 'el 15 de junio a las 10am'?",
    "appointment_confirmation": "¡Perfecto! Tu cita ha sido programada para el {appointment_datetime_display}. Te esperamos, {client_name}.",
    "appointment_reschedule_offer": "¿Te gustaría cambiar la fecha u hora?",
    "no_available_slots": "Lo siento, no tengo disponibilidad para esa fecha u hora. ¿Te gustaría intentar con otra?",
    "ask_contact_info": "Para poder confirmar la cita, necesito tu nombre completo y un número de teléfono de contacto, por favor.",
    "contact_info_received": "Gracias por tus datos, {client_name}. Un momento por favor...",
    "error": "Lo siento, algo salió mal al procesar tu solicitud. Por favor, inténtalo de nuevo más tarde.",
    "cancel_appointment_request": "¿Cuál es la fecha y hora de la cita que deseas cancelar? Por favor, indícala con el día y la hora.",
    "cancel_appointment_confirm": "¿Estás seguro de que quieres cancelar la cita del {appointment_datetime_display}? Responde 'Sí' para confirmar o 'No' para mantenerla.",
    "cancel_appointment_success": "Tu cita del {appointment_datetime_display} ha sido cancelada exitosamente. ¡Esperamos verte pronto!",
    "cancel_appointment_not_found": "No encontré una cita programada para esa fecha y hora. Por favor, verifica la información o contacta a nuestro soporte.",
    "cancel_appointment_aborted": "De acuerdo, tu cita no ha sido cancelada.",
    "unknown_message": "Lo siento, no entendí tu mensaje. ¿Podrías reformularlo?",
    "fallback_contact_support": "Si necesitas ayuda inmediata o tu consulta es compleja, puedes contactar a nuestro equipo de soporte al {company_phone_number}.",
    "ask_for_name": "Por favor, indícame tu nombre completo.",
    "ask_for_phone_number": "Por favor, indícame tu número de teléfono de contacto.",
    "provide_name_and_phone": "Para agendar tu cita, necesito tu nombre completo y tu número de teléfono.",
    "appointment_date_past": "La fecha u hora que has indicado ya ha pasado. Por favor, selecciona una fecha y hora futuras.",
    "invalid_datetime_format": "No pude entender la fecha y hora. Por favor, usa un formato como 'el 15 de junio a las 3pm' o 'mañana a las 10:30 de la mañana'.",
    "appointment_time_suggestion": "Podría agendar tu cita para el {date} a las {time}. ¿Te parece bien?"
}

async def handle_incoming_message(
    user_phone_number: str,
    company_whatsapp_number: str,
    message_text: str,
    message_sid: str
) -> str:
    logger.info(f"Mensaje entrante de {user_phone_number}: {message_text}")
    response_text = RESPONSES["error"] # Default error response

    async with get_db_session() as db_session:
        try:
            # 1. Obtener información de la compañía
            company_result = await db_session.execute(
                select(Company).where(Company.company_number == company_whatsapp_number)
            )
            company = company_result.scalars().first()
            if not company:
                logger.error(f"Compañía no encontrada para el número: {company_whatsapp_number}")
                return _generate_twilio_response(RESPONSES["error"])

            # 2. Obtener o crear sesión de chat
            chat_session = await get_or_create_session(
                user_phone_number=user_phone_number,
                company_id=company.id,
                db_session=db_session
            )
            logger.info(f"CHAT_SESSION_REPO: Sesión de chat activa ID: {chat_session.id}, Estado: {chat_session.status}")

            # 3. Guardar el mensaje entrante
            await message_repository.add_message(
                db_session=db_session,
                message_sid=message_sid,
                body=message_text,
                direction="in",
                sender_phone_number=user_phone_number,
                company_id=company.id,
                chat_session_id=chat_session.id
            )
            logger.info(f"MESSAGE_REPO: Mensaje entrante guardado. SID: {message_sid}")

            # Cargar historial de mensajes para el contexto del LLM
            message_history_for_gemini = await chat_session.get_formatted_message_history(db_session, limit=10)
            logger.info(f"Historial de mensajes para Gemini: {message_history_for_gemini}")

            # 4. Detectar intención
            # La intención ahora puede depender del estado de la sesión, no solo del mensaje
            current_intent = await detect_intent(message_text, chat_session.session_data)
            logger.info(f"Intención detectada: {current_intent}")

            # Inicializar session_data_to_update con la copia de los datos actuales de la sesión
            session_data_to_update = chat_session.session_data.copy()
            final_response_text = "" # Inicializar aquí para controlarla mejor

            # --- NUEVA LÓGICA DE PRIORIZACIÓN DE INTENCIONES DIRECTAS ---
            # Primero, intenta manejar las intenciones directas que no requieren interacción compleja con Gemini
            if current_intent == "greet":
                final_response_text = RESPONSES["greet"].format(company_name=company.name)
                new_conversation_state = "started"
            elif current_intent == "farewell":
                final_response_text = RESPONSES["farewell"]
                await clear_session_slots(chat_session)
                new_conversation_state = "ended"
            elif current_intent == "ask_bot_identity":
                final_response_text = RESPONSES["ask_bot_identity"].format(company_name=company.name)
                new_conversation_state = "in_progress"
            elif current_intent == "ask_bot_capabilities":
                final_response_text = RESPONSES["ask_bot_capabilities"]
                new_conversation_state = "in_progress"
            elif current_intent == "ask_schedule":
                final_response_text = f"Nuestro horario de atención es: {company.schedule or 'No especificado'}. "
                if company.catalog_url:
                    final_response_text += f"Puedes ver nuestro catálogo de servicios aquí: {company.catalog_url}"
                new_conversation_state = "in_progress"
            elif current_intent == "ask_catalog_or_price":
                if company.catalog_url:
                    final_response_text = f"Puedes ver nuestro catálogo de servicios y precios aquí: {company.catalog_url}"
                else:
                    final_response_text = "Actualmente no tenemos un catálogo en línea, pero puedes contactarnos directamente para más información sobre nuestros servicios y precios."
                new_conversation_state = "in_progress"
            elif current_intent == "ask_location":
                final_response_text = f"Estamos ubicados en: {company.address or 'No especificada'}."
                new_conversation_state = "in_progress"
            # --- FIN DE LÓGICA DE PRIORIZACIÓN ---

            # Si no se manejó por una intención directa, entonces ir a Gemini para lógica más compleja o default
            if not final_response_text: # Si final_response_text aún está vacío, Gemini debe generar la respuesta
                gemini_response_json = await generate_response(
                    user_message=message_text,
                    company=company.__dict__,
                    current_intent=current_intent,
                    session_data=chat_session.session_data,
                    chat_history_for_gemini=message_history_for_gemini
                )
                logger.info(f"Respuesta de Gemini: {gemini_response_json}")

                final_response_text = gemini_response_json.get("text", RESPONSES["error"])
                new_conversation_state = gemini_response_json.get("conversation_state", "in_progress")

                # Lógica para agendamiento basada en el estado y la intención
                # Esta lógica ahora se ejecutará *después* de que Gemini dé su respuesta,
                # para que el handler pueda "corregir" o continuar el flujo.
                # Es crucial que Gemini sepa el estado de espera para que su 'text'
                # sea coherente, pero la lógica de extracción y actualización de slots
                # la mantiene el message_handler.
                
                # Manejo de agendamiento
                if current_intent == "schedule_appointment" or new_conversation_state in ["awaiting_name", "awaiting_datetime"]:
                    extracted_info = extract_contact_info(message_text)
                    
                    if session_data_to_update.get("waiting_for_name") and extracted_info.get("name"):
                        session_data_to_update["client_name"] = extracted_info["name"]
                        session_data_to_update["waiting_for_name"] = False
                        session_data_to_update["waiting_for_datetime"] = True
                        if not "fecha y hora" in final_response_text.lower():
                            final_response_text = RESPONSES["appointment_datetime_request"]
                            new_conversation_state = "awaiting_datetime"
                        logger.info(f"Nombre del cliente capturado: {session_data_to_update['client_name']}")

                    elif session_data_to_update.get("waiting_for_datetime") and extracted_info.get("datetime"):
                        appointment_dt = extracted_info["datetime"]
                        if appointment_dt < datetime.now(timezone.utc).replace(tzinfo=None):
                            final_response_text = RESPONSES["appointment_date_past"]
                            new_conversation_state = "awaiting_datetime"
                        else:
                            session_data_to_update["appointment_datetime"] = appointment_dt.isoformat()
                            session_data_to_update["waiting_for_datetime"] = False
                            
                            if session_data_to_update.get("client_name"):
                                new_appointment = Appointment(
                                    client_phone_number=user_phone_number,
                                    client_name=session_data_to_update["client_name"],
                                    company_id=company.id,
                                    scheduled_for=appointment_dt
                                )
                                db_session.add(new_appointment)
                                await db_session.flush()

                                appointment_display = _format_datetime_for_display(appointment_dt)
                                final_response_text = RESPONSES["appointment_confirmation"].format(
                                    appointment_datetime_display=appointment_display,
                                    client_name=session_data_to_update["client_name"]
                                )
                                await clear_session_slots(chat_session, preserve_name=True)
                                new_conversation_state = "in_progress"
                                logger.info(f"Cita agendada para: {session_data_to_update['client_name']} el {appointment_display}")
                            else:
                                final_response_text = RESPONSES["appointment_name_request"]
                                session_data_to_update["waiting_for_name"] = True
                                new_conversation_state = "awaiting_name"
                                logger.warning("Falta nombre al intentar agendar cita después de fecha/hora.")
                    
                    elif current_intent == "schedule_appointment" and not (session_data_to_update.get("client_name") and session_data_to_update.get("appointment_datetime")):
                        if not session_data_to_update.get("client_name"):
                            final_response_text = RESPONSES["appointment_name_request"]
                            session_data_to_update["waiting_for_name"] = True
                            new_conversation_state = "awaiting_name"
                        elif not session_data_to_update.get("appointment_datetime"):
                            final_response_text = RESPONSES["appointment_datetime_request"]
                            session_data_to_update["waiting_for_datetime"] = True
                            new_conversation_state = "awaiting_datetime"
                        logger.info(f"Se activó flujo de agendamiento, pero faltan datos. Estado: {new_conversation_state}")

                # Manejo de cancelación
                elif current_intent == "cancel_appointment" or new_conversation_state in ["awaiting_cancel_datetime", "awaiting_cancel_confirmation"]:
                    extracted_info = extract_contact_info(message_text)

                    if session_data_to_update.get("waiting_for_cancel_datetime") and extracted_info.get("datetime"):
                        appointment_dt_to_cancel = extracted_info["datetime"]
                        session_data_to_update["appointment_datetime_to_cancel"] = appointment_dt_to_cancel.isoformat()
                        session_data_to_update["waiting_for_cancel_datetime"] = False

                        appointment_result = await db_session.execute(
                            select(Appointment)
                            .where(Appointment.client_phone_number == user_phone_number)
                            .where(Appointment.company_id == company.id)
                            .where(Appointment.scheduled_for == appointment_dt_to_cancel)
                            .where(Appointment.status == 'scheduled')
                        )
                        appointment_to_cancel = appointment_result.scalars().first()

                        if appointment_to_cancel:
                            appointment_display = _format_datetime_for_display(appointment_dt_to_cancel)
                            final_response_text = RESPONSES["cancel_appointment_confirm"].format(
                                appointment_datetime_display=appointment_display
                            )
                            session_data_to_update["confirm_cancel_id"] = appointment_to_cancel.id
                            session_data_to_update["waiting_for_cancel_confirmation"] = True
                            new_conversation_state = "awaiting_cancel_confirmation"
                            logger.info(f"Cita a cancelar encontrada. ID: {appointment_to_cancel.id}. Esperando confirmación.")
                        else:
                            final_response_text = RESPONSES["cancel_appointment_not_found"]
                            await clear_session_slots(chat_session, preserve_name=True)
                            new_conversation_state = "in_progress"
                            logger.info("Cita a cancelar no encontrada.")

                    elif session_data_to_update.get("waiting_for_cancel_confirmation"):
                        if "sí" in message_text.lower() or "si" in message_text.lower():
                            cancel_id = session_data_to_update.get("confirm_cancel_id")
                            if cancel_id:
                                appointment_to_cancel = await db_session.get(Appointment, cancel_id)
                                if appointment_to_cancel:
                                    appointment_to_cancel.status = 'cancelled'
                                    db_session.add(appointment_to_cancel)
                                    appointment_dt_to_cancel = datetime.fromisoformat(session_data_to_update["appointment_datetime_to_cancel"])
                                    appointment_display = _format_datetime_for_display(appointment_dt_to_cancel)
                                    final_response_text = RESPONSES["cancel_appointment_success"].format(
                                        appointment_datetime_display=appointment_display
                                    )
                                    logger.info(f"Cita ID {cancel_id} cancelada exitosamente.")
                                else:
                                    final_response_text = RESPONSES["cancel_appointment_not_found"]
                                    logger.warning(f"Intento de cancelar cita con ID {cancel_id} falló (no encontrada).")
                            else:
                                final_response_text = RESPONSES["error"]
                            await clear_session_slots(chat_session, preserve_name=True)
                            new_conversation_state = "in_progress"
                        elif "no" in message_text.lower():
                            final_response_text = RESPONSES["cancel_appointment_aborted"]
                            await clear_session_slots(chat_session, preserve_name=True)
                            new_conversation_state = "in_progress"
                            logger.info("Cancelación de cita abortada por el usuario.")
                        else:
                            appointment_dt_to_cancel_str = session_data_to_update.get("appointment_datetime_to_cancel")
                            if appointment_dt_to_cancel_str:
                                appointment_dt_to_cancel = datetime.fromisoformat(appointment_dt_to_cancel_str)
                                appointment_display = _format_datetime_for_display(appointment_dt_to_cancel)
                                final_response_text = RESPONSES["cancel_appointment_confirm"].format(
                                    appointment_datetime_display=appointment_display
                                )
                            else:
                                final_response_text = RESPONSES["error"]
                            new_conversation_state = "awaiting_cancel_confirmation"
                            logger.info("Esperando confirmación de cancelación (respuesta no clara).")
                    elif current_intent == "cancel_appointment" and not session_data_to_update.get("appointment_datetime_to_cancel"):
                        final_response_text = RESPONSES["cancel_appointment_request"]
                        session_data_to_update["waiting_for_cancel_datetime"] = True
                        new_conversation_state = "awaiting_cancel_datetime"
                        logger.info("Se activó flujo de cancelación, pero falta fecha/hora.")

                # Fallback general si Gemini no proporcionó una respuesta específica y no es un flujo transaccional
                elif new_conversation_state == "unknown" or (new_conversation_state == "in_progress" and final_response_text == RESPONSES["error"]):
                    final_response_text = RESPONSES["unknown_message"]
                    final_response_text += " " + RESPONSES["fallback_contact_support"].format(company_phone_number=company.company_number)


            # Actualizar el estado final de la conversación en session_data_to_update
            session_data_to_update["conversation_state"] = new_conversation_state

            # Actualizar los datos de la sesión en la base de datos
            await update_session_data(
                chat_session,
                session_data_to_update,
                db_session
            )
            logger.info(f"CHAT_SESSION_REPO: Datos de sesión actualizados. Nuevo estado: {chat_session.session_data.get('conversation_state')}")


            # 7. Guardar la respuesta del bot en el historial de mensajes
            await message_repository.add_message(
                db_session=db_session,
                message_sid=f"SM{uuid.uuid4().hex}",
                body=final_response_text,
                direction="out",
                sender_phone_number=company_whatsapp_number,
                company_id=company.id,
                chat_session_id=chat_session.id
            )
            logger.info(f"MESSAGE_REPO: Mensaje saliente guardado.")

            await db_session.commit()
            logger.info("Cambios en la base de datos confirmados.")

            logger.info(f"DEBUG FINAL: Respuesta del bot ANTES de Twilio: '{final_response_text[0:100]}...'")
            return _generate_twilio_response(final_response_text)

        except SQLAlchemyError as e:
            await db_session.rollback()
            logger.error(f"Error de base de datos en message_handler: {e}", exc_info=True)
            return _generate_twilio_response(RESPONSES["error"])
        except Exception as e:
            logger.error(f"Error general en handle_incoming_message: {e}", exc_info=True)
            return _generate_twilio_response(RESPONSES["error"])

def _generate_twilio_response(message: str) -> str:
    response = MessagingResponse()
    response.message(message)
    return str(response)

def _format_datetime_for_display(dt_obj: datetime) -> str:
    dias_semana = {
        0: "lunes", 1: "martes", 2: "miércoles", 3: "jueves",
        4: "viernes", 5: "sábado", 6: "domingo"
    }
    nombres_meses = {
        1: "enero", 2: "febrero", 3: "marzo", 4: "abril",
        5: "mayo", 6: "junio", 7: "julio", 8: "agosto",
        9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre"
    }
    dt_local = dt_obj.replace(tzinfo=None)

    dia_semana = dias_semana[dt_local.weekday()]
    dia = dt_local.day
    mes = nombres_meses[dt_local.month]
    año = dt_local.year
    hora = dt_local.strftime("%I:%M %p").lower().replace("am", "a.m.").replace("pm", "p.m.")

    return f"el {dia_semana} {dia} de {mes} de {año} a las {hora}"