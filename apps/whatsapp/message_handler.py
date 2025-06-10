import logging
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
import uuid

from twilio.twiml.messaging_response import MessagingResponse
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

def message_mentions_schedule(text: str) -> bool:
    text = text.lower()
    palabras_horario = ["horario", "hora", "abren", "abierto", "cierran", "cierra", "atienden"]
    return any(p in text for p in palabras_horario)

async def handle_incoming_message(
    user_phone_number: str,
    company_whatsapp_number: str,
    message_text: str,
    message_sid: str,
) -> str:
    async with get_db_session() as db_session:
        try:
            logger.info(f"Mensaje entrante de {user_phone_number}: '{message_text}'")

            # Obtener datos de la empresa por el número de WhatsApp (sin prefijo 'whatsapp:')
            cleaned_number = company_whatsapp_number
            if cleaned_number.startswith('whatsapp:'):
                cleaned_number = cleaned_number.replace('whatsapp:', '')
            company_obj = await get_company_by_number(cleaned_number, db_session)
            if company_obj:
                company_data = {
                    "name": company_obj.name,
                    "schedule": company_obj.schedule,
                    "catalog_url": company_obj.catalog_url,
                }
                company_id = company_obj.id
            else:
                company_data = {"name": None, "schedule": "", "catalog_url": ""}
                company_id = None

            # 1. Obtener o crear sesión de chat (si no hay empresa, no se puede crear sesión)
            if not company_id:
                final_response_text = "No se pudo identificar la empresa. Por favor, contacta al administrador."
                return _generate_twilio_response(final_response_text)

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

            # --- MANEJO DE SOLICITUD DE HORARIO, AUNQUE HAYA SALUDO ---
            if (intent and "horario" in intent) or message_mentions_schedule(message_text):
                if company_obj and company_obj.schedule and company_obj.name:
                    horario_real = company_obj.schedule
                    nombre_empresa = company_obj.name
                    prompt_gemini = (
                        f"Redacta un mensaje cordial y profesional para WhatsApp, informando al usuario el horario de atención de la empresa '{nombre_empresa}'. "
                        f"El horario real es: '{horario_real}'. "
                        "No pidas ningún tipo de aclaración, no preguntes nada, no digas que necesitas más información. "
                        "Solo responde usando el dato del horario proporcionado, como si fueras un asistente de la empresa. "
                        "Ejemplo de respuesta: El horario de atención de [nombre_empresa] es: [horario_real]."
                    )
                    instructions = (
                        "Responde únicamente con el dato de horario proporcionado, redactando de forma amable y profesional. "
                        "No pidas más información. No expliques nada. No generes preguntas. No digas que faltan datos. "
                        "Si en el mensaje encuentras el horario, solo respóndelo cordialmente con el dato real."
                    )
                    response_from_gemini = await generate_response(
                        user_message=prompt_gemini,
                        company=company_data,
                        current_intent="horario",
                        session_id=chat_session.id,
                        session_data=session_data,
                        instructions=instructions
                    )
                    final_response_text = response_from_gemini.get("text", "").strip()

                    # Fallback: Si Gemini NO obedece, responde tú mismo
                    if (
                        not final_response_text
                        or "necesito saber" in final_response_text.lower()
                        or "qué horario" in final_response_text.lower()
                        or "especifica" in final_response_text.lower()
                        or "no puedo" in final_response_text.lower()
                        or "no puedo darte" in final_response_text.lower()
                        or "no puedo ayudarte" in final_response_text.lower()
                        or "no puedo brindar" in final_response_text.lower()
                        or ("por favor" in final_response_text.lower() and "especifica" in final_response_text.lower())
                    ):
                        final_response_text = f"El horario de atención de {nombre_empresa} es: {horario_real}"
                else:
                    final_response_text = "Lo siento, no tengo registrado el horario de la empresa en este momento."

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

            # --- SALUDO PERSONALIZADO ---
            if intent in ("greet", "saludo") or not message_history or len(message_history) == 1:
                if company_obj and company_obj.name:
                    nombre_empresa = company_obj.name
                    prompt_gemini = (
                        f"Saluda cordialmente al usuario y dale la bienvenida a {nombre_empresa}. "
                        f"Pregunta en qué puede ayudarte, usando un tono profesional y cálido."
                    )
                    response_from_gemini = await generate_response(
                        user_message=prompt_gemini,
                        company=company_data,
                        current_intent=intent,
                        session_id=chat_session.id,
                        session_data=session_data
                    )
                    final_response_text = response_from_gemini.get("text", f"Hola, bienvenido a {nombre_empresa}. ¿En qué puedo ayudarte?")
                else:
                    final_response_text = "Hola, bienvenido. ¿En qué puedo ayudarte?"
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
            if session_data.get('in_appointment_flow', False) or (intent in ["schedule_appointment", "agendar_cita", "cita"]):
                # Si aún no ha iniciado, inicializa el flujo
                if not session_data.get('in_appointment_flow', False):
                    session_data["in_appointment_flow"] = True
                    session_data["waiting_for_name"] = True
                    session_data["waiting_for_datetime"] = True
                    session_data["waiting_for_phone"] = True
                    session_data["conversation_state"] = "started"
                # Extraer info relevante del mensaje
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

                # Pide lo que falta
                if missing_slots:
                    if "name" in missing_slots:
                        final_response_text = "Para agendar la cita necesito que me proporciones tu nombre."
                    elif "datetime" in missing_slots:
                        final_response_text = "¿Para qué fecha y hora deseas agendar tu cita?"
                    elif "phone" in missing_slots:
                        final_response_text = "Por favor, indícame tu número de teléfono para confirmar la cita."
                    else:
                        final_response_text = RESPONSES["unknown"]
                else:
                    client_name = session_data.get("client_name")
                    client_phone_number = session_data.get("client_phone_number")
                    appointment_datetime_str = session_data.get("appointment_datetime")
                    appointment_datetime_obj = datetime.fromisoformat(appointment_datetime_str) if appointment_datetime_str else None
                    if client_name and client_phone_number and appointment_datetime_obj:
                        from apps.calendar.calendar_integration import create_calendar_event
                        nombre_empresa = company_obj.name if company_obj else ""
                        summary = f"Cita {client_name} - {nombre_empresa}"
                        description = f"Cita agendada por WhatsApp para {client_name} ({client_phone_number})."
                        end_datetime_obj = appointment_datetime_obj + timedelta(hours=1)
                        calendar_event_link = await create_calendar_event(
                            summary,
                            description,
                            appointment_datetime_obj,
                            end_datetime_obj,
                            company_obj.calendar_email if company_obj else None
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
                            prompt_gemini = (
                                f"Confirma de manera cordial que la cita para {client_name} fue agendada para {appointment_display} en {nombre_empresa}."
                            )
                            response_from_gemini = await generate_response(
                                user_message=prompt_gemini,
                                company=company_data,
                                current_intent="confirm_appointment",
                                session_id=chat_session.id,
                                session_data=session_data
                            )
                            final_response_text = response_from_gemini.get("text", f"Perfecto, tu cita fue agendada para {appointment_display}.")
                            await clear_session_slots(chat_session, db_session)
                            session_data = chat_session.session_data
                        else:
                            final_response_text = RESPONSES["error"]
                            logger.error(f"Bot: Falló el agendamiento en Google Calendar: {calendar_event_link}")
                    else:
                        final_response_text = RESPONSES["unknown"]
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
                return _generate_twilio_response(final_response_text)

            # --- FLUJO DE CANCELACIÓN (idéntico a antes, puedes completarlo según tu lógica) ---
            if session_data.get('in_cancel_flow', False):
                # ... flujo de cancelación aquí ...
                pass

            # --- INTENCIONES DIRECTAS O FLUJOS NUEVOS ---
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