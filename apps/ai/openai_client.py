import os
import openai

openai.api_key = os.getenv("OPENAI_API_KEY")

async def get_api_response(messages: list, model:str = "gpt-3.5-turbo") -> str:
    try:
        response = await openai.ChatCompletion.acreate(
            model=model,
            messages=messages,
            temperature=0.7,
            max_tokens=800,
        )
        return response.choices[0].message["content"].strip()
    except Exception as e:
        print("Error al generar respuesta con OpenAI:", e)
        return "Hubo un error al generar la respuesta, por favor intenta más tarde"