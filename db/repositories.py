from sqlalchemy.exc import SQLAlchemyError
from db.database import SessionLocal
from db.models import UnknownClient, Appointment
import logging

logger = logging.getLogger(__name__)


async def save_unknown_client(phone: str, name: str) -> bool:
    try:
        async with SessionLocal() as session:
            async with session.begin():
                nuevo = UnknownClient(phone=phone, name=name)
                session.add(nuevo)
        return True
    except SQLAlchemyError as e:
        logger.error(f"Error saving unknown client: {e}")
        return False


async def save_appointment(phone: str, datetime_str: str) -> bool:
    try:
        async with SessionLocal() as session:
            async with session.begin():
                cita = Appointment(phone=phone, datetime=datetime_str)
                session.add(cita)
        return True
    except SQLAlchemyError as e:
        logger.error(f"Error saving appointment: {e}")
        return False
