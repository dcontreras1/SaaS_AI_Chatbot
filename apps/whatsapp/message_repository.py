# apps/whatsapp/message_repository.py
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any

from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.messages import Message

logger = logging.getLogger(__name__)

async def add_message(
    db_session: AsyncSession,
    message_sid: str,
    body: str,
    direction: str,
    sender_phone_number: str,
    company_id: int,
    chat_session_id: int
) -> None:
    logger.info(f"MESSAGE_REPO: Añadiendo mensaje - SID: {message_sid}, Dir: {direction}, Body: '{body[:70]}'")
    try:
        new_message = Message(
            message_sid=message_sid,
            body=body,
            direction=direction,
            sender_phone_number=sender_phone_number,
            company_id=company_id,
            chat_session_id=chat_session_id,
            timestamp=datetime.now(timezone.utc).replace(tzinfo=None) 
        )
        db_session.add(new_message)
    except Exception as e:
        logger.error(f"MESSAGE_REPO: Error al añadir mensaje: {e}", exc_info=True)
        raise

async def get_message_history(db_session: AsyncSession, chat_session_id: int, limit: int = 10) -> List[Dict[str, Any]]:
    logger.info(f"MESSAGE_REPO: Obteniendo historial para chat_session_id={chat_session_id}, limit={limit}")
    try:
        result = await db_session.execute(
            select(Message)
            .where(Message.chat_session_id == chat_session_id)
            .order_by(desc(Message.timestamp))
            .limit(limit)
        )
        messages = result.scalars().all()

        formatted_history = []
        for msg in reversed(messages): 
            role = "user" if msg.direction == "in" else "model"
            formatted_history.append({"role": role, "parts": [{"text": msg.body}]})

        logger.info(f"MESSAGE_REPO: Historial obtenido para chat_session_id={chat_session_id}: {len(formatted_history)} mensajes.")
        return formatted_history
    except Exception as e:
        logger.error(f"MESSAGE_REPO: Error al obtener historial de mensajes: {e}", exc_info=True)
        raise