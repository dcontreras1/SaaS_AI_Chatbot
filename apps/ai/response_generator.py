import json
import logging
from apps.ai.gemini_client import get_api_response
from db.database import get_messages_by_session_id

logger = logging.getLogger(__name__)

async def generate_response(
    user_message,
    company,
    current_intent,
    session_id,
    session_data=None,
    instructions=None
):
    """
    Genera una respuesta usando el historial real almacenado en la base de datos y el modelo Gemini.
    Puede recibir contexto adicional en session_data.
    El parámetro 'instructions' permite controlar el tono y la objetividad de la respuesta.
    """
    try:
        # 1. Obtener historial desde la base de datos (formato: [{"direction": "in"/"out", "body": "..."}, ...])
        raw_messages = await get_messages_by_session_id(session_id)

        # 2. Convertir historial al formato Gemini: [{"role": "user"/"model", "parts": [{"text": "..."}]}, ...]
        message_history = []
        for msg in raw_messages:
            role = "user" if msg["direction"] == "in" else "model"
            message_history.append({"role": role, "parts": [{"text": msg["body"]}]})

        # 3. Agregar el nuevo mensaje del usuario (todavía no guardado en DB)
        user_message_text = f"Empresa: {company['name']}. Intención: {current_intent}. Mensaje: {user_message}"
        if session_data:
            user_message_text = f"Contexto conversacional: {session_data}\n{user_message_text}"

        if instructions:
            user_message_text = f"{instructions}\n{user_message_text}"

        message_history.append({
            "role": "user",
            "parts": [{"text": user_message_text}]
        })

        # 4. Llamar a Gemini usando el historial completo
        response_text = await get_api_response(message_history)

        # 5. Parsear respuesta como JSON si es posible, sino devolver texto plano
        try:
            result = json.loads(response_text)
            return result
        except Exception:
            logger.warning("La respuesta de Gemini no era JSON válido. Se usará texto plano.")
            return {"text": response_text, "conversation_state": "in_progress"}

    except Exception as e:
        logger.error(f"Error en generate_response: {e}", exc_info=True)
        return {"text": "Lo siento, ocurrió un error generando la respuesta.", "conversation_state": "error"}

async def gemini_simple_prompt(prompt: str) -> str:
    """
    Envía un prompt simple a Gemini y retorna solo el texto.
    Útil para extracción de intención, fechas, etc.
    """
    try:
        response_text = await get_api_response([{"role": "user", "parts": [{"text": prompt}]}])
        return response_text
    except Exception as e:
        logger.error(f"Error en gemini_simple_prompt: {e}", exc_info=True)
        return "unknown"