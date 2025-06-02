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
    "appointment_datetime_request": "Necesito la fecha y hora para tu cita. ¿Podrías indicarme el día y la hora, por ejemplo: 'el lunes a las 3pm' o 'el 15 de junio a las 10 de la mañana'?",
    "appointment_scheduled": "¡Excelente! Tu cita ha sido agendada con éxito para el {datetime} a nombre de {name}. Recibirás una confirmación en breve.",
    "appointment_reschedule_cancel": "Para reagendar o cancelar una cita, por favor, responde con 'reagendar cita' o 'cancelar cita' y el bot te guiará.",
    "cancel_request": "Entendido. ¿Qué cita te gustaría cancelar? Por favor, dime la fecha y hora.",
    "cancel_confirm": "¿Estás seguro de que quieres cancelar la cita del {datetime} a nombre de {name}? Responde 'Sí' para confirmar o 'No' para mantenerla.",
    "cancel_success": "¡Tu cita del {datetime} a nombre de {name} ha sido cancelada con éxito! Esperamos verte pronto.",
    "cancel_not_found": "Lo siento, no encontré ninguna cita para cancelar con la información que me diste. ¿Podrías darme más detalles (fecha y hora, o tu nombre completo si es diferente al registrado)?",
    "cancel_aborted": "De acuerdo, no se ha cancelado ninguna cita. ¿Hay algo más en lo que pueda ayudarte?",
    "cancel_invalid_confirmation": "Por favor, responde 'Sí' o 'No' para confirmar la cancelación.",
    "unknown": "Lo siento, no entendí tu solicitud. ¿Podrías reformularla, por favor?",
    "error": "Lo siento, ha ocurrido un error interno muy grave y no puedo procesar tu solicitud en este momento. Por favor, inténtalo de nuevo más tarde.",
}

