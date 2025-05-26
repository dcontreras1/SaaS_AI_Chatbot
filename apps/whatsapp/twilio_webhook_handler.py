import os
import logging
from fastapi import APIRouter, Form, BackgroundTasks
from fastapi.responses import PlainTextResponse
from dotenv import load_dotenv

from apps.whatsapp.message_handler import handle_incoming_message

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

        # Ejecutamos handle_incoming_message en segundo plano.
        # No necesitamos pasarle la sesión aquí, ya que la manejará internamente.
        # BackgroundTasks es una forma de que FastAPI responda rápido a Twilio
        # mientras el procesamiento pesado ocurre "detrás de escenas".
        background_tasks = BackgroundTasks() # Debemos instanciar BackgroundTasks aquí si no la recibimos como parámetro
        background_tasks.add_task(handle_incoming_message, message_data)

        # Retornamos un "OK" inmediatamente para Twilio.
        return "OK"
    except Exception as e:
        logger.error(f"Webhook error: {e}", exc_info=True) # exc_info=True para el traceback completo
        return "ERROR"