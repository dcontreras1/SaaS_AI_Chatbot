from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from db.database import Base
import datetime

class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    content = Column(String, nullable=False)
    timestamp = Column(DateTime, default=datetime.datetime.now, nullable=False)
    direction = Column(String, nullable=False)  # "in" o "out"
    sender = Column(String, nullable=True)  # Número del usuario
    company_id = Column(Integer, ForeignKey('companies.id'), nullable=False)

    company = relationship("Company", back_populates="messages")
