import os
import logging
from fastapi import APIRouter, Form
from fastapi.responses import PlainTextResponse
from dotenv import load_dotenv
from typing import Optional
from apps.whatsapp.message_handler import handle_incoming_message # Asegúrate que esta importación sea correcta
from twilio.twiml.messaging_response import MessagingResponse

load_dotenv()
logger = logging.getLogger(__name__)

webhook_router = APIRouter()

@webhook_router.post("/webhook", response_class=PlainTextResponse)
async def twilio_webhook(
    From: str = Form(...),
    Body: str = Form(...),
    To: str = Form(...),
    # Twilio también envía MessageSid, lo capturamos si está disponible
    MessageSid: Optional[str] = Form(None)
):
    try:
        # Ya estás capturando From, Body y To directamente como argumentos de la función FastAPI.
        # No necesitas el diccionario message_data si vas a pasar los argumentos directamente.

        logger.info(f"Datos del webhook: From={From}, To={To}, Body={Body}, MessageSid={MessageSid}")

        # Llama a handle_incoming_message con los argumentos correctos
        # Asegúrate de limpiar el prefijo "whatsapp:" de los números de teléfono
        user_phone_number = From.replace("whatsapp:", "")
        company_whatsapp_number = To.replace("whatsapp:", "")
        message_text = Body
        message_sid = MessageSid # Pasar el MessageSid directamente

        twilio_response_xml = await handle_incoming_message(
            user_phone_number=user_phone_number,
            company_whatsapp_number=company_whatsapp_number,
            message_text=message_text,
            message_sid=message_sid # Pasa el SID al handler
        )

        # Retorna el TwilioML como PlainTextResponse
        return PlainTextResponse(content=twilio_response_xml, media_type="text/xml")

    except Exception as e:
        logger.error(f"Webhook error: {e}", exc_info=True)
        # En caso de error, siempre devuelve un TwilioML válido.
        error_twiml = MessagingResponse()
        error_twiml.message("Lo siento, algo salió mal al procesar tu solicitud. Por favor, inténtalo de nuevo más tarde.")
        return PlainTextResponse(content=str(error_twiml), media_type="text/xml")