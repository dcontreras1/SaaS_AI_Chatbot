async def predict_next_steps(intent: str, entities: dict) -> str:
    """
    Función placeholder para predecir los siguientes pasos
    basado en la intención detectada y las entidades extraídas.
    """
    if intent == "schedule_appointment":
        return "Parece que quieres programar una cita. ¿Necesitas ayuda para elegir una fecha y hora?"
    elif intent == "ask_general":
        return "Si tienes más preguntas generales, estoy aquí para ayudarte."
    elif intent == "provide_contact":
        return "Gracias por compartir tus datos de contacto. Nuestro equipo se pondrá en contacto contigo pronto."
    else:
        return "No estoy seguro de cómo ayudarte con eso. ¿Podrías reformular tu pregunta o indicar lo que buscas?"