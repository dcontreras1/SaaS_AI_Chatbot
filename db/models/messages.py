# db/models/messages.py
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from db.database import Base

class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    message_sid = Column(String, unique=True, nullable=False)
    body = Column(String, nullable=False)
    sender_phone_number = Column(String, nullable=False)
    direction = Column(String, nullable=False)
    timestamp = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)

    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    company = relationship("Company", back_populates="messages")

    chat_session_id = Column(Integer, ForeignKey("chat_sessions.id"), nullable=True)
    chat_session = relationship("ChatSession", back_populates="messages")