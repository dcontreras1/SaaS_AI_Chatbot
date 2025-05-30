from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from db.database import Base
from datetime import datetime, timezone

class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String, unique=True, nullable=False)
    status = Column(String, nullable=False, default="active")
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    started_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    company = relationship("Company", back_populates="sessions")
    messages = relationship("Message", back_populates="chat_session", cascade="all, delete-orphan")