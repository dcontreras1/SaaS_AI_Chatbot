import asyncio
from dotenv import load_dotenv
import os

dotenv_path = '/home/dcontreras/SaaS_Chatbot_project/.env'
load_dotenv(dotenv_path)

from sqlalchemy.future import select
from db.database import get_db_session
from db.models.company import Company

async def create_test_company():
    async with get_db_session() as session:
        twilio_phone_number_raw = os.getenv("TWILIO_PHONE_NUMBER")
        if not twilio_phone_number_raw:
            print("Error: TWILIO_PHONE_NUMBER no está configurado en las variables de entorno.")
            return

        cleaned_company_number = twilio_phone_number_raw.replace("whatsapp:", "")

        result = await session.execute(
            select(Company).where(Company.company_number == cleaned_company_number)
        )
        existing = result.scalars().first()

        # Metadata con doctores ficticios como información clave
        metadata = {
            "appointment_slots": [
                {
                    "key": "doctor",
                    "label": "doctor",
                    "type": "string",
                    "required": True,
                    "options": ["María Martinez", "Eduardo López"]
                },
                {
                    "key": "datetime",
                    "label": "fecha y hora",
                    "type": "datetime",
                    "required": True
                }
            ],
            "confirmation_message": "Perfecto, tu cita fue agendada para {datetime} con {doctor}.",
            # Información clave adicional (doctores de la clínica)
            "doctors": [
                {
                    "name": "María Martinez",
                    "specialty": "Ortodoncia"
                },
                {
                    "name": "Eduardo López",
                    "specialty": "Odontología general"
                }
            ]
        }

        if existing:
            print(f"La empresa con número '{cleaned_company_number}' ya está registrada.")
            modified = False
            if existing.calendar_email != "contrerasdaniel2984@gmail.com":
                existing.calendar_email = "contrerasdaniel2984@gmail.com"
                modified = True
            if existing.metadata != metadata:
                existing.metadata = metadata
                modified = True
            if modified:
                await session.commit()
                print("Datos de la empresa actualizados (email/metadata).")
            return

        new_company = Company(
            name="Clínica Odontológica Sonríe",
            industry="Salud",
            catalog_url=None,
            schedule="Lunes a Viernes, 8am a 8pm",
            company_number=cleaned_company_number,
            whatsapp_token=os.getenv("TWILIO_AUTH_TOKEN"),
            api_key="test-api-key-123",
            calendar_email="contrerasdaniel2984@gmail.com",
            metadata=metadata
        )

        session.add(new_company)
        await session.commit()
        print(f"Empresa de prueba creada con éxito con número '{new_company.company_number}' y email de calendario.")

if __name__ == "__main__":
    asyncio.run(create_test_company())