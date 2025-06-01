from datetime import datetime, timezone
from typing import List, Dict, Any
from sqlalchemy.dialects.postgresql import JSONB # <-- Asegúrate de que sea JSONB
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import Base # Asumiendo que esta es la ruta correcta a tu Base

class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id = Column(Integer, primary_key=True, index=True)
    user_phone_number = Column(String, nullable=False, index=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    session_data = Column(JSONB, nullable=False, default={}) # <-- Este es el cambio clave aquí
    status = Column(String, nullable=False, default="active")
    started_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    last_activity = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    company = relationship("Company", back_populates="chat_sessions") 
    messages = relationship("Message", back_populates="chat_session", cascade="all, delete-orphan", order_by="Message.timestamp")

    async def get_formatted_message_history(self, db_session: AsyncSession, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Recupera y formatea el historial de mensajes de esta sesión para el modelo LLM.
        """
        from .messages import Message # Importación local para evitar dependencias circulares

        result = await db_session.execute(
            select(Message)
            .where(Message.chat_session_id == self.id)
            .order_by(Message.timestamp.desc()) 
            .limit(limit)
        )
        raw_messages: List[Message] = result.scalars().all()[::-1] 

        formatted_history = []
        for msg in raw_messages:
            role = "user" if msg.direction == "in" else "model"
            formatted_history.append({"role": role, "parts": [{"text": msg.body}]})
        
        return formatted_history

    def __repr__(self):
        return f"<ChatSession(id={self.id}, user_phone='{self.user_phone_number}', status='{self.status}')>"