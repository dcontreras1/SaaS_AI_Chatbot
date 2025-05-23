from fastapi import APIRouter, Form, Request, HTTPException, Depends
from fastapi.responses import PlainTextResponse
from apps.whatsapp.message_handler import handle_incoming_message
from apps.whatsapp.whatsapp_api import verify_twilio_credentials
from twilio.twiml.messaging_response import MessagingResponse
from db.database import get_db_session
from sqlalchemy.ext.asyncio import AsyncSession
import logging
import json
import traceback

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

webhook_router = APIRouter()

@webhook_router.post("/webhook", response_class=PlainTextResponse)
async def twilio_webhook(
    request: Request,
    From: str = Form(...),
    Body: str = Form(...),
    To: str = Form(...),
    db_session: AsyncSession = Depends(get_db_session)
):
    twiml_response = MessagingResponse() 

    try:
        # Añadir log para verificar la sesión inyectada
        logger.info(f"DEBUG WEBHOOK: Sesión INYECTADA por FastAPI (ID: {id(db_session)})")

        # Verificar conexión con Twilio
        if not verify_twilio_credentials():
            logger.error("Error: Credenciales de Twilio no configuradas")
            twiml_response.message("Lo siento, hay un problema de configuración.")
            return str(twiml_response)
        
        logger.info("=== Datos del Webhook ===")
        logger.info(f"From: {From}")
        logger.info(f"To: {To}")
        logger.info(f"Body: {Body}")

        # Verificar formato del número
        if not From.startswith('whatsapp:'):
            From = f'whatsapp:{From}'
        if not To.startswith('whatsapp:'):
            To = f'whatsapp:{To}'

        # Crear diccionario con los datos del mensaje
        message_data = {
            "From": From,
            "Body": Body,
            "To": To
        }
        
        # Procesar el mensaje, pasando la sesión de base de datos inyectada
        result = await handle_incoming_message(message_data, db_session) 
        
        if result.get("success", False):
            # Si el procesamiento fue exitoso, devolver un TwiML vacío
            return str(twiml_response)
        else:
            error_msg = result.get('error', 'Hubo un error al procesar tu mensaje.')
            logger.error(f"Error procesando mensaje en handle_incoming_message: {error_msg}")
            # Si hay un error interno, se puede enviar un mensaje al usuario
            twiml_response.message("Lo siento, no pude procesar tu solicitud en este momento. Por favor, inténtalo de nuevo más tarde.")
            return str(twiml_response)

    except Exception as e:
        logger.error(f"Error general en webhook: {str(e)}")
        logger.error(f"Traceback completo: {traceback.format_exc()}")
        # En caso de una excepción inesperada, envía un mensaje de error al usuario
        twiml_response.message("Ha ocurrido un error inesperado. Por favor, inténtalo más tarde.")
        return str(twiml_response)

@webhook_router.get("/webhook")
async def verify_webhook(request: Request):
    """Endpoint para verificación de Twilio."""
    try:
        # Verificar conexión con Twilio
        if not verify_twilio_credentials():
            logger.error("Error: Credenciales de Twilio no configuradas")
            raise HTTPException(status_code=500, detail="Error de configuración de Twilio")
        
        # Log de headers en la verificación
        headers = dict(request.headers)
        logger.info("=== Headers de verificación ===")
        for header, value in headers.items():
            logger.info(f"{header}: {value}")
            
        return "Webhook está funcionando"
    except Exception as e:
        logger.error(f"Error en verificación: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))