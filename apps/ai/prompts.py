"""
Prompts utilities for dynamic SaaS AI Chatbot - agendamiento y atención multicliente.

Este módulo genera prompts generales y adaptativos para agendamiento, usando metadata y slots dinámicos según la empresa.
"""

from typing import Dict, Any


def build_appointment_prompt(
    company: Any,
    slots_filled: Dict[str, Any],
    slots_pending: list,
    company_metadata: Dict[str, Any],
) -> str:
    """
    Genera un prompt general para agendamiento, adaptado a los requisitos de cada empresa.

    Args:
        company: Objeto de la empresa (debe tener .name y .schedule)
        slots_filled: Dict con los datos ya obtenidos del usuario, por ejemplo: {"doctor": "María Martinez"}
        slots_pending: Lista de strings con los keys de los slots aún pendientes, por ejemplo: ["datetime"]
        company_metadata: Dict con la metadata de la empresa (ejemplo: appointment_slots, confirmation_message, etc)

    Returns:
        str: Prompt para enviar al modelo LLM.
    """
    return f"""
Eres un asistente virtual encargado de agendar citas para una empresa cliente.
Cada empresa puede requerir información adicional específica para cada cita, según su configuración.

INFORMACIÓN DE LA EMPRESA:
- Nombre: {getattr(company, 'name', 'Desconocido')}
- Horario: {getattr(company, 'schedule', 'No especificado')}
- Metadata para agendamiento (estructura JSON): {company_metadata}

ESTADO DE LA CONVERSACIÓN:
- Datos ya proporcionados por el usuario: {slots_filled}
- Datos que faltan por solicitar: {slots_pending}

INSTRUCCIONES:
1. Pregunta de manera amable y profesional únicamente por los datos que faltan de la lista {slots_pending}.
2. Si hay opciones predefinidas para algún dato (por ejemplo, doctores disponibles), preséntalas para que el usuario elija exactamente una.
3. Cuando tengas toda la información requerida, confirma la cita usando los valores proporcionados y el formato indicado en la metadata (confirmation_message), si lo hay.
4. Si el usuario pide información de horarios o servicios, respóndelo usando la información disponible en los datos de la empresa.
5. No generes preguntas innecesarias ni repitas preguntas ya respondidas.
6. Nunca inventes opciones ni confirmes una cita sin toda la información requerida.
    """.strip()


def build_info_prompt(
    company: Any,
    company_metadata: Dict[str, Any],
    topic: str = "general"
) -> str:
    """
    Prompt para responder preguntas generales sobre la empresa (horarios, servicios, etc).

    Args:
        company: Objeto de la empresa.
        company_metadata: Dict con la metadata de la empresa.
        topic: Tema específico si se desea.

    Returns:
        str: Prompt para el modelo IA.
    """
    return f"""
Eres un asistente virtual para la empresa {getattr(company, 'name', 'Desconocido')}.
Contesta de forma cordial, profesional y usando los datos reales de la empresa.

INFORMACIÓN:
- Horario: {getattr(company, 'schedule', 'No especificado')}
- Servicios destacados: {company_metadata.get('services', 'No especificado')}
- Otros datos relevantes: {company_metadata}

INSTRUCCIÓN:
Responde la pregunta del usuario sobre "{topic}", usando únicamente la información provista.
No inventes información ni pidas datos adicionales si no son necesarios.
    """.strip()