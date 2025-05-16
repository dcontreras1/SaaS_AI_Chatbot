from sqlalchemy import Column, Integer, String, Text
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

class Company(Base):
    __tablename__= "companies"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    industry = Column(String, nullable=True)
    catalog_url = Column(String, nullable=True)
    schedule = Column(String, nullable=True)
    whatsapp_phone_number_id = Column(String, nullable=False, unique=True)
    whatsapp_token = Column(String, nullable=False)
    api_key = Column(String, nullable=False, unique=True) #Para autenticación