import os
import json
import httpx

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
# Usando explicitly el modelo "gemini-1.5-flash-latest"
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-latest:generateContent"

async def call_gemini_api(prompt: str) -> str:
    """
    Realiza una llamada a la API de Gemini usando el modelo gemini-1.5-flash-latest.
    """
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY no está configurada en el entorno.")

    headers = {
        "Content-Type": "application/json"
    }
    # Gemini espera el prompt en el campo 'contents', como lista de mensajes.
    data = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": prompt}]
            }
        ]
    }
    params = {"key": GEMINI_API_KEY}

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            GEMINI_API_URL,
            headers=headers,
            params=params,
            data=json.dumps(data)
        )
        response.raise_for_status()
        response_json = response.json()
        # Gemini responde con text en: response_json['candidates'][0]['content']['parts'][0]['text']
        try:
            return response_json['candidates'][0]['content']['parts'][0]['text']
        except Exception:
            return str(response_json)

async def generate_response(user_message, company, current_intent, session_data):
    context = f"""
    Conversación previa: {session_data}
    Usuario: {user_message}
    Empresa: {company['name']}
    Intención detectada: {current_intent}
    """
    prompt = context + """
    Instrucciones:
    - Si detectas que es el primer mensaje del usuario o un saludo, responde con "conversation_state": "started".
    - Si detectas que la conversación está finalizando (despedida, cierre), responde con "conversation_state": "ended".
    - Si es parte de una conversación en progreso, responde con "conversation_state": "in_progress".
    - Junto a esto, entrega la respuesta natural al usuario en el campo "text".

    Responde en formato JSON. Ejemplo:
    {"text": "¡Hola! ¿En qué puedo ayudarte?", "conversation_state": "started"}
    """
    response = await call_gemini_api(prompt)
    try:
        result = json.loads(response)
        return result
    except Exception:
        return {"text": response, "conversation_state": "in_progress"}