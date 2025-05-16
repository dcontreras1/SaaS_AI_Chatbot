from apps.ai.response_generator import generate_response
from apps.whatsapp.whatsapp_api import send_whatsapp_message
from db.models.companies import get_company_by_number
from db.models.messages import Message
from db.database import get_db_session
import datetime

async def handle_incoming_message(message: dict, phone_number_id: str = None):
    sender = message.get("From")
    text = message.get("Body", "")
    receiver_number = message.get("To")

    if not sender or not text or not receiver_number:
        print("Mensaje inválido:", message)
        return

    company = await get_company_by_number(receiver_number)
    if not company:
        print("Empresa no registrada para número:", receiver_number)
        return

    async for session in get_db_session():
        # Guardar mensaje recibido
        incoming_msg = Message(
            content=text,
            timestamp=datetime.datetime.now(),
            company_id=company.id,
            direction="in",
            sender=sender
        )
        session.add(incoming_msg)

        # Generar respuesta con IA
        response_text = await generate_response(text, company)

        # Guardar mensaje de salida
        outgoing_msg = Message(
            content=response_text,
            timestamp=datetime.datetime.now(),
            company_id=company.id,
            direction="out",
            sender=sender
        )
        session.add(outgoing_msg)

        await session.commit()

    await send_whatsapp_message(to_number=sender, message=response_text, from_number=receiver_number)
