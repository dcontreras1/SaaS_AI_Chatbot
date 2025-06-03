import os
import json
import httpx
import logging
from typing import Dict, Any, List

from apps.ai.prompts import build_prompt

logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-latest:generateContent"

async def call_gemini_api(messages: list) -> str:
    """
    Realiza una llamada a la API de Gemini usando el modelo gemini-1.5-flash-latest.
    Ahora acepta una lista de mensajes formateada para la API de Gemini.
    """
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY no está configurada en el entorno.")

    headers = {
        "Content-Type": "application/json"
    }
    
    data = {
        "contents": messages # <-- Se pasa la lista de mensajes directamente
    }
    params = {"key": GEMINI_API_KEY}

    logger.debug(f"DEBUG GEMINI API: Enviando a Gemini: {json.dumps(data, indent=2)}")

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            GEMINI_API_URL,
            headers=headers,
            params=params,
            data=json.dumps(data)
        )
        response.raise_for_status()
        response_json = response.json()
        logger.debug(f"DEBUG GEMINI API: Respuesta cruda de Gemini: {json.dumps(response_json, indent=2)}")

        try:
            return response_json['candidates'][0]['content']['parts'][0]['text']
        except Exception as e:
            logger.error(f"Error al parsear respuesta de Gemini: {e}. Respuesta completa: {response_json}", exc_info=True)
            return str(response_json)

async def generate_response(user_message: str, company: Dict[str, Any], current_intent: str, session_data: Dict[str, Any], chat_history_for_gemini: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Genera una respuesta del bot utilizando Gemini, basándose en el mensaje del usuario,
    la información de la compañía, la intención detectada y los datos de la sesión.
    Retorna un diccionario con 'text' y 'conversation_state'.
    """
    # Construir el prompt completo utilizando la función build_prompt
    # Pasar todos los datos necesarios para que build_prompt construya un contexto rico
    messages_for_gemini = build_prompt(
        user_message=user_message,
        company=company,
        chat_history=chat_history_for_gemini, # Usar el historial real
        session_data=session_data,
        intent=current_intent
    )

    response_from_gemini_text = await call_gemini_api(messages_for_gemini)

    try:
        # Intentar parsear la respuesta de Gemini como JSON
        # Puede que Gemini envuelva el JSON en ```json...```
        cleaned_response = response_from_gemini_text.strip()
        if cleaned_response.startswith('```json') and cleaned_response.endswith('```'):
            cleaned_response = cleaned_response[7:-3].strip()
        
        result = json.loads(cleaned_response)
        
        # Validar que el resultado tenga las claves esperadas
        if "text" not in result or "conversation_state" not in result:
            logger.warning(f"Respuesta de Gemini no tiene el formato esperado (faltan 'text' o 'conversation_state'). Respuesta: {result}")
            # Fallback a un formato válido si el LLM no sigue las instrucciones
            result = {"text": response_from_gemini_text, "conversation_state": "in_progress"}
            
        return result
    except json.JSONDecodeError as e:
        logger.error(f"Error al decodificar JSON de la respuesta de Gemini: {e}. Respuesta cruda: {response_from_gemini_text}", exc_info=True)
        # Si la respuesta no es un JSON válido, devuélvela como texto con un estado por defecto.
        return {"text": response_from_gemini_text, "conversation_state": "in_progress"}
    except Exception as e:
        logger.error(f"Error inesperado en generate_response: {e}", exc_info=True)
        return {"text": "Lo siento, hubo un error al generar mi respuesta.", "conversation_state": "unknown"}