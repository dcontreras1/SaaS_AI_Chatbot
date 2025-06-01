import logging
from typing import Dict, Any, Optional
from datetime import datetime, timedelta, timezone
import uuid
import re

from twilio.twiml.messaging_response import MessagingResponse
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError

# Importaciones ajustadas a tu estructura de módulos
from apps.whatsapp.chat_session_repository import get_or_create_session, update_session_data, clear_session_slots
from apps.whatsapp import message_repository
from apps.ai.response_generator import generate_response
from apps.ai.nlp_utils import detect_intent, extract_contact_info
from db.database import get_db_session 
from db.models.company import Company
from db.models.appointment import Appointment 

logger = logging.getLogger(__name__)

# Respuestas predefinidas
RESPONSES = {
    "greet": "¡Hola! ¿En qué puedo ayudarte?",
    "ask_general": "Claro que sí. Nuestro horario de atención es de lunes a viernes, de 9:00 a 18:00 hs.",
    "farewell": "¡Adiós! Que tengas un excelente día.",
    "ask_bot_identity": "Soy un asistente virtual, diseñado para ayudarte con tus consultas y agendar citas.",
    "ask_bot_capabilities": "Puedo proporcionarte información sobre nuestro horario, precios, ubicación, catálogo de servicios y agendar citas. ¿Qué necesitas?",
    "ask_price": "Los precios varían según el servicio. ¿Qué tipo de servicio te interesa?",
    "ask_location": "Estamos ubicados en [Dirección de la Empresa]. Puedes encontrarnos en Google Maps buscando [Nombre de la Empresa].",
    "ask_catalog": "Puedes ver nuestro catálogo completo de servicios en el siguiente enlace: https://elclubdelcatalogo.com/.",
    "appointment_name_request": "Para agendar tu cita, necesito tu nombre completo, por favor.",
    "appointment_datetime_request": "Necesito la fecha y hora para tu cita. ¿Podrías indicarme el día y la hora, por ejemplo: 'el lunes a las 3pm' o 'el 15 de junio a las 10 de la mañana'?",
    "appointment_confirmation": "Perfecto, {name}. He agendado tu cita para el {datetime}. ¿Es correcto?", # Ya no se usa directamente
    "appointment_scheduled": "¡Excelente! Tu cita ha sido agendada con éxito para el {datetime} a nombre de {name}. Recibirás una confirmación en breve.",
    "appointment_reschedule_cancel": "Para reagendar o cancelar una cita, por favor, responde con 'reagendar cita' o 'cancelar cita' y el bot te guiará.",
    "unknown": "Lo siento, no entendí tu solicitud. ¿Podrías reformularla, por favor?",
    "error": "Lo siento, ha ocurrido un error interno muy grave y no puedo procesar tu solicitud en este momento. Por favor, inténtalo de nuevo más tarde.",
    "cancel_request": "Entendido. ¿Qué cita te gustaría cancelar? Por favor, dime la fecha y hora.",
    "cancel_confirm": "¿Estás seguro de que quieres cancelar la cita del {datetime} a nombre de {name}? Responde 'Sí' para confirmar o 'No' para mantenerla.",
    "cancel_success": "¡Tu cita del {datetime} a nombre de {name} ha sido cancelada con éxito! Esperamos verte pronto.",
    "cancel_not_found": "Lo siento, no encontré ninguna cita para cancelar con la información que me diste. ¿Podrías darme más detalles (fecha y hora, o tu nombre completo si es diferente al número de teléfono)?",
    "cancel_aborted": "De acuerdo, no se ha cancelado ninguna cita. ¿Hay algo más en lo que pueda ayudarte?",
    "cancel_invalid_confirmation": "Por favor, responde 'Sí' o 'No' para confirmar la cancelación."
}