async def handle_incoming_message(
    user_phone_number: str,
    company_whatsapp_number: str,
    message_text: str,
    message_sid: Optional[str] = None
) -> str:
    logger.info(f"Procesando mensaje - De: {user_phone_number}, Para: {company_whatsapp_number}, Mensaje: '{message_text}', SID: {message_sid}")

    async with get_db_session() as db_session:
        try:
            company_phone_in_db = "whatsapp:" + company_whatsapp_number
            result = await db_session.execute(
                select(Company).where(Company.company_number == company_phone_in_db)
            )
            company = result.scalar_one_or_none()

            if not company:
                logger.error(f"Compañía no encontrada para el número de WhatsApp: {company_phone_in_db}")
                return _generate_twilio_response(RESPONSES["error"])

            chat_session = await get_or_create_session(user_phone_number, company.id, db_session)
            session_data = chat_session.session_data if chat_session.session_data is not None else {}
            logger.info(f"DEBUG HANDLER: Sesión de chat persistente cargada (ID: {chat_session.id}). Datos: {session_data}")

            await message_repository.add_message(
                db_session=db_session,
                message_sid=message_sid,
                body=message_text,
                direction="in",
                sender_phone_number=user_phone_number,
                company_id=company.id,
                chat_session_id=chat_session.id
            )

            current_message_entities = await extract_contact_info(message_text)
            extracted_name_nlp = current_message_entities.get('name')
            extracted_datetime_nlp = current_message_entities.get('datetime')

            logger.info(f"DEBUG HANDLER: Entidades extraídas con NLP_UTILS: Nombre={extracted_name_nlp}, Fecha/Hora={extracted_datetime_nlp}")

            if extracted_name_nlp:
                session_data['client_name'] = extracted_name_nlp
                session_data['waiting_for_name'] = False
                logger.info(f"DEBUG SLOTS: Nombre '{extracted_name_nlp}' extraído por NLP y guardado en sesión.")

            if extracted_datetime_nlp:
                if session_data.get('in_cancel_flow'):
                    session_data['appointment_datetime_to_cancel'] = extracted_datetime_nlp.isoformat()
                    session_data['waiting_for_cancel_datetime'] = False
                    logger.info(f"DEBUG SLOTS: Fecha/Hora '{extracted_datetime_nlp}' para CANCELACIÓN extraída por NLP.")
                else:
                    session_data['appointment_datetime'] = extracted_datetime_nlp.isoformat()
                    session_data['waiting_for_datetime'] = False
                    logger.info(f"DEBUG SLOTS: Fecha/Hora '{extracted_datetime_nlp}' para AGENDAMIENTO extraída por NLP.")

            # Detectar intención al principio y priorizar ask_schedule
            intent = await detect_intent(message_text)
            logger.info(f"DEBUG HANDLER: Intención detectada del mensaje actual: {intent}")

            final_response_text = ""

            # PRIORIDAD 0: Horario de atención (rompe cualquier flujo anterior)
            if intent == "ask_schedule":
                # Limpiar flags de cita/cancelación
                session_data['in_appointment_flow'] = False
                session_data['waiting_for_name'] = False
                session_data['waiting_for_datetime'] = False
                session_data['in_cancel_flow'] = False
                session_data['waiting_for_cancel_datetime'] = False
                session_data['waiting_for_cancel_confirmation'] = False
                session_data['confirm_cancel_id'] = None
                session_data['appointment_datetime_to_cancel'] = None
                # Responder con el horario
                horario = getattr(company, "schedule", "lunes a viernes de 8am a 6pm")
                final_response_text = f"Nuestro horario de atención es: {horario}. ¿En qué más puedo ayudarte?"
                await update_session_data(chat_session, session_data, db_session)
                await db_session.commit()
                await message_repository.add_message(
                    db_session=db_session,
                    message_sid=f"bot-{uuid.uuid4()}",
                    body=final_response_text,
                    direction="out",
                    sender_phone_number=company_whatsapp_number,
                    company_id=company.id,
                    chat_session_id=chat_session.id
                )
                await db_session.commit()
                logger.info(f"DEBUG FINAL: Respuesta del bot ANTES de Twilio: '{final_response_text[0:100]}...'")
                return _generate_twilio_response(final_response_text)

            # PRIORIDAD 1: Flujo de Cancelación
            if intent == "cancel_appointment" or session_data.get('in_cancel_flow', False):
                session_data['in_cancel_flow'] = True
                session_data['in_appointment_flow'] = False

                if session_data.get('waiting_for_cancel_datetime', True) and not session_data.get('appointment_datetime_to_cancel'):
                    final_response_text = RESPONSES["cancel_request"]
                    session_data['waiting_for_cancel_datetime'] = True
                    logger.info("DEBUG CANCEL: Pidiendo fecha/hora para cancelar.")

                elif session_data.get('appointment_datetime_to_cancel') and not session_data.get('waiting_for_cancel_confirmation'):
                    cancel_datetime_obj = datetime.fromisoformat(session_data['appointment_datetime_to_cancel'])
                    result = await db_session.execute(
                        select(Appointment).where(
                            Appointment.client_phone_number == user_phone_number,
                            Appointment.scheduled_for == cancel_datetime_obj,
                            Appointment.company_id == company.id,
                            Appointment.status == 'scheduled'
                        )
                    )
                    appointment_to_cancel = result.scalar_one_or_none()

                    if appointment_to_cancel:
                        session_data['confirm_cancel_id'] = appointment_to_cancel.id
                        final_response_text = RESPONSES["cancel_confirm"].format(
                            name=appointment_to_cancel.client_name,
                            datetime=_format_datetime_for_display(cancel_datetime_obj)
                        )
                        session_data['waiting_for_cancel_confirmation'] = True
                        logger.info(f"DEBUG CANCEL: Cita encontrada. Pidiendo confirmación para ID: {appointment_to_cancel.id}")
                    else:
                        final_response_text = RESPONSES["cancel_not_found"]
                        session_data['appointment_datetime_to_cancel'] = None
                        session_data['confirm_cancel_id'] = None
                        await clear_session_slots(chat_session, db_session, preserve_name=True)
                        session_data = chat_session.session_data
                        logger.info("DEBUG CANCEL: No se encontró la cita con los datos proporcionados.")

                elif session_data.get('waiting_for_cancel_confirmation'):
                    message_text_lower = message_text.lower().strip()
                    if message_text_lower == "sí" or message_text_lower == "si":
                        appointment_id = session_data.get('confirm_cancel_id')
                        if appointment_id:
                            try:
                                appointment_to_cancel = await db_session.get(Appointment, appointment_id)
                                if appointment_to_cancel:
                                    appointment_to_cancel.status = 'canceled'
                                    db_session.add(appointment_to_cancel)
                                    final_response_text = RESPONSES["cancel_success"].format(
                                        name=appointment_to_cancel.client_name,
                                        datetime=_format_datetime_for_display(appointment_to_cancel.scheduled_for)
                                    )
                                    await clear_session_slots(chat_session, db_session)
                                    session_data = chat_session.session_data
                                    logger.info(f"DEBUG CANCEL: Cita {appointment_id} cancelada exitosamente.")
                                else:
                                    final_response_text = RESPONSES["cancel_not_found"]
                                    await clear_session_slots(chat_session, db_session)
                                    session_data = chat_session.session_data
                                    logger.info("DEBUG CANCEL: Cita no encontrada por ID durante confirmación.")
                            except Exception as e:
                                logger.error(f"Error al cancelar cita por confirmación: {e}", exc_info=True)
                                final_response_text = RESPONSES["error"]
                                await clear_session_slots(chat_session, db_session)
                                session_data = chat_session.session_data
                        else:
                            final_response_text = RESPONSES["cancel_not_found"]
                            await clear_session_slots(chat_session, db_session)
                            session_data = chat_session.session_data

                    elif message_text_lower == "no":
                        final_response_text = RESPONSES["cancel_aborted"]
                        await clear_session_slots(chat_session, db_session)
                        session_data = chat_session.session_data
                        logger.info("DEBUG CANCEL: Cancelación abortada por el usuario.")
                    else:
                        final_response_text = RESPONSES["cancel_invalid_confirmation"]
                        logger.info("DEBUG CANCEL: Respuesta de confirmación inválida para cancelación.")

                else:
                    final_response_text = RESPONSES["cancel_request"]
                    session_data['waiting_for_cancel_datetime'] = True
                    logger.info("DEBUG CANCEL: En flujo de cancelación, estado ambiguo. Volviendo a pedir fecha.")

            # PRIORIDAD 2: Flujo de Agendamiento Mejorado
            elif intent == "schedule_appointment" or session_data.get('in_appointment_flow', False):
                session_data['in_appointment_flow'] = True
                session_data['in_cancel_flow'] = False

                # --- NUEVA LÓGICA: Si ya tienes ambos datos, agenda directamente
                if session_data.get('client_name') and session_data.get('appointment_datetime'):
                    try:
                        app_datetime_obj = datetime.fromisoformat(session_data['appointment_datetime'])
                        new_appointment = Appointment(
                            client_phone_number=user_phone_number,
                            client_name=session_data['client_name'],
                            scheduled_for=app_datetime_obj,
                            company_id=company.id,
                            status='scheduled'
                        )
                        db_session.add(new_appointment)
                        final_response_text = RESPONSES["appointment_scheduled"].format(
                            name=session_data['client_name'],
                            datetime=_format_datetime_for_display(app_datetime_obj)
                        )
                        await clear_session_slots(chat_session, db_session)
                        session_data = chat_session.session_data
                        logger.info("DEBUG SLOTS: Cita agendada exitosamente y slots limpiados.")
                    except Exception as e:
                        logger.error(f"Error al agendar cita: {e}", exc_info=True)
                        final_response_text = RESPONSES["error"]
                        await clear_session_slots(chat_session, db_session)
                        session_data = chat_session.session_data

                # --- Si falta el nombre, pídelo
                elif not session_data.get('client_name'):
                    final_response_text = RESPONSES["appointment_name_request"]
                    session_data['waiting_for_name'] = True
                    logger.info("DEBUG SLOTS: Agendamiento - Falta nombre. Volviendo a preguntar.")

                # --- Si falta la fecha, pídela
                elif not session_data.get('appointment_datetime'):
                    final_response_text = RESPONSES["appointment_datetime_request"]
                    session_data['waiting_for_datetime'] = True
                    logger.info("DEBUG SLOTS: Agendamiento - Falta fecha/hora. Volviendo a preguntar.")

            # PRIORIDAD 3: Flujo General (ni agendamiento ni cancelación)
            else:
                logger.info("DEBUG: Consultando a Gemini (flujo general).")
                llm_response = await generate_response(
                    user_message=message_text,
                    company={
                        "name": company.name,
                        "schedule": company.schedule,
                        "catalog_url": company.catalog_url,
                        "calendar_email": company.calendar_email
                    },
                    current_intent=intent,
                    session_data=session_data
                )
                conversation_state = "in_progress"
                if isinstance(llm_response, str):
                    try:
                        response_obj = json.loads(llm_response)
                        final_response_text = response_obj.get("text", "")
                        conversation_state = response_obj.get("conversation_state", "in_progress")
                    except Exception:
                        final_response_text = llm_response
                        conversation_state = "in_progress"
                elif isinstance(llm_response, dict):
                    final_response_text = llm_response.get("text", "")
                    conversation_state = llm_response.get("conversation_state", "in_progress")
                else:
                    final_response_text = str(llm_response)
                    conversation_state = "in_progress"
                if not final_response_text:
                    final_response_text = RESPONSES["unknown"]

                # Actualización de flags según Gemini
                if conversation_state == "started":
                    session_data['conversation_started'] = True
                    session_data['conversation_ended'] = False
                elif conversation_state == "ended":
                    session_data['conversation_ended'] = True
                    session_data['in_appointment_flow'] = False
                    session_data['in_cancel_flow'] = False
                else:
                    session_data['conversation_started'] = True
                    session_data['conversation_ended'] = False

            await update_session_data(chat_session, session_data, db_session)
            await db_session.commit()
            logger.info("DEBUG SLOTS: Estado de sesión guardado. Datos: %s", chat_session.session_data)

            await message_repository.add_message(
                db_session=db_session,
                message_sid=f"bot-{uuid.uuid4()}",
                body=final_response_text,
                direction="out",
                sender_phone_number=company_whatsapp_number,
                company_id=company.id,
                chat_session_id=chat_session.id
            )
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
    dia_semana_str = dias_semana[dt_obj.weekday()]
    mes_str = nombres_meses[dt_obj.month]
    hora_str = dt_obj.strftime("%I:%M %p").replace("AM", "a.m.").replace("PM", "p.m.").lower()
    return f"{dia_semana_str}, {dt_obj.day} de {mes_str} a las {hora_str}"