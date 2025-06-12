import logging
from typing import Dict, Any
from datetime import datetime, timedelta
import uuid
import unicodedata

from twilio.twiml.messaging_response import MessagingResponse
from sqlalchemy.exc import SQLAlchemyError

from apps.whatsapp.chat_session_repository import get_or_create_session, update_session_data
from apps.whatsapp import message_repository
from apps.ai.nlp_utils import detect_intent, extract_info
from db.database import get_db_session
from db.models.companies import get_company_by_number
from apps.calendar.calendar_integration import create_calendar_event

logger = logging.getLogger(__name__)

def _generate_twilio_response(message: str) -> str:
    response = MessagingResponse()
    response.message(message)
    return str(response)

def normalize_text(text):
    if not text:
        return ""
    return unicodedata.normalize('NFD', text.strip().lower()).encode('ascii', 'ignore').decode('utf-8')

def make_json_serializable(obj):
    """
    Recursively convert datetime objects to isoformat strings in dicts/lists.
    """
    if isinstance(obj, dict):
        return {k: make_json_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [make_json_serializable(i) for i in obj]
    elif isinstance(obj, datetime):
        return obj.isoformat()
    else:
        return obj

async def handle_incoming_message(
    user_phone_number: str,
    company_whatsapp_number: str,
    message_text: str,
    message_sid: str,
) -> str:
    async with get_db_session() as db_session:
        try:
            # Obtener empresa y metadata
            cleaned_number = company_whatsapp_number.replace('whatsapp:', '')
            company_obj = await get_company_by_number(cleaned_number, db_session)
            if not company_obj:
                return _generate_twilio_response(
                    "No se pudo identificar la empresa. Por favor, contacta al administrador."
                )
            company_metadata = company_obj.company_metadata or {}
            appointment_slots = company_metadata.get("appointment_slots", [])
            confirmation_message = company_metadata.get("confirmation_message", "Tu cita fue agendada.")
            company_name = company_obj.name or "la empresa"

            chat_session = await get_or_create_session(user_phone_number, company_obj.id, db_session)
            session_data = chat_session.session_data

            # Interrupción del flujo de cita con saludo
            saludo_detectado = any(
                word in message_text.lower() for word in [
                    "hola", "buenos días", "buenas tardes", "buenas noches", "saludo", "hey"
                ]
            )
            if session_data.get("in_appointment_flow", False) and saludo_detectado:
                session_data["in_appointment_flow"] = False
                session_data["slots_filled"] = {}
                session_data = make_json_serializable(session_data)
                await update_session_data(chat_session, session_data, db_session)
                msg = f"¡Hola! Soy el asistente virtual para {company_name}. ¿En qué puedo ayudarte?"
                await message_repository.add_message(
                    db_session, str(uuid.uuid4()), msg, "out",
                    company_whatsapp_number, chat_session.company_id, chat_session.id
                )
                await db_session.commit()
                return _generate_twilio_response(msg)

            # Flujo de cita usando Gemini para extraer opciones y fechas
            if session_data.get("in_appointment_flow", False):
                slots_filled = session_data.get("slots_filled", {})
                # Busca el siguiente slot pendiente
                next_slot = None
                for slot in appointment_slots:
                    if slot["key"] not in slots_filled:
                        next_slot = slot
                        break

                if next_slot:
                    value = None
                    # Usar LLM para slots con opciones o para fecha/hora
                    if "options" in next_slot:
                        info = await extract_info(
                            message_text,
                            session_data,
                            user_phone=user_phone_number,
                            slot=next_slot["key"],
                            options=next_slot["options"],
                        )
                        gemini_value = info.get(next_slot["key"])
                        matched_option = None
                        if gemini_value:
                            normalized_gemini = normalize_text(gemini_value)
                            for opt in next_slot["options"]:
                                if normalize_text(opt) == normalized_gemini:
                                    matched_option = opt
                                    break
                            if not matched_option:
                                for opt in next_slot["options"]:
                                    if normalized_gemini in normalize_text(opt):
                                        matched_option = opt
                                        break
                        value = matched_option
                    elif next_slot["key"] in ["datetime", "fecha", "hora", "fecha_hora", "date", "time"]:
                        info = await extract_info(
                            message_text,
                            session_data,
                            user_phone=user_phone_number,
                            slot=next_slot["key"],
                            options=None
                        )
                        value = info.get("datetime") or info.get(next_slot["key"])
                    else:
                        info = await extract_info(
                            message_text,
                            session_data,
                            user_phone=user_phone_number
                        )
                        value = info.get(next_slot["key"])

                    if value:
                        slots_filled[next_slot["key"]] = value
                        session_data["slots_filled"] = slots_filled
                        session_data = make_json_serializable(session_data)
                        await update_session_data(chat_session, session_data, db_session)
                        # Busca el siguiente slot después de llenar este
                        for slot2 in appointment_slots:
                            if slot2["key"] not in slots_filled:
                                if "options" in slot2:
                                    options_str = ", ".join(slot2["options"])
                                    msg = f"Por favor indícame {slot2['label']}. Opciones: {options_str}."
                                elif slot2["key"] in ["datetime", "fecha", "hora", "fecha_hora", "date", "time"]:
                                    msg = f"Por favor indícame {slot2['label']}."
                                else:
                                    msg = f"Por favor indícame {slot2['label']}."
                                await message_repository.add_message(
                                    db_session, str(uuid.uuid4()), msg, "out",
                                    company_whatsapp_number, chat_session.company_id, chat_session.id
                                )
                                await db_session.commit()
                                return _generate_twilio_response(msg)
                        # Si ya no hay slots pendientes, confirma y agenda la cita
                        session_data["in_appointment_flow"] = False
                        session_data = make_json_serializable(session_data)
                        await update_session_data(chat_session, session_data, db_session)
                        msg = confirmation_message.format(**slots_filled)
                        try:
                            appointment_datetime = slots_filled.get("datetime")
                            doctor = slots_filled.get("doctor")
                            appointment_dt = None
                            if appointment_datetime:
                                if isinstance(appointment_datetime, str):
                                    try:
                                        appointment_dt = datetime.fromisoformat(appointment_datetime)
                                    except Exception:
                                        pass
                                elif isinstance(appointment_datetime, datetime):
                                    appointment_dt = appointment_datetime
                            summary = f"Cita {doctor or user_phone_number} - {company_name}"
                            description = f"Cita agendada por WhatsApp para {user_phone_number}."
                            if appointment_dt:
                                end_datetime_obj = appointment_dt + timedelta(hours=1)
                                calendar_event_link = await create_calendar_event(
                                    summary,
                                    description,
                                    appointment_dt,
                                    end_datetime_obj,
                                    company_obj.calendar_email if company_obj else None
                                )
                                if "Error" in calendar_event_link:
                                    msg += " (No se pudo crear el evento en el calendario)"
                        except Exception as e:
                            logger.error(f"Error al crear evento en calendario: {e}")

                        await message_repository.add_message(
                            db_session, str(uuid.uuid4()), msg, "out",
                            company_whatsapp_number, chat_session.company_id, chat_session.id
                        )
                        await db_session.commit()
                        return _generate_twilio_response(msg)
                    else:
                        if "options" in next_slot:
                            options_str = ", ".join(next_slot["options"])
                            msg = f"Por favor indícame {next_slot['label']}. Opciones: {options_str}."
                        else:
                            msg = f"Por favor indícame {next_slot['label']}."
                        await message_repository.add_message(
                            db_session, str(uuid.uuid4()), msg, "out",
                            company_whatsapp_number, chat_session.company_id, chat_session.id
                        )
                        await db_session.commit()
                        return _generate_twilio_response(msg)
                else:
                    msg = confirmation_message.format(**slots_filled)
                    session_data["in_appointment_flow"] = False
                    session_data = make_json_serializable(session_data)
                    await update_session_data(chat_session, session_data, db_session)
                    await message_repository.add_message(
                        db_session, str(uuid.uuid4()), msg, "out",
                        company_whatsapp_number, chat_session.company_id, chat_session.id
                    )
                    await db_session.commit()
                    return _generate_twilio_response(msg)

            # Saludo fuera de cualquier flujo activo
            saludos = {
                "hola": "¡Hola!",
                "buenos días": "¡Buenos días!",
                "buenas tardes": "¡Buenas tardes!",
                "buenas noches": "¡Buenas noches!",
                "hey": "¡Hey!"
            }
            mensaje_usuario = message_text.lower().strip()
            for saludo, respuesta_saludo in saludos.items():
                if saludo in mensaje_usuario:
                    msg = f"{respuesta_saludo} Soy el asistente virtual para {company_name}. ¿En qué puedo ayudarte?"
                    await message_repository.add_message(
                        db_session, str(uuid.uuid4()), msg, "out",
                        company_whatsapp_number, chat_session.company_id, chat_session.id
                    )
                    await db_session.commit()
                    return _generate_twilio_response(msg)

            # Inicio del flujo de agendamiento si detecta intención
            intent = await detect_intent(message_text, session_data)
            if intent in ["schedule_appointment", "agendar_cita", "cita"]:
                session_data["in_appointment_flow"] = True
                session_data["slots_filled"] = {}
                session_data = make_json_serializable(session_data)
                await update_session_data(chat_session, session_data, db_session)
                first_slot = appointment_slots[0] if appointment_slots else None
                if first_slot:
                    if "options" in first_slot:
                        options_str = ", ".join(first_slot["options"])
                        msg = f"Para agendar tu cita necesito saber {first_slot['label']}. Opciones: {options_str}."
                    else:
                        msg = f"Para agendar tu cita necesito saber {first_slot['label']}."
                    await message_repository.add_message(
                        db_session, str(uuid.uuid4()), msg, "out",
                        company_whatsapp_number, chat_session.company_id, chat_session.id
                    )
                    await db_session.commit()
                    return _generate_twilio_response(msg)
                else:
                    await db_session.commit()
                    return _generate_twilio_response(
                        "No hay configuración de slots para agendar citas en esta empresa."
                    )

            # Manejo de otros intents, como horario
            if "horario" in message_text.lower():
                horario = company_obj.schedule or "No tengo registrado el horario en este momento."
                msg = f"Nuestro horario de atención es: {horario}"
                await message_repository.add_message(
                    db_session, str(uuid.uuid4()), msg, "out",
                    company_whatsapp_number, chat_session.company_id, chat_session.id
                )
                await db_session.commit()
                return _generate_twilio_response(msg)

            # Fallback: Respuesta general
            msg = f"Soy el asistente virtual para {company_name}. ¿En qué puedo ayudarte?"
            await message_repository.add_message(
                db_session, str(uuid.uuid4()), msg, "out",
                company_whatsapp_number, chat_session.company_id, chat_session.id
            )
            await db_session.commit()
            return _generate_twilio_response(msg)

        except SQLAlchemyError as e:
            await db_session.rollback()
            logger.error(f"Error de base de datos en message_handler: {e}", exc_info=True)
            return _generate_twilio_response(
                "Lo siento, algo salió mal. Por favor, inténtalo de nuevo más tarde."
            )
        except Exception as e:
            logger.error(f"Error general en handle_incoming_message: {e}", exc_info=True)
            return _generate_twilio_response(
                "Lo siento, algo salió mal. Por favor, inténtalo de nuevo más tarde."
            )