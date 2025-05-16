from fastapi import APIRouter, Form
from fastapi.responses import PlainTextResponse
from apps.whatsapp.message_handler import handle_incoming_message

webhook_router = APIRouter()

@webhook_router.post("/webhook", response_class=PlainTextResponse)
async def twilio_webhook(
    From: str = Form(...),
    Body: str = Form(...),
    To: str = Form(...)
):
    try:
        message = {
            "From": From,
            "Body": Body,
            "To": To
        }
        await handle_incoming_message(message)
        return "OK"
    except Exception as e:
        print("Webhook error:", e)
        return "ERROR"
