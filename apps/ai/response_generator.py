from apps.ai.prompts import build_prompt
from apps.ai.gemini_client import get_api_response 

async def generate_response(user_message: str, company: dict) -> str:
    """
    Genera una respuesta del modelo de IA basándose en el mensaje del usuario y la información de la empresa.

    Args:
        user_message (str): El mensaje del usuario.
        company (dict): Un diccionario con la información de la empresa (ej. horario, catálogo).

    Returns:
        str: La respuesta generada por el modelo de IA.
    """
    messages = build_prompt(user_message, company)
    
    response = await get_api_response(messages)
    
    return response