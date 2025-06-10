import logging
from fastapi import APIRouter, Request
from fastapi.responses import Response, PlainTextResponse

from apps.whatsapp.message_handler import handle_incoming_message

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/webhook")
async def twilio_webhook(request: Request):
    try:
        form = await request.form()
        user_phone_number = form.get("From")
        company_whatsapp_number = form.get("To")
        message_text = form.get("Body")
        message_sid = form.get("MessageSid")

        logger.info(
            f"Datos del webhook: From={user_phone_number}, To={company_whatsapp_number}, "
            f"Body={message_text}, MessageSid={message_sid}"
        )

        twilio_response_xml = await handle_incoming_message(
            user_phone_number,
            company_whatsapp_number,
            message_text,
            message_sid,
        )

        return Response(content=twilio_response_xml, media_type="application/xml")
    except Exception as e:
        logger.error(f"Webhook error: {e}", exc_info=True)
        return PlainTextResponse("Error interno en el webhook", status_code=200)

webhook_router = router