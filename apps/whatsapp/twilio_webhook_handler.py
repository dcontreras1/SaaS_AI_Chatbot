import os
import logging
from fastapi import APIRouter, Form
from fastapi.responses import PlainTextResponse
from dotenv import load_dotenv

from apps.whatsapp.message_handler import handle_incoming_message
from twilio.twiml.messaging_response import MessagingResponse

load_dotenv()
logger = logging.getLogger(__name__)

webhook_router = APIRouter()

@webhook_router.post("/webhook", response_class=PlainTextResponse)
async def twilio_webhook(
    From: str = Form(...),
    Body: str = Form(...),
    To: str = Form(...)
):
    try:
        message_data = {
            "From": From,
            "Body": Body,
            "To": To
        }

        logger.info(f"Datos del webhook: From={From}, To={To}, Body={Body}")

        # Llama a handle_incoming_message y espera la respuesta TwilioML
        twilio_response_xml = await handle_incoming_message(message_data)

        # Retorna el TwilioML como PlainTextResponse
        return PlainTextResponse(content=twilio_response_xml, media_type="text/xml")

    except Exception as e:
        logger.error(f"Webhook error: {e}", exc_info=True)
        # En caso de error, siempre devuelve un TwilioML válido.
        error_twiml = MessagingResponse()
        error_twiml.message("Lo siento, algo salió mal al procesar tu solicitud. Por favor, inténtalo de nuevo más tarde.")
        return PlainTextResponse(content=str(error_twiml), media_type="text/xml")