from apps.whatsapp.whatsapp_api import send_whatsapp_message
# Ya no es necesario importar get_db_session aquí, se inyecta
from db.models.unknown_clients import UnknownClient
from db.models.messages import Message
from db.models.client import Client
from db.models.appointment import Appointment
from apps.ai.nlp_utils import detect_intent, extract_contact_info
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession # Asegúrate de que esto esté importado
import logging
import traceback # Asegúrate de que esto esté importado
from datetime import datetime # Para el manejo de fechas en Appointment

# --- Configura el logger para este módulo si no está configurado globalmente ---
logger = logging.getLogger(__name__)
# -----------------------------------------------------------------------------

# ¡CORRECCIÓN CLAVE AQUÍ!
# Elimina 'db_session=None' y asegúrate de que esté tipado correctamente.
async def handle_incoming_message(message_data: dict, db_session: AsyncSession):
    """
    Maneja un mensaje entrante de WhatsApp.
    
    Args:
        message_data (dict): Datos del mensaje con las claves:
            - From: número del remitente (con prefijo whatsapp:)
            - To: número de destino (con prefijo whatsapp:)
            - Body: contenido del mensaje
        db_session (AsyncSession): La sesión de base de datos inyectada por FastAPI.
    """
    try:
        # --- LÍNEA DE DEPURACIÓN CRÍTICA ---
        logger.info(f"DEBUG HANDLER: Sesión RECIBIDA en handle_incoming_message (ID: {id(db_session)}, Tipo: {type(db_session)})")
        # -----------------------------------

        # Extraer y limpiar números
        user_number = message_data["From"].replace("whatsapp:", "")
        company_number = message_data["To"].replace("whatsapp:", "")
        message_text = message_data["Body"]
        
        logger.info(f"Procesando mensaje - De: {user_number}, Para: {company_number}, Mensaje: {message_text}")

        # ¡ELIMINADO! Este bloque ya no es necesario ni correcto.
        # La sesión db_session siempre será una AsyncSession inyectada por FastAPI.
        # if db_session is None:
        #     async for session in get_db_session():
        #         db_session = session
        #         break

        # Guardar mensaje
        new_message = Message(
            content=message_text,
            direction="in",
            sender=user_number,
            company_id=1  # Reemplazar con lógica real para múltiples empresas
        )
        db_session.add(new_message) # ¡Esta es la línea que falla!

        # Verificar si el usuario ya es cliente registrado
        result = await db_session.execute(select(Client).where(Client.phone_number == user_number))
        client = result.scalars().first()

        # Si no está registrado, guardarlo como cliente desconocido
        if not client:
            unknown_result = await db_session.execute(
                select(UnknownClient).where(UnknownClient.phone_number == user_number)
            )
            if not unknown_result.scalars().first():
                db_session.add(UnknownClient(phone_number=user_number))
                logger.info(f"Nuevo cliente desconocido registrado: {user_number}")

        # Determinar intención
        intent = detect_intent(message_text)
        entities = extract_contact_info(message_text)
        
        logger.info(f"Intención detectada: {intent}")
        if entities:
            logger.info(f"Entidades extraídas: {entities}")

        # Procesar según la intención
        if intent == "ask_general":
            response = "Claro, nuestros horarios son de lunes a viernes de 9am a 6pm."
            await send_whatsapp_message(user_number, response)
            logger.info(f"Respuesta enviada a {user_number}: {response}")

        elif intent == "schedule_appointment":
            response = "Perfecto, para agendar una cita necesito tu nombre completo, número de teléfono, día y hora de preferencia."
            await send_whatsapp_message(user_number, response)
            logger.info(f"Solicitud de información de cita enviada a {user_number}")

        elif intent == "provide_contact":
            name = entities.get("name")
            phone = entities.get("phone") or user_number
            appointment_datetime_str = entities.get("datetime") # Obtener como string

            if name and appointment_datetime_str:
                # Convertir la fecha y hora a un objeto datetime si es necesario para el modelo
                try:
                    # Asume que datetime_str está en un formato que puede ser parseado
                    # Puedes ajustar el formato ('%Y-%m-%d %H:%M') según lo que devuelva tu NLP
                    appointment_datetime = datetime.strptime(appointment_datetime_str, '%Y-%m-%d %H:%M')
                except ValueError:
                    logger.error(f"Formato de fecha/hora incorrecto: {appointment_datetime_str}")
                    response = "No pude entender la fecha y hora. Por favor, asegúrate de usar un formato claro (ej. 'mañana a las 3pm')."
                    await send_whatsapp_message(user_number, response)
                    return {"success": False, "error": "Formato de fecha/hora incorrecto"}

                # Crear cliente si no existe
                result = await db_session.execute(select(Client).where(Client.phone_number == phone))
                client = result.scalars().first()
                if not client:
                    client = Client(name=name, phone_number=phone)
                    db_session.add(client)
                    await db_session.flush() # Importante para obtener client.id antes del commit
                    logger.info(f"Nuevo cliente registrado: {name} ({phone})")

                # Crear la cita
                appointment = Appointment(
                    client_id=client.id,
                    company_id=1,
                    scheduled_for=appointment_datetime # Pasa el objeto datetime
                )
                db_session.add(appointment)
                logger.info(f"Cita agendada para {name} en {appointment_datetime}")

                response = f"Gracias {name}, tu cita ha sido registrada para el {appointment_datetime.strftime('%A %d de %B a las %H:%M')}"
                await send_whatsapp_message(user_number, response)
                logger.info(f"Confirmación de cita enviada a {user_number}")
            else:
                response = "Falta información para agendar la cita. Por favor incluye tu nombre, número, día y hora."
                await send_whatsapp_message(user_number, response)
                logger.info(f"Solicitud de información adicional enviada a {user_number}")

        else:
            response = "Lo siento, no entendí tu mensaje. ¿Podrías reformularlo?"
            await send_whatsapp_message(user_number, response)
            logger.info(f"Mensaje de no entendido enviado a {user_number}")

        await db_session.commit()
        return {"success": True}

    except Exception as e:
        logger.error(f"Error procesando mensaje: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return {"success": False, "error": str(e)}