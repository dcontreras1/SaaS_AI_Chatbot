# apps/whatsapp/message_handler.py

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
    "appointment_datetime_request": "Necesito la fecha y hora para tu cita. ¿Podrías indicarme el día y la hora, por ejemplo: 'el lunes a las 3pm' o 'el 15 de junio a las 10:00'?",
    "appointment_phone_request": "Gracias. Ahora, por favor, necesito tu número de teléfono para confirmar la cita.",
    "appointment_confirmation": "¡Perfecto! Tu cita ha sido programada para el {appointment_datetime_display}. Te esperamos, {client_name}.",
    "appointment_reschedule_request": "Ya tienes una cita agendada para esa fecha. ¿Te gustaría cambiarla o agendar otra? Por favor, indica 'cambiar' o 'agendar otra'.",
    "appointment_unavailable": "Lo siento, la fecha y hora solicitada no está disponible o ya ha pasado. Por favor, elige otra.",
    "cancel_appointment_request": "Para cancelar tu cita, por favor, indícame la fecha y hora de la cita que deseas cancelar o su ID si lo tienes.",
    "cancel_appointment_confirmation_request": "Estás a punto de cancelar tu cita del {appointment_datetime_display}. ¿Estás seguro? Responde 'sí' para confirmar o 'no' para mantenerla.",
    "cancel_appointment_success": "Tu cita del {appointment_datetime_display} ha sido cancelada exitosamente.",
    "cancel_appointment_not_found": "No encontré una cita con esa información. Por favor, verifica la fecha, hora o el ID de la cita.",
    "cancel_appointment_flow_exit": "De acuerdo, tu cita no ha sido cancelada.",
    "ask_schedule": "Nuestro horario de atención es: {company_schedule}. ¡Te esperamos!",
    "ask_catalog": "Puedes ver nuestro catálogo de servicios aquí: {company_catalog_url}. ¡Cualquier otra duda me dices!",
    "ask_pricing": "Nuestros precios varían según el servicio. Te invito a revisar nuestro catálogo en {company_catalog_url} o a consultarme por un servicio específico.",
    "ask_general": "Estoy aquí para ayudarte con información general, agendar o cancelar citas. ¿Cómo puedo asistirte?",
    "provide_contact_info_name_missing": "Gracias por tu mensaje. Para agendar la cita, también necesito tu nombre completo.",
    "provide_contact_info_phone_missing": "Gracias, {client_name}. Ahora necesito tu número de teléfono para poder confirmar la cita.",
    "provide_contact_info_datetime_missing": "Gracias por tu información. ¿Para cuándo y a qué hora te gustaría agendar la cita?",
    "unknown": "Lo siento, no entendí tu solicitud. ¿Podrías ser más claro, por favor?",
    "error": "Lo siento, algo salió mal. Por favor, inténtalo de nuevo más tarde.",
    "good_to_go": "Todo listo. ¿Hay algo más en lo que pueda ayudarte?",
    "no_cancellable_appointments": "No tienes citas próximas que puedan ser canceladas.",
    "pending_name_and_datetime": "Necesito tu nombre y la fecha/hora de la cita. ¿Podrías proporcionarme ambos?",
    "pending_name_and_phone": "Necesito tu nombre y tu número de teléfono. ¿Podrías proporcionarme ambos?",
    "pending_datetime_and_phone": "Necesito la fecha/hora y tu número de teléfono. ¿Podrías proporcionarme ambos?",
}


