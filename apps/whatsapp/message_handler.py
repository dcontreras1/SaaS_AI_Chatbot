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
from apps.calendar.calendar_integration import (
    create_calendar_event,
    is_time_slot_available,
    delete_calendar_event
)

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
            cleaned_number = company_whatsapp_number.replace('whatsapp:', '')
            company_obj = await get_company_by_number(cleaned_number, db_session)
            if not company_obj:
                return _generate_twilio_response(
                    "No se pudo identificar la empresa. Por favor, contacta al administrador."
                )
            company_metadata = company_obj.company_metadata or {}
            appointment_slots = company_metadata.get("appointment_slots", [])
            confirmation_message = company_metadata.get(
                "confirmation_message", "Tu cita fue agendada."
            )
            company_name = company_obj.name or "la empresa"
            allow_parallel = company_metadata.get("allow_parallel_appointments", True)

            chat_session = await get_or_create_session(
                user_phone_number, company_obj.id, db_session
            )
            session_data = chat_session.session_data

            saludo_detectado = any(
                word in message_text.lower()
                for word in [
                    "hola",
                    "buenos días",
                    "buenas tardes",
                    "buenas noches",
                    "saludo",
                    "hey",
                ]
            )
            if session_data.get("in_appointment_flow", False) and saludo_detectado:
                session_data["in_appointment_flow"] = False
                session_data["slots_filled"] = {}
                session_data = make_json_serializable(session_data)
                await update_session_data(chat_session, session_data, db_session)
                msg = (
                    f"¡Hola! Soy el asistente virtual para {company_name}. ¿En qué puedo ayudarte?"
                )
                await message_repository.add_message(
                    db_session,
                    str(uuid.uuid4()),
                    msg,
                    "out",
                    company_whatsapp_number,
                    chat_session.company_id,
                    chat_session.id,
                )
                await db_session.commit()
                return _generate_twilio_response(msg)

            # ==============================
            # FLUJO DE CANCELACION DE CITAS
            # ==============================
            intent = await detect_intent(message_text, session_data)
            if intent == "cancel_appointment":
                event_id = session_data.get("event_id")
                calendar_id = company_obj.calendar_email
                if not event_id:
                    msg = "No se encontró una cita previa para cancelar. ¿Podrías indicarme la fecha y hora de la cita que deseas cancelar?"
                else:
                    deleted = delete_calendar_event(calendar_id, event_id)
                    if deleted:
                        msg = "Tu cita ha sido cancelada y eliminada del calendario."
                        session_data.pop("event_id", None)
                    else:
                        msg = "Hubo un error al intentar cancelar tu cita. Por favor intenta más tarde."
                await message_repository.add_message(
                    db_session,
                    str(uuid.uuid4()),
                    msg,
                    "out",
                    company_whatsapp_number,
                    chat_session.company_id,
                    chat_session.id,
                )
                session_data = make_json_serializable(session_data)
                await update_session_data(chat_session, session_data, db_session)
                await db_session.commit()
                return _generate_twilio_response(msg)
            # ==============================

            # Flujo de cita
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
                    if next_slot["key"] == "name":
                        info = await extract_info(
                            message_text,
                            session_data,
                            user_phone=user_phone_number,
                            slot="name",
                        )
                        value = info.get("name")
                        if not value:
                            msg = "¿Podrías indicarme el nombre de la persona para quien es la cita?"
                            await message_repository.add_message(
                                db_session,
                                str(uuid.uuid4()),
                                msg,
                                "out",
                                company_whatsapp_number,
                                chat_session.company_id,
                                chat_session.id,
                            )
                            await db_session.commit()
                            return _generate_twilio_response(msg)
                    elif "options" in next_slot:
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
                        if not value:
                            options_str = ", ".join(next_slot["options"])
                            msg = (
                                f"¿Con qué {next_slot['label']} prefieres tu cita? Puedes elegir entre {options_str}."
                            )
                            await message_repository.add_message(
                                db_session,
                                str(uuid.uuid4()),
                                msg,
                                "out",
                                company_whatsapp_number,
                                chat_session.company_id,
                                chat_session.id,
                            )
                            await db_session.commit()
                            return _generate_twilio_response(msg)
                    elif next_slot["key"] in [
                        "datetime",
                        "fecha",
                        "hora",
                        "fecha_hora",
                        "date",
                        "time",
                    ]:
                        info = await extract_info(
                            message_text,
                            session_data,
                            user_phone=user_phone_number,
                            slot=next_slot["key"],
                            options=None,
                        )
                        value = info.get("datetime") or info.get(next_slot["key"])
                        if not value:
                            msg = f"¿Para qué fecha y hora deseas la cita?"
                            await message_repository.add_message(
                                db_session,
                                str(uuid.uuid4()),
                                msg,
                                "out",
                                company_whatsapp_number,
                                chat_session.company_id,
                                chat_session.id,
                            )
                            await db_session.commit()
                            return _generate_twilio_response(msg)
                    else:
                        info = await extract_info(
                            message_text,
                            session_data,
                            user_phone=user_phone_number,
                        )
                        value = info.get(next_slot["key"])
                        if not value:
                            msg = f"Por favor indícame {next_slot['label']}."
                            await message_repository.add_message(
                                db_session,
                                str(uuid.uuid4()),
                                msg,
                                "out",
                                company_whatsapp_number,
                                chat_session.company_id,
                                chat_session.id,
                            )
                            await db_session.commit()
                            return _generate_twilio_response(msg)

                    # Si extrajo el valor, lo guarda
                    if value:
                        slots_filled[next_slot["key"]] = value
                        session_data["slots_filled"] = slots_filled
                        session_data = make_json_serializable(session_data)
                        await update_session_data(chat_session, session_data, db_session)

                        # Preguntar siguiente slot pendiente
                        pending_slot = None
                        for slot in appointment_slots:
                            if slot["key"] not in slots_filled:
                                pending_slot = slot
                                break

                        if pending_slot:
                            if pending_slot["key"] == "name":
                                msg = "¿Podrías indicarme el nombre de la persona para quien es la cita?"
                            elif "options" in pending_slot:
                                options_str = ", ".join(pending_slot["options"])
                                msg = f"¿Con qué {pending_slot['label']} prefieres tu cita? Puedes elegir entre {options_str}."
                            elif pending_slot["key"] in [
                                "datetime", "fecha", "hora", "fecha_hora", "date", "time"
                            ]:
                                msg = f"¿Para qué fecha y hora deseas la cita?"
                            else:
                                msg = f"Por favor indícame {pending_slot['label']}."
                            await message_repository.add_message(
                                db_session,
                                str(uuid.uuid4()),
                                msg,
                                "out",
                                company_whatsapp_number,
                                chat_session.company_id,
                                chat_session.id,
                            )
                            await db_session.commit()
                            return _generate_twilio_response(msg)
                        else:
                            session_data["in_appointment_flow"] = False
                            session_data = make_json_serializable(session_data)
                            await update_session_data(chat_session, session_data, db_session)
                            name = slots_filled.get("name", "")
                            appointment_datetime = slots_filled.get("datetime", "")
                            resource_slot = None
                            resource_value = None
                            for slot in appointment_slots:
                                if "options" in slot and slot["key"] in slots_filled:
                                    resource_slot = slot
                                    resource_value = slots_filled[slot["key"]]
                                    break
                            doctor_or_resource = resource_value or ""
                            fecha_str, hora_str = "", ""
                            appointment_dt = None
                            if appointment_datetime:
                                if isinstance(appointment_datetime, str):
                                    try:
                                        appointment_dt = datetime.fromisoformat(appointment_datetime)
                                    except Exception:
                                        appointment_dt = None
                                elif isinstance(appointment_datetime, datetime):
                                    appointment_dt = appointment_datetime
                                else:
                                    appointment_dt = None
                                if appointment_dt:
                                    fecha_str = appointment_dt.strftime("%d/%m/%Y")
                                    hora_str = appointment_dt.strftime("%H:%M")
                            summary = (
                                f"Cita {name} con {doctor_or_resource} - {company_name}"
                                if name
                                else f"Cita con {doctor_or_resource} - {company_name}"
                            )
                            description = (
                                f"Cita para {name} con {doctor_or_resource} agendada por WhatsApp para el paciente {user_phone_number}."
                            )
                            msg = f"Perfecto, {name}, tu cita con {doctor_or_resource} fue agendada para el {fecha_str} a las {hora_str}."
                            try:
                                if appointment_dt:
                                    end_datetime_obj = appointment_dt + timedelta(hours=1)
                                    calendar_id = company_obj.calendar_email
                                    slot_available = await is_time_slot_available(
                                        calendar_id,
                                        appointment_dt,
                                        end_datetime_obj,
                                        resource_name=resource_value,
                                        allow_parallel_appointments=allow_parallel
                                    )
                                    if not slot_available:
                                        msg = f"Ya hay una cita agendada con {doctor_or_resource or 'el especialista'} para esa fecha y hora. ¿Quieres elegir otro horario?"
                                        await message_repository.add_message(
                                            db_session,
                                            str(uuid.uuid4()),
                                            msg,
                                            "out",
                                            company_whatsapp_number,
                                            chat_session.company_id,
                                            chat_session.id,
                                        )
                                        await db_session.commit()
                                        return _generate_twilio_response(msg)
                                    calendar_event = await create_calendar_event(
                                        summary,
                                        description,
                                        appointment_dt,
                                        end_datetime_obj,
                                        company_obj.calendar_email if company_obj else None,
                                    )
                                    if isinstance(calendar_event, dict) and calendar_event.get("status") == "success":
                                        session_data["event_id"] = calendar_event.get("event_id")
                                        await update_session_data(chat_session, session_data, db_session)
                                    elif isinstance(calendar_event, dict) and calendar_event.get("status") == "conflict":
                                        msg = calendar_event.get("message", msg)
                                    elif isinstance(calendar_event, dict) and calendar_event.get("status") == "error":
                                        msg += " (No se pudo crear el evento en el calendario)"
                            except Exception as e:
                                logger.error(
                                    f"Error al crear evento en calendario o verificar disponibilidad: {e}"
                                )

                            await message_repository.add_message(
                                db_session,
                                str(uuid.uuid4()),
                                msg,
                                "out",
                                company_whatsapp_number,
                                chat_session.company_id,
                                chat_session.id,
                            )
                            await db_session.commit()
                            return _generate_twilio_response(msg)

            saludos = {
                "hola": "¡Hola!",
                "buenos días": "¡Buenos días!",
                "buenas tardes": "¡Buenas tardes!",
                "buenas noches": "¡Buenas noches!",
                "hey": "¡Hey!",
            }
            mensaje_usuario = message_text.lower().strip()
            for saludo, respuesta_saludo in saludos.items():
                if saludo in mensaje_usuario:
                    msg = f"{respuesta_saludo} Soy el asistente virtual para {company_name}. ¿En qué puedo ayudarte?"
                    await message_repository.add_message(
                        db_session,
                        str(uuid.uuid4()),
                        msg,
                        "out",
                        company_whatsapp_number,
                        chat_session.company_id,
                        chat_session.id,
                    )
                    await db_session.commit()
                    return _generate_twilio_response(msg)

            if intent in ["schedule_appointment", "agendar_cita", "cita"]:
                session_data["in_appointment_flow"] = True
                session_data["slots_filled"] = {}
                session_data = make_json_serializable(session_data)
                await update_session_data(chat_session, session_data, db_session)
                first_slot = appointment_slots[0] if appointment_slots else None
                if first_slot:
                    if first_slot["key"] == "name":
                        msg = "¿Podrías indicarme el nombre de la persona para quien es la cita?"
                    elif "options" in first_slot:
                        options_str = ", ".join(first_slot["options"])
                        msg = f"¿Con qué {first_slot['label']} prefieres tu cita? Puedes elegir entre {options_str}."
                    elif first_slot["key"] in [
                        "datetime",
                        "fecha",
                        "hora",
                        "fecha_hora",
                        "date",
                        "time",
                    ]:
                        msg = f"¿Para qué fecha y hora deseas la cita?"
                    else:
                        msg = f"Para agendar tu cita necesito saber {first_slot['label']}."
                    await message_repository.add_message(
                        db_session,
                        str(uuid.uuid4()),
                        msg,
                        "out",
                        company_whatsapp_number,
                        chat_session.company_id,
                        chat_session.id,
                    )
                    await db_session.commit()
                    return _generate_twilio_response(msg)
                else:
                    await db_session.commit()
                    return _generate_twilio_response(
                        "No hay configuración de slots para agendar citas en esta empresa."
                    )

            if "horario" in message_text.lower():
                horario = (
                    company_obj.schedule
                    or "No tengo registrado el horario en este momento."
                )
                msg = f"Nuestro horario de atención es: {horario}"
                await message_repository.add_message(
                    db_session,
                    str(uuid.uuid4()),
                    msg,
                    "out",
                    company_whatsapp_number,
                    chat_session.company_id,
                    chat_session.id,
                )
                await db_session.commit()
                return _generate_twilio_response(msg)

            msg = f"Soy el asistente virtual para {company_name}. ¿En qué puedo ayudarte?"
            await message_repository.add_message(
                db_session,
                str(uuid.uuid4()),
                msg,
                "out",
                company_whatsapp_number,
                chat_session.company_id,
                chat_session.id,
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