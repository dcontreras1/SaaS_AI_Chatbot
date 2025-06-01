import os
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

def build_prompt(
    user_message: str,
    company: Dict[str, Any],
    chat_history: Optional[List[Dict[str, Any]]] = None,
    client_name: Optional[str] = None,
    appointment_datetime: Optional[datetime] = None,
    intent: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Retorna la lista de mensajes (prompt) para enviar a la API de Gemini,
    incluyendo instrucciones del sistema, un historial de chat opcional, el estado de los slots,
    y la intención detectada del usuario.
    """

    system_prompt_parts = [
        f"Eres un asistente virtual para la empresa '{company['name']}'.",
        f"Tu trabajo es responder con claridad, amabilidad y precisión a los clientes por WhatsApp.",
        f"Si el usuario pregunta por catálogo, precios, horarios u otros temas comunes, responde usando la información que te brinda la empresa.",
        f"Si no sabes algo, indica que el equipo humano lo contactará.",
        f"Siempre debes ser conciso y directo en tus respuestas, pero siempre amable.",
        f"",
        f"Información de la empresa:",
        f"- Nombre: {company['name']}",
        f"- Rubro: {company.get('industry', 'No especificado')}",
        f"- Catálogo: {company.get('catalog_url', 'No proporcionado')}",
        f"- Horarios: {company.get('schedule', 'No especificado')}",
        f"",
        f"Si el usuario pregunta sobre agendar una cita:",
        f"  - Necesitarás su **nombre completo** y la **fecha y hora** de la cita.",
        f"  - El formato preferido para la fecha y hora es DD/MM/YY HH:MM (ejemplo: 02/06/25 16:00).",
        f"  - Una vez que tengas ambos, confirma la información.",
        f"  - Si ya tienes el nombre o la fecha/hora, **no vuelvas a pedir esa información**."
    ]

    # 🔍 Incorporar información de la intención detectada
    if intent:
        intent_descriptions = {
            "ask_general": "El usuario está preguntando por los horarios de atención.",
            "ask_catalog": "El usuario quiere conocer el catálogo de productos o servicios.",
            "ask_price": "El usuario desea saber los precios.",
            "ask_location": "El usuario solicita la ubicación o dirección.",
            "ask_bot_identity": "El usuario pregunta por tu identidad como asistente virtual.",
            "ask_bot_capabilities": "El usuario quiere saber qué puedes hacer.",
            "greet": "El usuario ha saludado.",
            "farewell": "El usuario se despide.",
            "schedule_appointment": "El usuario quiere agendar una cita.",
            "cancel_appointment": "El usuario desea cancelar una cita.",
        }

        description = intent_descriptions.get(intent)
        if description:
            system_prompt_parts.append(f"\nContexto detectado: {description}")

    # 🔎 Añadir slots si ya hay nombre o fecha/hora de cita
    if client_name:
        system_prompt_parts.append(f"Información de cita actual recopilada: Nombre del cliente: {client_name}.")
    if appointment_datetime:
        if appointment_datetime.tzinfo is None:
            appointment_datetime_display = appointment_datetime.isoformat() + 'Z'
        else:
            appointment_datetime_display = appointment_datetime.isoformat()
        system_prompt_parts.append(f"Información de cita actual recopilada: Fecha y hora de la cita: {appointment_datetime_display}.")

    # Construcción final del mensaje
    system_prompt_content = "\n".join(system_prompt_parts)

    messages_to_gemini = []

    if chat_history:
        if chat_history[0]["role"] == "user":
            combined_first_user_message = f"{system_prompt_content.strip()}\n\n{chat_history[0]['parts'][0]['text'].strip()}"
            messages_to_gemini.append({"role": "user", "parts": [{"text": combined_first_user_message}]})
            messages_to_gemini.extend(chat_history[1:])
        else:
            messages_to_gemini.append({"role": "user", "parts": [{"text": system_prompt_content}]})
            messages_to_gemini.extend(chat_history)
    else:
        messages_to_gemini.append({
            "role": "user",
            "parts": [{"text": f"{system_prompt_content.strip()}\n\n{user_message.strip()}"}]
        })
        return messages_to_gemini

    # Asegurarse de incluir el mensaje actual del usuario al final
    if not messages_to_gemini or messages_to_gemini[-1]["parts"][0]["text"].strip() != user_message.strip():
        messages_to_gemini.append({"role": "user", "parts": [{"text": user_message.strip()}]})

    return messages_to_gemini
