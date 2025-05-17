from db.models import Desconocido, Cita
from db.session import async_session

async def save_unknown_client(phone: str, name: str):
    async with async_session() as session:
        nuevo = Desconocido(phone=phone, name=name)
        session.add(nuevo)
        await session.commit()

async def save_appointment(phone: str, datetime_str: str):
    async with async_session() as session:
        cita = Cita(phone=phone, datetime=datetime_str)
        session.add(cita)
        await session.commit()
