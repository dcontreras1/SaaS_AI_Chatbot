from twilio.rest import Client
import os

# Cargar credenciales de Twilio desde variables de entorno
account_sid = os.getenv("TWILIO_ACCOUNT_SID")
auth_token = os.getenv("TWILIO_AUTH_TOKEN")
twilio_whatsapp_number = os.getenv("TWILIO_WHATSAPP_NUMBER")

if not all([account_sid, auth_token, twilio_whatsapp_number]):
    raise EnvironmentError("Faltan variables de entorno de Twilio.")

client = Client(account_sid, auth_token)

def send_whatsapp_message(to_number: str, message: str, from_number: str = None):
    try:
        message = client.messages.create(
            body=message,
            from_=f'whatsapp:{from_number or twilio_whatsapp_number}',
            to=f'whatsapp:{to_number}'
        )
        print(f"Mensaje enviado con SID: {message.sid}")
    except Exception as e:
        print(f"Error al enviar el mensaje: {e}")
