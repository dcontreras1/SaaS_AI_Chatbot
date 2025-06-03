import os
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

def build_prompt(
    user_message: str,
    company: Dict[str, Any],
    chat_history: Optional[List[Dict[str, Any]]] = None,
    session_data: Optional[Dict[str, Any]] = None, # <-- Añadir session_data aquí
    intent: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Retorna la lista de mensajes (prompt) para enviar a la API de Gemini,
    incluyendo instrucciones del sistema, un historial de chat opcional, el estado de los slots,
    y la intención detectada del usuario.
    """

    # Asegurarse de que session_data no es None para evitar errores.
    if session_data is None:
        session_data = {}

    system_prompt_parts = [
        f"Eres un asistente virtual para la empresa '{company['name']}'.",
        f"Tu trabajo es responder con claridad, amabilidad y precisión a los clientes por WhatsApp.",
        f"Si el usuario pregunta por catálogo, precios, horarios u otros temas comunes, responde usando la información que te brinda la empresa.",
        f"Si no sabes algo, indica que el equipo humano lo contactará.",
        f"Siempre debes ser conciso y directo en tus respuestas, pero siempre amable.",
        f"Estás en una conversación continua. Mantén el contexto.",
        f"",
        f"Información de la empresa:",
        f"- Nombre: {company['name']}",
        f"- Rubro: {company.get('industry', 'No especificado')}",
        f"- Catálogo: {company.get('catalog_url', 'No proporcionado')}",
        f"- Horarios: {company.get('schedule', 'No especificado')}",
        f"- Número de contacto (WhatsApp): {company.get('company_number', 'No proporcionado')}",
        f"- Email de calendario: {company.get('calendar_email', 'No proporcionado')}",
        f"",
        f"Instrucciones de formato de respuesta JSON (¡IMPORTANTE!):",
        f"Tu respuesta DEBE ser un objeto JSON válido con dos claves: 'text' y 'conversation_state'.",
        f"- 'text': La respuesta en lenguaje natural para el usuario.",
        f"- 'conversation_state': Un string que indica el estado actual de la conversación. Puede ser 'started', 'in_progress', 'awaiting_name', 'awaiting_datetime', 'awaiting_cancel_datetime', 'awaiting_cancel_confirmation', 'ended', 'unknown'.",
        f"",
        f"Estado actual de la sesión (session_data): {session_data}",
        f"Intención detectada: {intent}",
    ]

    # Añadir información de slots si están presentes en session_data
    if session_data.get("client_name"):
        system_prompt_parts.append(f"Información de cita actual recopilada: Nombre del cliente: {session_data['client_name']}.")
    if session_data.get("appointment_datetime"):
        try:
            appointment_datetime_obj = datetime.fromisoformat(session_data["appointment_datetime"])
            # Asegurarse de que el objeto datetime no tiene información de zona horaria si se va a usar isoformat directamente sin 'Z'
            # para evitar problemas con la representación
            if appointment_datetime_obj.tzinfo is None:
                appointment_datetime_display = appointment_datetime_obj.isoformat() + 'Z' # Añadir 'Z' para UTC naive como estándar
            else:
                appointment_datetime_display = appointment_datetime_obj.isoformat()
            system_prompt_parts.append(f"Información de cita actual recopilada: Fecha y hora de la cita: {appointment_datetime_display}.")
        except ValueError:
            logger.warning(f"Fecha/hora de cita inválida en session_data: {session_data['appointment_datetime']}")

    if session_data.get("appointment_datetime_to_cancel"):
        try:
            cancel_datetime_obj = datetime.fromisoformat(session_data["appointment_datetime_to_cancel"])
            if cancel_datetime_obj.tzinfo is None:
                cancel_datetime_display = cancel_datetime_obj.isoformat() + 'Z'
            else:
                cancel_datetime_display = cancel_datetime_obj.isoformat()
            system_prompt_parts.append(f"Información de cancelación recopilada: Fecha y hora de la cita a cancelar: {cancel_datetime_display}.")
        except ValueError:
            logger.warning(f"Fecha/hora de cancelación inválida en session_data: {session_data['appointment_datetime_to_cancel']}")


    # --- Lógica específica para guiar a Gemini según el estado ---
    if intent == "schedule_appointment":
        if session_data.get("waiting_for_name"):
            system_prompt_parts.append("El usuario acaba de pedir una cita y se le ha solicitado su nombre. El mensaje actual del usuario DEBE contener su nombre. Extráelo y confirma que tienes el nombre, luego solicita la fecha y hora de la cita.")
            system_prompt_parts.append("Tu 'conversation_state' debe ser 'awaiting_datetime' después de obtener el nombre.")
        elif session_data.get("waiting_for_datetime"):
            system_prompt_parts.append("El usuario ha proporcionado su nombre y se le ha solicitado la fecha y hora de la cita. El mensaje actual del usuario DEBE contener la fecha y hora. Extráelo y confirma si es posible, luego solicita el número de teléfono.")
            system_prompt_parts.append("Tu 'conversation_state' debe ser 'in_progress' o 'awaiting_phone_number' (si agregas ese slot).")
        # Considera añadir un estado para "awaiting_phone_number" si lo requieres.
        # if session_data.get("waiting_for_phone_number"):
        #     system_prompt_parts.append("El usuario ha proporcionado nombre y fecha/hora, y se le ha solicitado el número de teléfono. El mensaje actual del usuario DEBE contener su número de teléfono. Extráelo y confirma la cita.")
        #     system_prompt_parts.append("Tu 'conversation_state' debe ser 'in_progress' y la cita finalizada.")

    elif intent == "cancel_appointment":
        if session_data.get("waiting_for_cancel_datetime"):
            system_prompt_parts.append("El usuario ha indicado que quiere cancelar una cita y se le ha solicitado la fecha y hora de la cita a cancelar. El mensaje actual del usuario DEBE contener la fecha y hora. Extráela y confirma si es posible, luego pide confirmación de cancelación.")
            system_prompt_parts.append("Tu 'conversation_state' debe ser 'awaiting_cancel_confirmation'.")
        elif session_data.get("waiting_for_cancel_confirmation"):
            system_prompt_parts.append("El usuario ha indicado la cita a cancelar y se le ha pedido confirmación. El mensaje actual del usuario DEBE ser 'sí' o 'no'. Si es 'sí', confirma la cancelación. Si es 'no', aborta la cancelación.")
            system_prompt_parts.append("Tu 'conversation_state' debe ser 'in_progress' o 'ended' si la acción se completa.")


    # Construcción final del mensaje
    system_prompt_content = "\n".join(system_prompt_parts)

    messages_to_gemini = []

    # Combina el prompt del sistema con el primer mensaje del usuario si el historial empieza con el usuario
    if chat_history and chat_history[0]["role"] == "user":
        # Asegúrate de que el primer mensaje del historial tiene 'parts' y 'text'
        first_user_text = chat_history[0].get('parts', [{}])[0].get('text', '')
        combined_first_user_message = f"{system_prompt_content.strip()}\n\n{first_user_text.strip()}"
        messages_to_gemini.append({"role": "user", "parts": [{"text": combined_first_user_message}]})
        messages_to_gemini.extend(chat_history[1:])
    else:
        # Si el historial está vacío o comienza con el modelo, el primer mensaje del usuario se combina con el prompt del sistema
        messages_to_gemini.append({"role": "user", "parts": [{"text": system_prompt_content.strip()}]})
        if chat_history:
            messages_to_gemini.extend(chat_history)

    # Asegurarse de incluir el mensaje actual del usuario al final
    # Solo añadir si no fue ya combinado con el prompt del sistema
    if not messages_to_gemini or messages_to_gemini[-1]["parts"][0]["text"] != f"{system_prompt_content.strip()}\n\n{user_message.strip()}":
        messages_to_gemini.append({"role": "user", "parts": [{"text": user_message.strip()}]})


    logger.debug(f"DEBUG PROMPT: Mensajes finales para Gemini: {messages_to_gemini}")
    return messages_to_gemini