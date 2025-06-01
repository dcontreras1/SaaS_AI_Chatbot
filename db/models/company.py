from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import relationship
from db.database import Base

class Company(Base):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    industry = Column(String, nullable=True)
    catalog_url = Column(String, nullable=True)
    schedule = Column(String, nullable=True)
    company_number = Column(String, nullable=False, unique=True)
    whatsapp_token = Column(String, nullable=False)
    api_key = Column(String, nullable=False, unique=True)
    calendar_email = Column(String, nullable=True, unique=True)

    appointments = relationship("Appointment", back_populates="company", cascade="all, delete")
    messages = relationship("Message", back_populates="company")
    chat_sessions = relationship("ChatSession", back_populates="company")