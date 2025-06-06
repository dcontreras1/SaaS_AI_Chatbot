import json
import logging
from apps.ai.gemini_client import get_api_response
from db.database import get_messages_by_session_id

logger = logging.getLogger(__name__)

async def generate_response(user_message, company, current_intent, session_id):
    """
    Genera una respuesta usando el historial real almacenado en la base de datos.
    """

    try:
        # 1. Obtener historial desde la base de datos (formato: [{"sender": "user", "message": "..."}, ...])
        raw_messages = await get_messages_by_session_id(session_id)

        # 2. Convertir historial al formato Gemini: [{"role": "user", "parts": [{"text": "..."}]}, ...]
        message_history = []
        for msg in raw_messages:
            role = "user" if msg["sender"] == "user" else "model"
            message_history.append({"role": role, "parts": [{"text": msg["message"]}]})

        # 3. Agregar el nuevo mensaje del usuario (todavía no guardado en DB)
        message_history.append({
            "role": "user",
            "parts": [{"text": f"Empresa: {company['name']}. Intención: {current_intent}. Mensaje: {user_message}"}]
        })

        # 4. Llamar a Gemini usando el historial completo
        response_text = await get_api_response(message_history)

        # 5. Parsear respuesta como JSON
        try:
            result = json.loads(response_text)
            return result
        except Exception:
            logger.warning("La respuesta de Gemini no era JSON válido. Se usará texto plano.")
            return {"text": response_text, "conversation_state": "in_progress"}

    except Exception as e:
        logger.error(f"Error en generate_response: {e}", exc_info=True)
        return {"text": "Lo siento, ocurrió un error generando la respuesta.", "conversation_state": "error"}
