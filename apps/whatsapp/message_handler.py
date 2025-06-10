import logging
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
import uuid

from twilio.twiml.messaging_response import MessagingResponse
from sqlalchemy.future import select
from sqlalchemy.exc import SQLAlchemyError

from apps.whatsapp.chat_session_repository import get_or_create_session, update_session_data, clear_session_slots
from apps.whatsapp import message_repository
from apps.ai.response_generator import generate_response
from apps.ai.nlp_utils import detect_intent, extract_info
from db.database import get_db_session
from db.models.company import Company
from db.models.appointment import Appointment
from db.models.companies import get_company_by_number

logger = logging.getLogger(__name__)

RESPONSES = {
    "unknown": "Lo siento, no entendí tu solicitud. ¿Podrías ser más claro, por favor?",
    "error": "Lo siento, algo salió mal. Por favor, inténtalo de nuevo más tarde.",
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

            # Obtener datos de la empresa por el número de WhatsApp
            company_obj = await get_company_by_number(company_whatsapp_number, db_session)
            if company_obj:
                company_data = {
                    "name": company_obj.name,
                    "schedule": company_obj.schedule,
                    "catalog_url": company_obj.catalog_url,
                }
                company_id = company_obj.id
            else:
                company_data = {"name": "nuestra empresa", "schedule": "", "catalog_url": ""}
                company_id = 1  # fallback

            # 1. Obtener o crear sesión de chat
            chat_session = await get_or_create_session(
                user_phone_number, company_id, db_session
            )
            session_data = chat_session.session_data

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

            # 3. Obtener el historial de mensajes para el LLM (si lo quieres usar como contexto)
            message_history = await message_repository.get_message_history(
                db_session, chat_session.id
            )
            logger.info(f"Historial de mensajes para Gemini: {message_history}")

            # 4. Detectar la intención del usuario usando Gemini
            intent = await detect_intent(message_text, session_data)
            logger.info(f"Intención detectada: {intent}")

            final_response_text = RESPONSES["unknown"]

            # --- RESPUESTA DIRECTA: Horario de la Empresa ---
            if intent in ["consultar_horario", "schedule_info", "company_schedule", "horario_empresa"]:
                if company_obj and company_obj.schedule:
                    final_response_text = f"El horario de atención de {company_obj.name} es: {company_obj.schedule}"
                else:
                    final_response_text = "Lo siento, no tengo registrado el horario de la empresa en este momento."
                # Guardar respuesta y devolver
                await message_repository.add_message(
                    db_session,
                    str(uuid.uuid4()),
                    final_response_text,
                    "out",
                    company_whatsapp_number,
                    chat_session.company_id,
                    chat_session.id,
                )
                await db_session.commit()
                return _generate_twilio_response(final_response_text)
            # --- FLUJO DE AGENDAMIENTO ---
            if session_data.get('in_appointment_flow', False):
                logger.info(f"Bot: Entrando en flujo de agendamiento. Session data inicial: {session_data}")
                contact_info = await extract_info(message_text, session_data, user_phone=user_phone_number)
                name = contact_info.get("name")
                phone = contact_info.get("phone")
                appointment_dt = contact_info.get("datetime")

                if name:
                    session_data["client_name"] = name
                    session_data["waiting_for_name"] = False
                if phone:
                    session_data["client_phone_number"] = phone
                    session_data["waiting_for_phone"] = False
                if appointment_dt:
                    session_data["appointment_datetime"] = appointment_dt.isoformat()
                    session_data["waiting_for_datetime"] = False

                missing_slots = []
                if session_data.get("waiting_for_name"):
                    missing_slots.append("name")
                if session_data.get("waiting_for_datetime"):
                    missing_slots.append("datetime")
                if session_data.get("waiting_for_phone"):
                    missing_slots.append("phone")

                if missing_slots:
                    response_from_gemini = await generate_response(
                        user_message=message_text,
                        company=company_data,
                        current_intent=intent,
                        session_id=chat_session.id,
                        session_data=session_data,
                    )
                    final_response_text = response_from_gemini.get("text", RESPONSES["unknown"])
                else:
                    client_name = session_data.get("client_name")
                    client_phone_number = session_data.get("client_phone_number")
                    appointment_datetime_str = session_data.get("appointment_datetime")
                    appointment_datetime_obj = datetime.fromisoformat(appointment_datetime_str) if appointment_datetime_str else None
                    if client_name and client_phone_number and appointment_datetime_obj:
                        from apps.calendar.calendar_integration import create_calendar_event
                        summary = f"Cita {client_name} - {company_obj.name}"
                        description = f"Cita agendada por WhatsApp para {client_name} ({client_phone_number})."
                        end_datetime_obj = appointment_datetime_obj + timedelta(hours=1)
                        calendar_event_link = await create_calendar_event(
                            summary,
                            description,
                            appointment_datetime_obj,
                            end_datetime_obj,
                            company_obj.calendar_email
                        )
                        if "Error" not in calendar_event_link:
                            new_appointment = Appointment(
                                client_phone_number=client_phone_number,
                                client_name=client_name,
                                company_id=chat_session.company_id,
                                scheduled_for=appointment_datetime_obj,
                                status="scheduled"
                            )
                            db_session.add(new_appointment)
                            await db_session.commit()
                            appointment_display = _format_datetime_for_display(appointment_datetime_obj)
                            response_from_gemini = await generate_response(
                                user_message=message_text,
                                company=company_data,
                                current_intent="appointment_confirmation",
                                session_id=chat_session.id,
                                session_data=session_data,
                                extra_context={
                                    "appointment_datetime_display": appointment_display,
                                    "client_name": client_name,
                                    "calendar_event_link": calendar_event_link,
                                }
                            )
                            final_response_text = response_from_gemini.get(
                                "text",
                                f"¡Perfecto! Tu cita ha sido programada para el {appointment_display}. Puedes ver los detalles aquí: {calendar_event_link}"
                            )
                            await clear_session_slots(chat_session, db_session)
                            session_data = chat_session.session_data
                        else:
                            final_response_text = RESPONSES["error"]
                            logger.error(f"Bot: Falló el agendamiento en Google Calendar: {calendar_event_link}")
                    else:
                        response_from_gemini = await generate_response(
                            user_message=message_text,
                            company=company_data,
                            current_intent="pending_info",
                            session_id=chat_session.id,
                            session_data=session_data,
                        )
                        final_response_text = response_from_gemini.get("text", RESPONSES["unknown"])
                await update_session_data(chat_session, session_data, db_session)

            # --- FLUJO DE CANCELACIÓN ---
            elif session_data.get('in_cancel_flow', False):
                logger.info(f"Bot: Entrando en flujo de cancelación. Session data inicial: {session_data}")
                contact_info = await extract_info(message_text, session_data, user_phone=user_phone_number)
                cancel_dt = contact_info.get("datetime")
                cancel_id = contact_info.get("cancel_id")

                if cancel_dt:
                    session_data["appointment_datetime_to_cancel"] = cancel_dt.isoformat()
                    session_data["waiting_for_cancel_datetime"] = False
                if cancel_id:
                    session_data["confirm_cancel_id"] = cancel_id
                    session_data["waiting_for_cancel_datetime"] = False

                need_confirm = session_data.get("waiting_for_cancel_confirmation", False)
                if not need_confirm and not session_data.get("waiting_for_cancel_datetime", True):
                    response_from_gemini = await generate_response(
                        user_message=message_text,
                        company=company_data,
                        current_intent="cancel_appointment_confirmation_request",
                        session_id=chat_session.id,
                        session_data=session_data,
                        extra_context={
                            "appointment_datetime_display": session_data.get("appointment_datetime_to_cancel"),
                            "cancel_id": session_data.get("confirm_cancel_id"),
                        }
                    )
                    final_response_text = response_from_gemini.get("text", "¿Estás seguro de cancelar la cita?")
                    session_data["waiting_for_cancel_confirmation"] = True
                elif need_confirm:
                    text_lower = message_text.lower()
                    if "sí" in text_lower or "si" in text_lower:
                        app_to_cancel_dt_str = session_data.get("appointment_datetime_to_cancel")
                        app_to_cancel_id = session_data.get("confirm_cancel_id")
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
                            response_from_gemini = await generate_response(
                                user_message=message_text,
                                company=company_data,
                                current_intent="cancel_appointment_success",
                                session_id=chat_session.id,
                                session_data=session_data,
                                extra_context={"appointment_datetime_display": display_dt}
                            )
                            final_response_text = response_from_gemini.get("text", f"Tu cita del {display_dt} ha sido cancelada exitosamente.")
                            await clear_session_slots(chat_session, db_session)
                            session_data = chat_session.session_data
                            logger.info("Bot: Cita cancelada y sesión limpiada.")
                        else:
                            final_response_text = "No encontré una cita con esa información. Por favor, verifica la fecha, hora o el ID de la cita."
                            await clear_session_slots(chat_session, db_session)
                            session_data = chat_session.session_data
                            logger.warning("Bot: Intento de cancelación fallido, cita no encontrada.")
                    elif "no" in text_lower:
                        final_response_text = "De acuerdo, tu cita no ha sido cancelada."
                        await clear_session_slots(chat_session, db_session)
                        session_data = chat_session.session_data
                        logger.info("Bot: Flujo de cancelación abortado.")
                    else:
                        final_response_text = "Por favor, responde 'sí' para confirmar o 'no' para mantener la cita."
                else:
                    response_from_gemini = await generate_response(
                        user_message=message_text,
                        company=company_data,
                        current_intent="cancel_appointment_request",
                        session_id=chat_session.id,
                        session_data=session_data,
                    )
                    final_response_text = response_from_gemini.get("text", "¿Cuál cita deseas cancelar? Por favor, indica la fecha y hora o el ID de la cita.")

                await update_session_data(chat_session, session_data, db_session)

            # --- INTENCIONES DIRECTAS O FLUJOS NUEVOS ---
            else:
                response_from_gemini = await generate_response(
                    user_message=message_text,
                    company=company_data,
                    current_intent=intent,
                    session_id=chat_session.id,
                    session_data=session_data
                )
                final_response_text = response_from_gemini.get("text", RESPONSES.get(intent, RESPONSES["unknown"]))

                if intent == "schedule_appointment":
                    session_data["in_appointment_flow"] = True
                    session_data["waiting_for_name"] = True
                    session_data["waiting_for_datetime"] = True
                    session_data["waiting_for_phone"] = True
                    session_data["conversation_state"] = "started"
                    await update_session_data(chat_session, session_data, db_session)
                elif intent == "cancel_appointment":
                    session_data["in_cancel_flow"] = True
                    session_data["waiting_for_cancel_datetime"] = True
                    session_data["conversation_state"] = "started"
                    await update_session_data(chat_session, session_data, db_session)
                elif intent in ["greet", "farewell"]:
                    session_data["conversation_state"] = "ended" if intent == "farewell" else "started"
                    await update_session_data(chat_session, session_data, db_session)

            await message_repository.add_message(
                db_session,
                str(uuid.uuid4()),
                final_response_text,
                "out",
                company_whatsapp_number,
                chat_session.company_id,
                chat_session.id,
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
    dia_semana_str = dias_semana.get(dt_obj.weekday())
    dia = dt_obj.day
    mes = nombres_meses.get(dt_obj.month)
    año = dt_obj.year
    hora = dt_obj.hour
    minuto = dt_obj.minute
    minuto_str = f"{minuto:02d}"
    return f"el {dia_semana_str} {dia} de {mes} de {año} a las {hora}:{minuto_str}"