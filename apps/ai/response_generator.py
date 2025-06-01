from apps.ai.prompts import build_prompt
from apps.ai.gemini_client import get_api_response 

async def generate_response(user_message: str, company: dict, current_intent: str = None) -> str:
    """
    Genera una respuesta del modelo de IA basándose en el mensaje del usuario,
    la información de la empresa y la intención detectada.

    Args:
        user_message (str): El mensaje del usuario.
        company (dict): Información de la empresa (ej. horario, catálogo).
        current_intent (str, optional): La intención del usuario, si está disponible.

    Returns:
        str: La respuesta generada por el modelo de IA.
    """
    messages = build_prompt(user_message, company, intent=current_intent)
    response = await get_api_response(messages)
    return response
