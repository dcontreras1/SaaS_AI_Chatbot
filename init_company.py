import asyncio
from dotenv import load_dotenv
import os

from sqlalchemy.future import select
from db.database import get_db_session
from db.models.company import Company
from db.models.client import Client
from db.models.appointment import Appointment

load_dotenv()  # Cargar .env

async def create_test_company():
    async for session in get_db_session():
        # Verifica si ya existe
        result = await session.execute(
            select(Company).where(Company.company_number == os.getenv("TWILIO_PHONE_NUMBER"))
        )
        existing = result.scalars().first()

        if existing:
            print("La empresa ya está registrada.")
            return

        new_company = Company(
            name="Empresa de Prueba",
            industry="Servicios",
            catalog_url=None,
            schedule="Lunes a Viernes, 9am a 6pm",
            company_number=os.getenv("TWILIO_PHONE_NUMBER"),
            whatsapp_token=os.getenv("TWILIO_AUTH_TOKEN"),
            api_key="test-api-key-123"
        )

        session.add(new_company)
        await session.commit()
        print("Empresa de prueba creada con éxito.")

if __name__ == "__main__":
    asyncio.run(create_test_company())
