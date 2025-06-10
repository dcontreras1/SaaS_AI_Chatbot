import os
import json
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

def build_prompt(
    user_message: str,
    company: Dict[str, Any],
    chat_history: Optional[List[Dict[str, Any]]] = None,
    session_data: Optional[Dict[str, Any]] = None, # <<-- Asegúrate de que este parámetro esté aquí
    intent: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Retorna la lista de mensajes (prompt) para enviar a la API de Gemini,
    incluyendo instrucciones del sistema, un historial de chat opcional, el estado de los slots,
    y la intención detectada del usuario.
    """

    # Asegurarse de que session_data no es None para evitar errores.
    if session_data is None:
        session_data = {}

    system_prompt_parts = [
        f"Eres un asistente virtual para la empresa '{company['name']}'.",
        f"Tu trabajo es responder con claridad, amabilidad y precisión a los clientes por WhatsApp.",
        f"Si el usuario pregunta por catálogo, precios, horarios u otros temas comunes, responde usando la información que te brinda la empresa.",
        f"Si no sabes algo, indica que el equipo humano lo contactará.",
        f"Siempre debes ser conciso y directo en tus respuestas, pero siempre amable.",
        f"Estás en una conversación continua. Mantén el contexto.",
        f"",
        f"Información de la empresa:",
        f"- Nombre: {company['name']}",
        f"- Rubro: {company.get('industry', 'No especificado')}",
        f"- Horario de atención: {company.get('schedule', 'No disponible')}",
        f"- Enlace al catálogo/servicios: {company.get('catalog_url', 'No disponible')}",
        f"- Número de contacto: {company.get('company_number', 'No disponible')}",
        f"- Correo de calendario: {company.get('calendar_email', 'No disponible')}",
        f"- API Key: {company.get('api_key', 'N/A')}", # No mostrar API Key a usuarios, solo para el contexto del LLM
        f"- Token de WhatsApp: {company.get('whatsapp_token', 'N/A')}", # No mostrar a usuarios
        f"",
        f"Contexto de la conversación actual (datos de sesión): {json.dumps(session_data)}", # Añadir datos de sesión aquí
        f"Intención del usuario detectada: {intent or 'No detectada'}",
        f"",
        f"Instrucciones para la respuesta:",
        f"1. Responde en español.",
        f"2. Si la intención es 'greet', 'farewell', 'ask_schedule', 'ask_catalog', 'ask_address', 'ask_phone', 'ask_email', 'ask_bot_identity', 'ask_bot_capabilities', prioriza el uso de la información de la empresa.",
        f"3. Si la intención es 'schedule_appointment' o 'cancel_appointment', no intentes realizar la acción aquí. El sistema la manejará. Solo responde con un mensaje de bienvenida o un reconocimiento.",
        f"4. Si la intención es 'provide_contact', agradece al usuario por la información y confirma que un agente se pondrá en contacto.",
        f"5. Para 'fallback' o si no hay información suficiente, pide más detalles o sugiere opciones.",
        f"6. Si la respuesta final se puede estructurar como JSON (por ejemplo, para indicar un cambio de estado en la conversación), hazlo. Ejemplo: {{ \"text\": \"Hola, ¿en qué puedo ayudarte?\", \"conversation_state\": \"initial\" }}",
        f"7. Si la respuesta es solo texto, que sea directamente el texto. No uses JSON.",
        f"8. No menciones tu API Key o token de WhatsApp al usuario final.",
        f"9. La hora actual es: {datetime.now(timezone.utc).isoformat()} (UTC). Tenla en cuenta para referencias relativas al tiempo.",
        f"10. **Formato de respuesta si es JSON**: {{ \"text\": \"mensaje para el usuario\", \"conversation_state\": \"nuevo_estado\" }}",
        f"    Posibles estados de conversación: \"initial\", \"in_progress\", \"waiting_for_name\", \"waiting_for_datetime\", \"waiting_for_cancellation_confirmation\", \"completed\", \"error\"."
        f"    **Si no hay un cambio de estado significativo, no incluyas 'conversation_state'.**"
        f"    **Si NO es un JSON, responde solo con el texto.**"
    ]

    messages_to_gemini = []

    # El primer mensaje debe contener las instrucciones del sistema.
    # Si hay historial de chat, el prompt del sistema se añade al primer mensaje del usuario.
    # Si no hay historial, el primer mensaje es el prompt del sistema seguido del mensaje actual del usuario.

    system_prompt_content = "\n".join(system_prompt_parts)

    # Si hay historial de chat, integra el prompt del sistema en el primer mensaje del historial
    if chat_history:
        # El primer mensaje del historial (que debería ser del usuario) se combina con el system prompt
        first_history_message = chat_history[0]
        if first_history_message.get("role") == "user" and first_history_message.get("parts") and first_history_message["parts"][0].get("text"):
            combined_text = f"{system_prompt_content}\n\n{first_history_message['parts'][0]['text']}"
            messages_to_gemini.append({"role": "user", "parts": [{"text": combined_text}]})
            messages_to_gemini.extend(chat_history[1:]) # Añadir el resto del historial
        else:
            # Si el primer mensaje no es del usuario o no tiene texto, añadir el system prompt separado
            messages_to_gemini.append({"role": "user", "parts": [{"text": system_prompt_content}]})
            messages_to_gemini.extend(chat_history)
    else:
        # Si no hay historial, el primer mensaje es el system prompt
        messages_to_gemini.append({"role": "user", "parts": [{"text": system_prompt_content}]})

    # Finalmente, añade el mensaje actual del usuario como el último mensaje.
    # Asegúrate de que no se duplique si ya fue combinado.
    last_message_text = user_message.strip()
    
    # Simple check para evitar duplicar el mensaje del usuario si ya fue parte del primer mensaje combinado
    # Esto es una simplificación, podrías necesitar una lógica más robusta
    if not messages_to_gemini or (messages_to_gemini[-1].get("role") == "user" and not messages_to_gemini[-1]["parts"][0]["text"].endswith(last_message_text)):
         messages_to_gemini.append({"role": "user", "parts": [{"text": last_message_text}]})

    return messages_to_gemini