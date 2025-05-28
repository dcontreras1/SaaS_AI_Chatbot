def build_prompt(user_message: str, company: dict) -> list:
    """
    Retorna la lista de mensajes (prompt) para enviar a la API de Gemini.
    `company` puede tener información como: nombre, productos, políticas, etc.
    
    Nota: Gemini no tiene un rol 'system' explícito. El system prompt se integra
    al inicio del primer mensaje del usuario.
    """
    system_instructions = f"""
Eres un asistente virtual para la empresa '{company['name']}'.
Tu trabajo es responder con claridad, amabilidad y precisión a los clientes por WhatsApp.
Si el usuario pregunta por catálogo, precios, horarios u otros temas comunes, responde usando la información que te brinda la empresa.
Si no sabes algo, indica que el equipo humano lo contactará.

Información de la empresa:
- Nombre: {company['name']}
- Rubro: {company.get('industry', 'No especificado')}
- Catálogo: {company.get('catalog_url', 'No proporcionado')}
- Horarios: {company.get('schedule', 'No especificado')}
"""

    # Integra las instrucciones del sistema al inicio del mensaje del usuario
    # para que Gemini lo procese como parte del contexto del usuario.
    full_user_prompt = f"{system_instructions.strip()}\n\n{user_message.strip()}"

    return [
        {"role": "user", "parts": [full_user_prompt]}
    ]