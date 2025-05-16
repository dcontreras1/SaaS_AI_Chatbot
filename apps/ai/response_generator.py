from apps.ai.prompts import build_prompt
from apps.ai.openai_client import get_api_response

async def generate_response(user_message: str, company: dict) -> str:
    messages = build_prompt(user_message, company)
    response = await get_api_response(messages)
    return response
