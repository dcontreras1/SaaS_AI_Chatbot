import google.generativeai as genai
import os
import logging

logger = logging.getLogger(__name__)

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

async def get_api_response(messages: list) -> str:
    """
    Obtiene una respuesta del modelo Gemini de Google AI.

    Args:
        messages: Una lista de diccionarios, donde cada diccionario representa
                  un mensaje en el formato esperado por la API de Gemini (role, parts).
    Returns:
        La respuesta de texto del modelo.
    """
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')

        if not messages:
            logger.warning("Lista de mensajes vacía para get_api_response.")
            return "Lo siento, no recibí ningún mensaje para procesar."

        if not messages[-1].get("parts"):
            logger.error(f"El último mensaje en el historial no tiene la clave 'parts': {messages[-1]}")
            return "Lo siento, hubo un problema interno al entender tu último mensaje."

        last_user_message_parts = messages[-1]["parts"]
        chat_history = messages[:-1]

        chat_session = model.start_chat(history=chat_history)

        response = chat_session.send_message(last_user_message_parts)

        return response.text

    except Exception as e:
        logger.error(f"Error al generar respuesta con Gemini: {e}", exc_info=True)
        return "Lo siento, hubo un problema al procesar tu solicitud con la IA. Por favor, inténtalo de nuevo."