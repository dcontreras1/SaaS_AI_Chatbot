from sqlalchemy import Column, Integer, String, Date
from datetime import date
from db.models.base import Base

class UnknownClient(Base):
    __tablename__ = "unknown_clients"

    id = Column(Integer, primary_key=True, index=True)
    phone_number = Column(String, unique=True, nullable=False)
    first_seen = Column(Date, default=date.today)
