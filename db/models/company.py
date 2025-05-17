from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import relationship
from db.models.base import Base

class Company(Base):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    industry = Column(String, nullable=True)
    catalog_url = Column(String, nullable=True)
    schedule = Column(String, nullable=True)
    whatsapp_phone_number_id = Column(String, nullable=False, unique=True)
    whatsapp_token = Column(String, nullable=False)
    api_key = Column(String, nullable=False, unique=True)

    appointments = relationship("Appointment", back_populates="company", cascade="all, delete")
    clients = relationship("Client", back_populates="company")
    messages = relationship("Message", back_populates="company")
    sessions = relationship("Session", back_populates="company")