async def handle_incoming_message(
    user_phone_number: str,
    company_whatsapp_number: str,
    message_text: str,
    message_sid: str,
) -> str:
    async with get_db_session() as db_session:
        try:
            logger.info(f"Mensaje entrante de {user_phone_number}: '{message_text}'")

            # 1. Obtener o crear sesión de chat
            chat_session = await get_or_create_session(
                user_phone_number, 1, db_session # Asumiendo company_id = 1 por ahora
            )
            session_data = chat_session.session_data # Cargar datos de la sesión

            logger.info(f"CHAT_SESSION_REPO: Sesión existente encontrada (ID: {chat_session.id}, Datos: {session_data})")

            # 2. Guardar el mensaje entrante
            await message_repository.add_message(
                db_session,
                message_sid,
                message_text,
                "in",
                user_phone_number,
                chat_session.company_id,
                chat_session.id,
            )

            # 3. Obtener el historial de mensajes para el LLM
            # Se pasa el session_data a generate_response para que el LLM lo use como contexto
            message_history = await message_repository.get_message_history(
                db_session, chat_session.id
            )
            logger.info(f"Historial de mensajes para Gemini: {message_history}")

            # 4. Detectar la intención del usuario
            # Pasar session_data a detect_intent puede ayudar a resolver ambigüedades
            intent = await detect_intent(message_text, session_data)
            logger.info(f"Intención detectada: {intent}")

            # 5. Lógica de manejo de flujos (citas, cancelación, etc.)
            final_response_text = RESPONSES["unknown"] # Default response

            # Manejar el flujo de agendamiento
            if session_data.get('in_appointment_flow', False):
                logger.info(f"Bot: Entrando en flujo de agendamiento. Session data inicial: {session_data}")
                contact_info = await extract_contact_info(message_text, session_data) 
                name = contact_info.get("name")
                phone = contact_info.get("phone")
                appointment_dt = contact_info.get("datetime")

                # Actualizar session_data con la información extraída
                if name:
                    session_data["client_name"] = name
                    session_data["waiting_for_name"] = False
                if phone:
                    session_data["client_phone_number"] = phone
                    session_data["waiting_for_phone"] = False
                if appointment_dt:
                    session_data["appointment_datetime"] = appointment_dt.isoformat()
                    session_data["waiting_for_datetime"] = False

                # Lógica de solicitud de información faltante
                if session_data.get("waiting_for_name"):
                    final_response_text = RESPONSES["appointment_name_request"]
                elif session_data.get("waiting_for_datetime"):
                    final_response_text = RESPONSES["appointment_datetime_request"]
                elif session_data.get("waiting_for_phone"):
                    final_response_text = RESPONSES["appointment_phone_request"]
                else:
                    # Si toda la información está completa, intentar agendar
                    client_name = session_data.get("client_name")
                    client_phone_number = session_data.get("client_phone_number")
                    # Convertir de nuevo a datetime para el calendario
                    appointment_datetime_str = session_data.get("appointment_datetime")
                    appointment_datetime_obj = datetime.fromisoformat(appointment_datetime_str) if appointment_datetime_str else None

                    if client_name and client_phone_number and appointment_datetime_obj:
                        from apps.calendar.calendar_integration import create_calendar_event
                        from apps.whatsapp.companies import get_company_by_number

                        company_obj = await get_company_by_number(company_whatsapp_number, db_session)
                        if company_obj and company_obj.calendar_email:
                            summary = f"Cita {client_name} - {company_obj.name}"
                            description = f"Cita agendada por WhatsApp para {client_name} ({client_phone_number})."
                            # Asume 1 hora de duración para la cita
                            end_datetime_obj = appointment_datetime_obj + timedelta(hours=1)

                            calendar_event_link = await create_calendar_event(
                                summary,
                                description,
                                appointment_datetime_obj,
                                end_datetime_obj,
                                company_obj.calendar_email
                            )

                            if "Error" not in calendar_event_link:
                                # Guardar la cita en la DB del bot
                                new_appointment = Appointment(
                                    client_phone_number=client_phone_number,
                                    client_name=client_name,
                                    company_id=chat_session.company_id,
                                    scheduled_for=appointment_datetime_obj,
                                    status="scheduled"
                                )
                                db_session.add(new_appointment)
                                await db_session.commit() # Confirmar la cita en la DB

                                appointment_display = _format_datetime_for_display(appointment_datetime_obj)
                                final_response_text = RESPONSES["appointment_confirmation"].format(
                                    appointment_datetime_display=appointment_display,
                                    client_name=client_name
                                ) + f" Puedes ver los detalles aquí: {calendar_event_link}"

                                await clear_session_slots(chat_session, db_session) # Limpiar el flujo
                                session_data = chat_session.session_data # Recargar session_data después de limpiar
                                logger.info("Bot: Cita agendada y sesión limpiada.")
                            else:
                                final_response_text = RESPONSES["appointment_unavailable"]
                                logger.error(f"Bot: Falló el agendamiento en Google Calendar: {calendar_event_link}")
                                # No limpiar la sesión para que el usuario pueda intentar de nuevo o corregir
                        else:
                            final_response_text = RESPONSES["error"]
                            logger.error("Bot: Correo de calendario de la empresa no configurado.")
                    else:
                        # Si llegamos aquí, la información está incompleta a pesar de los checks previos.
                        # Esto podría indicar un error en la lógica o un mensaje ambiguo.
                        # Podríamos pedir la información faltante de nuevo o una respuesta genérica.
                        if not client_name and not appointment_datetime_obj:
                            final_response_text = RESPONSES["pending_name_and_datetime"]
                        elif not client_name and not client_phone_number:
                            final_response_text = RESPONSES["pending_name_and_phone"]
                        elif not appointment_datetime_obj and not client_phone_number:
                            final_response_text = RESPONSES["pending_datetime_and_phone"]
                        elif not client_name:
                            final_response_text = RESPONSES["appointment_name_request"]
                        elif not appointment_datetime_obj:
                            final_response_text = RESPONSES["appointment_datetime_request"]
                        elif not client_phone_number:
                            final_response_text = RESPONSES["appointment_phone_request"]
                        logger.warning(f"Bot: Información de agendamiento incompleta: {session_data}")
                
                # Actualizar session_data en la DB después de cada paso en el flujo
                await update_session_data(chat_session, session_data, db_session)


            # Manejar el flujo de cancelación
            elif session_data.get('in_cancel_flow', False):
                logger.info(f"Bot: Entrando en flujo de cancelación. Session data inicial: {session_data}")
                contact_info = await extract_contact_info(message_text, session_data)
                cancel_dt = contact_info.get("datetime")
                cancel_id = contact_info.get("cancel_id")

                if cancel_dt:
                    session_data["appointment_datetime_to_cancel"] = cancel_dt.isoformat()
                    session_data["waiting_for_cancel_datetime"] = False

                if cancel_id:
                    session_data["confirm_cancel_id"] = cancel_id
                    session_data["waiting_for_cancel_datetime"] = False # Si hay ID, no esperamos fecha

                # Lógica de solicitud de confirmación o búsqueda
                if session_data.get("waiting_for_cancel_datetime", True):
                    # El usuario no ha proporcionado fecha/hora o ID aún, o lo proporcionó pero no se extrajo bien
                    if not cancel_dt and not cancel_id:
                        final_response_text = RESPONSES["cancel_appointment_request"]
                    else: # Se extrajo algo pero no es suficiente
                        final_response_text = RESPONSES["cancel_appointment_request"] # Pedir de nuevo
                elif session_data.get("waiting_for_cancel_confirmation", False):
                    # Se espera confirmación
                    text_lower = message_text.lower()
                    if "sí" in text_lower or "si" in text_lower:
                        # Proceder a cancelar
                        app_to_cancel_dt_str = session_data.get("appointment_datetime_to_cancel")
                        app_to_cancel_id = session_data.get("confirm_cancel_id")

                        # Buscar y cancelar la cita
                        appointment_query = select(Appointment).where(
                            Appointment.company_id == chat_session.company_id,
                            Appointment.client_phone_number == user_phone_number,
                            Appointment.status == 'scheduled'
                        )
                        if app_to_cancel_id:
                            appointment_query = appointment_query.where(Appointment.id == int(app_to_cancel_id))
                        elif app_to_cancel_dt_str:
                            app_to_cancel_dt_obj = datetime.fromisoformat(app_to_cancel_dt_str)
                            appointment_query = appointment_query.where(Appointment.scheduled_for == app_to_cancel_dt_obj)
                        
                        result = await db_session.execute(appointment_query)
                        appointment_to_cancel = result.scalars().first()

                        if appointment_to_cancel:
                            appointment_to_cancel.status = 'cancelled'
                            await db_session.commit()
                            display_dt = _format_datetime_for_display(appointment_to_cancel.scheduled_for)
                            final_response_text = RESPONSES["cancel_appointment_success"].format(appointment_datetime_display=display_dt)
                            await clear_session_slots(chat_session, db_session)
                            session_data = chat_session.session_data # Recargar session_data
                            logger.info("Bot: Cita cancelada y sesión limpiada.")
                        else:
                            final_response_text = RESPONSES["cancel_appointment_not_found"]
                            await clear_session_slots(chat_session, db_session)
                            session_data = chat_session.session_data # Recargar session_data
                            logger.warning("Bot: Intento de cancelación fallido, cita no encontrada.")
                    elif "no" in text_lower:
                        final_response_text = RESPONSES["cancel_appointment_flow_exit"]
                        await clear_session_slots(chat_session, db_session)
                        session_data = chat_session.session_data # Recargar session_data
                        logger.info("Bot: Flujo de cancelación abortado.")
                    else:
                        final_response_text = RESPONSES["cancel_appointment_confirmation_request"].format(
                            appointment_datetime_display=_format_datetime_for_display(datetime.fromisoformat(session_data["appointment_datetime_to_cancel"]))
                        )
                else: # Se tiene fecha/hora o ID, pero no confirmación. Pedir confirmación.
                    session_data["waiting_for_cancel_confirmation"] = True
                    # Si se tiene el datetime, se puede formar la respuesta de confirmación.
                    if session_data.get("appointment_datetime_to_cancel"):
                        display_dt = _format_datetime_for_display(datetime.fromisoformat(session_data["appointment_datetime_to_cancel"]))
                        final_response_text = RESPONSES["cancel_appointment_confirmation_request"].format(appointment_datetime_display=display_dt)
                    elif session_data.get("confirm_cancel_id"):
                        # Si solo se tiene el ID, la confirmación podría ser más genérica.
                        # Idealmente, se buscaría la cita por ID para mostrar la fecha.
                        final_response_text = RESPONSES["cancel_appointment_confirmation_request"].format(appointment_datetime_display=f"con ID {session_data['confirm_cancel_id']}")


                # Actualizar session_data en la DB después de cada paso en el flujo
                await update_session_data(chat_session, session_data, db_session)


            # Manejar intenciones que inician flujos o son respuestas directas
            else:
                if intent == "schedule_appointment":
                    # Iniciar el flujo de agendamiento
                    session_data["in_appointment_flow"] = True
                    session_data["waiting_for_name"] = True
                    session_data["waiting_for_datetime"] = True
                    session_data["waiting_for_phone"] = True # También pedir teléfono
                    session_data["conversation_state"] = "started" # Marcar el estado para el LLM
                    await update_session_data(chat_session, session_data, db_session)
                    logger.info("Bot: Iniciando flujo de agendamiento.")
                    final_response_text = RESPONSES["appointment_name_request"]
                elif intent == "cancel_appointment":
                    # Iniciar el flujo de cancelación
                    session_data["in_cancel_flow"] = True
                    session_data["waiting_for_cancel_datetime"] = True
                    session_data["conversation_state"] = "started" # Marcar el estado para el LLM
                    await update_session_data(chat_session, session_data, db_session)
                    logger.info("Bot: Iniciando flujo de cancelación.")
                    final_response_text = RESPONSES["cancel_appointment_request"]
                elif intent == "greet":
                    company = await db_session.get(Company, chat_session.company_id)
                    company_name = company.name if company else "nuestra empresa"
                    final_response_text = RESPONSES["greet"].format(company_name=company_name)
                    session_data["conversation_state"] = "started"
                    await update_session_data(chat_session, session_data, db_session)
                elif intent == "farewell":
                    final_response_text = RESPONSES["farewell"]
                    session_data["conversation_state"] = "ended" # Marcar la conversación como terminada
                    await update_session_data(chat_session, session_data, db_session)
                elif intent == "ask_schedule":
                    company = await db_session.get(Company, chat_session.company_id)
                    company_schedule = company.schedule if company and company.schedule else "no especificado"
                    final_response_text = RESPONSES["ask_schedule"].format(company_schedule=company_schedule)
                elif intent == "ask_catalog":
                    company = await db_session.get(Company, chat_session.company_id)
                    company_catalog_url = company.catalog_url if company and company.catalog_url else "no proporcionado"
                    if company_catalog_url != "no proporcionado":
                        final_response_text = RESPONSES["ask_catalog"].format(company_catalog_url=company_catalog_url)
                    else:
                        final_response_text = RESPONSES["ask_general"] # Usar una respuesta más genérica si no hay catálogo
                elif intent == "ask_pricing":
                    company = await db_session.get(Company, chat_session.company_id)
                    company_catalog_url = company.catalog_url if company and company.catalog_url else "no proporcionado"
                    final_response_text = RESPONSES["ask_pricing"].format(company_catalog_url=company_catalog_url)
                elif intent == "ask_bot_identity":
                    company = await db_session.get(Company, chat_session.company_id)
                    company_name = company.name if company else "la empresa"
                    final_response_text = RESPONSES["ask_bot_identity"].format(company_name=company_name)
                elif intent == "ask_bot_capabilities":
                    final_response_text = RESPONSES["ask_bot_capabilities"]
                elif intent == "ask_for_help":
                    final_response_text = RESPONSES["ask_general"] # Redirigir a una respuesta general de ayuda
                elif intent == "ask_general":
                    # Usar Gemini para una respuesta general si la intención es "ask_general"
                    # o si no se detectó una intención específica (unknown)
                    response_from_gemini = await generate_response(
                        user_message=message_text,
                        company={"name": "Empresa de Prueba", "schedule": "Lunes a Viernes, 9am a 6pm", "catalog_url": "No disponible"}, # Pasar info de la empresa real
                        current_intent=intent,
                        session_data=session_data
                    )
                    final_response_text = response_from_gemini.get("text", RESPONSES["unknown"])
                    # Actualizar conversation_state basado en la respuesta de Gemini si está presente
                    if "conversation_state" in response_from_gemini:
                        session_data["conversation_state"] = response_from_gemini["conversation_state"]
                        await update_session_data(chat_session, session_data, db_session)
                else: # Incluye "unknown"
                    # Usar Gemini para una respuesta general
                    response_from_gemini = await generate_response(
                        user_message=message_text,
                        company={"name": "Empresa de Prueba", "schedule": "Lunes a Viernes, 9am a 6pm", "catalog_url": "No disponible"}, # Pasar info de la empresa real
                        current_intent=intent,
                        session_data=session_data
                    )
                    final_response_text = response_from_gemini.get("text", RESPONSES["unknown"])
                    # Actualizar conversation_state basado en la respuesta de Gemini si está presente
                    if "conversation_state" in response_from_gemini:
                        session_data["conversation_state"] = response_from_gemini["conversation_state"]
                        await update_session_data(chat_session, session_data, db_session)


            # 6. Guardar la respuesta del bot
            await message_repository.add_message(
                db_session,
                str(uuid.uuid4()), # Generar un nuevo SID para el mensaje saliente
                final_response_text,
                "out",
                company_whatsapp_number,
                chat_session.company_id,
                chat_session.id,
            )
            
            # Asegurarse de guardar los cambios en la sesión si `update_session_data` no hace un commit
            # y si el estado de la sesión ha cambiado en cualquier flujo.
            # `update_session_data` ya debería manejar `flag_modified` y `db_session.add(chat_session)`.
            # El commit final del `handle_incoming_message` lo hará persistir.
            
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
    # Formatear el día de la semana y la fecha
    dia_semana_str = dias_semana.get(dt_obj.weekday())
    dia = dt_obj.day
    mes = nombres_meses.get(dt_obj.month)
    año = dt_obj.year
    hora = dt_obj.hour
    minuto = dt_obj.minute

    # Añadir un 0 delante si el minuto es menor a 10
    minuto_str = f"{minuto:02d}"

    return f"el {dia_semana_str} {dia} de {mes} de {año} a las {hora}:{minuto_str}"