async def handle_incoming_message(
    user_phone_number: str,
    company_whatsapp_number: str,
    message_text: str,
    message_sid: Optional[str] = None
) -> str:
    """
    Maneja los mensajes entrantes de WhatsApp.
    """
    logger.info(f"Procesando mensaje - De: {user_phone_number}, Para: {company_whatsapp_number}, Mensaje: '{message_text}', SID: {message_sid}")

    async with get_db_session() as db_session:
        logger.info(f"DEBUG HANDLER: Sesión de DB OBTENIDA (ID: {id(db_session)}, Tipo: {type(db_session)})")
        try:
            # 1. Obtener información de la compañía
            company_whatsapp_number_db_format = "whatsapp:" + company_whatsapp_number 
            result = await db_session.execute(
                select(Company).where(Company.company_number == company_whatsapp_number_db_format)
            )
            company = result.scalar_one_or_none()

            if not company:
                logger.error(f"Compañía no encontrada para el número de WhatsApp: {company_whatsapp_number_db_format}")
                return _generate_twilio_response(RESPONSES["error"])
            
            # 2. Cargar o crear la sesión de chat
            chat_session = await get_or_create_session(user_phone_number, company.id, db_session)
            session_data = chat_session.session_data if chat_session.session_data is not None else {}
            logger.info(f"DEBUG HANDLER: Sesión de chat persistente cargada (ID: {chat_session.id}). Datos: {session_data}")

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
            
            # 4. Extraer entidades (nombre, fecha/hora) del mensaje actual usando NLP
            current_message_entities = await extract_contact_info(message_text)
            extracted_name_nlp = current_message_entities.get('name')
            extracted_datetime_nlp = current_message_entities.get('datetime')
            
            logger.info(f"DEBUG HANDLER: Entidades extraídas con NLP_UTILS: Nombre={extracted_name_nlp}, Fecha/Hora={extracted_datetime_nlp}")

            # 5. Si hay entidades extraídas, actualiza la sesión inmediatamente
            if extracted_name_nlp:
                session_data['client_name'] = extracted_name_nlp
                session_data['waiting_for_name'] = False # Si extraemos, ya no esperamos
                logger.info(f"DEBUG SLOTS: Nombre '{extracted_name_nlp}' extraído por NLP y guardado en sesión.")
            
            if extracted_datetime_nlp:
                # Si estamos en flujo de cancelación, la fecha/hora es para cancelar
                if session_data.get('in_cancel_flow'):
                    session_data['appointment_datetime_to_cancel'] = extracted_datetime_nlp.isoformat()
                    session_data['waiting_for_cancel_datetime'] = False
                    logger.info(f"DEBUG SLOTS: Fecha/Hora '{extracted_datetime_nlp}' para CANCELACIÓN extraída por NLP y guardada en sesión.")
                else: # Si no es cancelación, es para agendamiento
                    session_data['appointment_datetime'] = extracted_datetime_nlp.isoformat()
                    session_data['waiting_for_datetime'] = False
                    logger.info(f"DEBUG SLOTS: Fecha/Hora '{extracted_datetime_nlp}' para AGENDAMIENTO extraída por NLP y guardada en sesión.")

            # 6. Determinar la intención principal del mensaje
            intent = await detect_intent(message_text)
            logger.info(f"DEBUG HANDLER: Intención detectada del mensaje actual: {intent}")
            logger.info(f"DEBUG HANDLER: Estado actual de in_appointment_flow: {session_data.get('in_appointment_flow')}, in_cancel_flow: {session_data.get('in_cancel_flow')}")

            final_response_text = ""

            # --- LÓGICA DE MANEJO DE FLUJOS (CANCELACIÓN Y AGENDAMIENTO) ---

            # PRIORIDAD 1: Flujo de Cancelación
            if intent == "cancel_appointment" or session_data.get('in_cancel_flow', False):
                logger.info("DEBUG FLOW: Entrando a flujo de cancelación.")
                session_data['in_cancel_flow'] = True
                session_data['in_appointment_flow'] = False # Salir del flujo de agendamiento
                
                # Estado: Esperando la fecha/hora de la cita a cancelar
                if session_data.get('waiting_for_cancel_datetime', True) and not session_data.get('appointment_datetime_to_cancel'):
                    final_response_text = RESPONSES["cancel_request"]
                    session_data['waiting_for_cancel_datetime'] = True
                    logger.info("DEBUG CANCEL: Pidiendo fecha/hora para cancelar.")

                # Estado: Tenemos la fecha/hora para cancelar, necesitamos confirmación
                elif session_data.get('appointment_datetime_to_cancel') and not session_data.get('waiting_for_cancel_confirmation'):
                    cancel_datetime_obj = datetime.fromisoformat(session_data['appointment_datetime_to_cancel'])
                    
                    # Buscar la cita en la DB
                    result = await db_session.execute(
                        select(Appointment).where(
                            Appointment.client_phone_number == user_phone_number,
                            Appointment.scheduled_for == cancel_datetime_obj,
                            Appointment.company_id == company.id,
                            Appointment.status == 'scheduled' # Asumo un estado 'scheduled' para citas activas
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
                        session_data = chat_session.session_data # Recargar session_data
                        logger.info("DEBUG CANCEL: No se encontró la cita con los datos proporcionados.")
                
                # Estado: Esperando confirmación final (Sí/No)
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
                
                else: # Catch-all para el flujo de cancelación si no se cumple ninguna de las anteriores
                    final_response_text = RESPONSES["cancel_request"]
                    session_data['waiting_for_cancel_datetime'] = True
                    logger.info("DEBUG CANCEL: En flujo de cancelación, estado ambiguo. Volviendo a pedir fecha.")

            # PRIORIDAD 2: Flujo de Agendamiento
            elif intent == "schedule_appointment" or session_data.get('in_appointment_flow', False):
                logger.info("DEBUG FLOW: Entrando a flujo de agendamiento.")
                session_data['in_appointment_flow'] = True
                session_data['in_cancel_flow'] = False # Salir del flujo de cancelación
                
                # *** LÓGICA CORREGIDA PARA AGENDAMIENTO: Priorizar el agendamiento si tenemos todo ***
                # Estado: Tenemos el nombre Y la fecha/hora, procedemos a agendar
                if session_data.get('client_name') and session_data.get('appointment_datetime'):
                    logger.info("DEBUG SLOTS: Agendamiento - Todos los datos obtenidos. Procediendo a agendar cita.")
                    try:
                        app_datetime_obj = datetime.fromisoformat(session_data['appointment_datetime'])
                        
                        # Crear el registro de la cita en la DB
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
                        # Limpiar slots después de agendar exitosamente
                        await clear_session_slots(chat_session, db_session)
                        session_data = chat_session.session_data # Recargar session_data después de clear
                        logger.info("DEBUG SLOTS: Cita agendada exitosamente y slots limpiados.")
                    except Exception as e:
                        logger.error(f"Error al agendar cita: {e}", exc_info=True)
                        final_response_text = RESPONSES["error"]
                        await clear_session_slots(chat_session, db_session)
                        session_data = chat_session.session_data
                        logger.info("DEBUG SLOTS: Error al agendar cita. Slots limpiados.")

                # Estado: Necesitamos el nombre del cliente (si no lo tenemos aún)
                elif not session_data.get('client_name'):
                    logger.info("DEBUG SLOTS: Agendamiento - Falta nombre.")
                    # Intentar inferir el nombre del mensaje si no es una pregunta
                    # (Esta lógica ya estaba, la mantengo)
                    if not extracted_name_nlp: # Si no lo extrajo NLP directamente
                        if intent == "provide_contact_info_followup" or \
                           (intent == "unknown" and not re.search(r'\?$', message_text.strip())):
                            potential_name_from_msg = message_text.strip().title()
                            if len(potential_name_from_msg) > 2 and \
                               not any(keyword in potential_name_from_msg.lower() for keyword in ["agendar", "cita", "lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo", "pm", "am", "hola", "gracias", "por favor", "si", "no", "cancelar"]):
                                session_data['client_name'] = potential_name_from_msg
                                session_data['waiting_for_name'] = False
                                logger.info(f"DEBUG SLOTS: Nombre '{potential_name_from_msg}' inferido del mensaje.")
                    
                    if not session_data.get('client_name'): # Si aún necesitamos el nombre después de intentar inferir
                        final_response_text = RESPONSES["appointment_name_request"]
                        session_data['waiting_for_name'] = True 
                        logger.info("DEBUG SLOTS: Agendamiento - Pidiendo nombre.")
                    else: # Si ya tenemos el nombre (por NLP o inferencia)
                        logger.info("DEBUG SLOTS: Nombre obtenido. Pasando a pedir fecha/hora.")
                        final_response_text = RESPONSES["appointment_datetime_request"]
                        session_data['waiting_for_datetime'] = True

                # Estado: Tenemos el nombre, pero necesitamos la fecha/hora (si no la tenemos aún)
                elif not session_data.get('appointment_datetime'):
                    final_response_text = RESPONSES["appointment_datetime_request"]
                    session_data['waiting_for_datetime'] = True
                    logger.info("DEBUG SLOTS: Agendamiento - Falta fecha/hora. Pidiendo fecha/hora.")
                
                else: # Catch-all para el flujo de agendamiento si algo inesperado sucede
                    logger.warning("DEBUG SLOTS: En flujo de agendamiento, pero estado inesperado. Datos: %s", session_data)
                    final_response_text = RESPONSES["unknown"]
                    # Podrías considerar un clear_session_slots si el estado es realmente irrecuperable aquí.


            # PRIORIDAD 3: Flujo General (si ninguna de las anteriores se activó)
            else:
                logger.info("DEBUG FLOW: Entrando a flujo general / LLM.")
                # Antes de ir al LLM, asegurarse de que no estábamos en un flujo anterior que se reseteó
                # Si el LLM "sugiere" un flujo, lo iniciamos.
                # Si el LLM no sugiere nada y no hay un flujo activo, significa que el usuario está en una consulta general.
                
                # Si el usuario NO está en un flujo y su intención no es iniciar uno,
                # entonces se debe resetear los flags si estaban activos por un error o mensaje ambiguo.
                # PERO, si el mensaje actual es una *respuesta* a una pregunta del bot (como "Daniel Contreras" a "dame tu nombre"),
                # entonces el intent podría ser 'unknown' o 'provide_contact_info_followup' y NO debería resetearse.
                # La lógica debe manejar esto con el 'in_appointment_flow' o 'in_cancel_flow' flags activos.

                # Si llegamos aquí, significa que ni "cancel_appointment" ni "schedule_appointment" fueron el intent *principal*
                # y tampoco session_data['in_cancel_flow'] ni session_data['in_appointment_flow'] eran True AL PRINCIPIO de este `if/elif/else` anidado.
                # Esto es crucial: el 'else' final significa que NO estábamos en un flujo específico.

                # Por lo tanto, si llegamos aquí, sí se deben limpiar los estados de flujo específicos
                # (aunque los slots ya se limpiaron si el flujo terminó con éxito).
                session_data['in_appointment_flow'] = False
                session_data['in_cancel_flow'] = False
                session_data['waiting_for_name'] = True
                session_data['waiting_for_datetime'] = True
                session_data['waiting_for_cancel_datetime'] = True
                session_data['waiting_for_cancel_confirmation'] = False
                session_data['confirm_cancel_id'] = None
                session_data['appointment_datetime_to_cancel'] = None
                logger.info("DEBUG FLOW: Reseteando flags de flujo para entrada a LLM general.")


                llm_response_text = await generate_response(
                    user_message=message_text, 
                    company={
                        "name": company.name, 
                        "schedule": company.schedule, 
                        "catalog_url": company.catalog_url, 
                        "calendar_email": company.calendar_email
                    }
                )
                final_response_text = llm_response_text
                
                # Si la respuesta del LLM sugiere un flujo de agendamiento o cancelación, iniciarlo
                if "agendar cita" in final_response_text.lower() or "agenda una cita" in final_response_text.lower() or "reservar cita" in final_response_text.lower():
                    logger.info("DEBUG FLOW: LLM sugirió agendar, iniciando flujo de agendamiento.")
                    session_data['in_appointment_flow'] = True
                    session_data['in_cancel_flow'] = False
                    session_data['waiting_for_name'] = True # Asumir que necesitamos el nombre al iniciar el flujo
                    session_data['waiting_for_datetime'] = True # Asumir que necesitamos la fecha/hora
                    final_response_text = RESPONSES["appointment_name_request"] # La primera pregunta del flujo

                elif any(k in final_response_text.lower() for k in ["cancelar cita", "anular cita", "eliminar cita"]):
                    logger.info("DEBUG FLOW: LLM sugirió cancelar, iniciando flujo de cancelación.")
                    session_data['in_cancel_flow'] = True
                    session_data['in_appointment_flow'] = False
                    session_data['waiting_for_cancel_datetime'] = True # La primera pregunta del flujo de cancelación
                    final_response_text = RESPONSES["cancel_request"]
                
                # Si el LLM no sugirió nada, y no es un flujo, se queda con la respuesta del LLM.

            # --- FIN LÓGICA DE MANEJO DE FLUJOS ---

            # 7. Guardar el estado actualizado de la sesión en la DB
            await update_session_data(chat_session, session_data, db_session)
            await db_session.commit()
            logger.info("DEBUG SLOTS: Estado de sesión guardado. Datos: %s", chat_session.session_data)

            # 8. Guardar la respuesta del bot en la DB
            await message_repository.add_message(
                db_session=db_session,
                message_sid=f"bot-{uuid.uuid4()}",
                body=final_response_text,
                direction="out",
                sender_phone_number=company_whatsapp_number,
                company_id=company.id,
                chat_session_id=chat_session.id
            )
            await db_session.commit() # Commit final para el mensaje saliente
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
    """
    Genera la respuesta TwiML para enviar un mensaje.
    """
    response = MessagingResponse()
    response.message(message)
    return str(response)

def _format_datetime_for_display(dt_obj: datetime) -> str:
    """
    Formatea un objeto datetime a una cadena legible para el usuario (ej. "lunes, 31 de mayo a las 3:00 p.m.").
    """
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
    
    # Asegúrate de que la fecha sea para el año actual si no se especifica explícitamente en el mensaje.
    # Si detect_intent/extract_contact_info ya maneja el año, esto podría ser redundante o requerir ajuste.
    # Para el ejemplo "lunes a las 3pm", asumirá el lunes más cercano.
    
    # Calcula la fecha real si dt_obj no tiene el año de contexto (si viene de NLP_UTILS solo con día de semana y hora)
    # Por ejemplo, si hoy es mayo 2025 y el usuario dice "lunes a las 3pm"
    # Puede que NLP devuelva un datetime para el lunes más cercano, que podría ser 2 de junio de 2025.
    
    # Si quieres que siempre muestre el año actual si no se especifica, y la fecha es futura.
    # Esto es solo un ejemplo de cómo podrías querer el formato final.
    # Tu _format_datetime_for_display ya es robusto, lo dejaré tal cual para los ejemplos.
    
    hora_str = dt_obj.strftime("%I:%M %p").replace("AM", "a.m.").replace("PM", "p.m.").lower()
    
    return f"{dia_semana_str}, {dt_obj.day} de {mes_str} a las {hora_str}"