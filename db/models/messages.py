from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from db.models.base import Base

class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    content = Column(String, nullable=False)
    # Convierte el datetime de UTC-aware a UTC-naive para compatibilidad con TIMESTAMP WITHOUT TIME ZONE
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), nullable=False)
    direction = Column(String, nullable=False)
    sender = Column(String, nullable=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)

    company = relationship("Company", back_populates="messages")