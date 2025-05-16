from sqlalchemy import Column, Integer, String, ForeignKey
from db.database import Base
from sqlalchemy.orm import relationship

class Session(Base):
    __tablename__ = "sessions"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String, unique=True, nullable=False)  # ID único de la sesión
    status = Column(String, nullable=False)  # Estado de la sesión (abierta, cerrada, pendiente, etc.)
    company_id = Column(Integer, ForeignKey('companies.id'), nullable=False)

    company = relationship("Company", back_populates="sessions")
