from apps.whatsapp.whatsapp_api import send_whatsapp_message
from db.database import get_db_session
from db.models.unknown_clients import UnknownClient
from db.models.messages import Message
from db.models.client import Client
from db.models.appointment import Appointment
from apps.ai.nlp_utils import detect_intent, extract_contact_info
from sqlalchemy.future import select

async def handle_incoming_message(message_data, db_session=None):
    user_number = message_data["From"].replace("whatsapp:", "")
    company_number = message_data["To"].replace("whatsapp:", "")
    message_text = message_data["Body"]
    
    print(f"Datos del webhook: From={user_number}, To={company_number}, Body={message_text}")

    if db_session is None:
        async for session in get_db_session():
            db_session = session
            break

    # Guardar mensaje
    new_message = Message(
        content=message_text,
        direction="in",
        sender=user_number,
        company_id=1  # Reemplazar con lógica real para múltiples empresas
    )
    db_session.add(new_message)

    # Verificar si el usuario ya es cliente registrado
    result = await db_session.execute(select(Client).where(Client.phone_number == user_number))
    client = result.scalars().first()

    # Si no está registrado, guardarlo como cliente desconocido si no existe
    if not client:
        unknown_result = await db_session.execute(
            select(UnknownClient).where(UnknownClient.phone_number == user_number)
        )
        if not unknown_result.scalars().first():
            db_session.add(UnknownClient(phone_number=user_number))

    # Determinar intención
    intent = detect_intent(message_text)
    entities = extract_contact_info(message_text)

    if intent == "ask_general":
        await send_whatsapp_message(user_number, "Claro, nuestros horarios son de lunes a viernes de 9am a 6pm.")

    elif intent == "schedule_appointment":
        await send_whatsapp_message(
            user_number,
            "Perfecto, para agendar una cita necesito tu nombre completo, número de teléfono, día y hora de preferencia."
        )

    elif intent == "provide_contact":
        name = entities.get("name")
        phone = entities.get("phone") or user_number
        appointment_datetime = entities.get("datetime")

        if name and appointment_datetime:
            # Crear cliente si no existe
            result = await db_session.execute(select(Client).where(Client.phone_number == phone))
            client = result.scalars().first()
            if not client:
                client = Client(name=name, phone_number=phone)
                db_session.add(client)
                await db_session.flush()  # Para obtener client.id

            # Crear la cita
            appointment = Appointment(
                client_id=client.id,
                company_id=1,  # Reemplazar con lógica real
                scheduled_for=appointment_datetime
            )
            db_session.add(appointment)

            await send_whatsapp_message(
                user_number,
                f"Gracias {name}, tu cita ha sido registrada para el {appointment_datetime.strftime('%A %d de %B a las %H:%M')}"
            )
        else:
            await send_whatsapp_message(
                user_number,
                "Falta información para agendar la cita. Por favor incluye tu nombre, número, día y hora."
            )

    else:
        await send_whatsapp_message(user_number, "Lo siento, no entendí tu mensaje. ¿Podrías reformularlo?")

    await db_session.commit()
