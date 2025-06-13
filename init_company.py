import asyncio
from dotenv import load_dotenv
import os

dotenv_path = '/home/dcontreras/SaaS_Chatbot_project/.env'
load_dotenv(dotenv_path)

from sqlalchemy.future import select
from db.database import get_db_session
from db.models.company import Company

# Aquí se definen las empresas a registrar (se puede agregar/quitar)
EMPRESAS = [
    {
        "name": "Clínica Odontológica Sonríe",
        "industry": "Salud",
        "catalog_url": None,
        "schedule": "Lunes a Viernes, 8am a 8pm",
        "company_number_env": "TWILIO_PHONE_NUMBER",
        "whatsapp_token_env": "TWILIO_AUTH_TOKEN",
        "api_key": "test-api-key-123",
        "calendar_email": "contrerasdaniel2984@gmail.com",
        "company_metadata": {
            "appointment_slots": [
                {
                    "key": "doctor",
                    "label": "doctor",
                    "type": "string",
                    "required": True,
                    "options": ["María Martinez", "Eduardo López"]
                },
                {
                    "key": "name",
                    "label": "nombre",
                    "type": "string",
                    "required": True
                },
                {
                    "key": "datetime",
                    "label": "fecha y hora",
                    "type": "datetime",
                    "required": True
                }
            ],
            "confirmation_message": "Perfecto, {name}, tu cita con {doctor} fue agendada para el {datetime}.",
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
    },
    {
        "name": "Peluquería Glamour",
        "industry": "Belleza",
        "catalog_url": None,
        "schedule": "Martes a Sábado, 10am a 7pm",
        "company_number_env": "PELUQUERIA_PHONE_NUMBER",
        "whatsapp_token_env": "PELUQUERIA_AUTH_TOKEN",
        "api_key": "glamour-api-key-2025",
        "calendar_email": "reservas@peluqueriaglamour.com",
        "company_metadata": {
            "appointment_slots": [
                {
                    "key": "stylist",
                    "label": "estilista",
                    "type": "string",
                    "required": True,
                    "options": ["Ana Rivera", "Carlos Pérez"]
                },
                {
                    "key": "name",
                    "label": "nombre",
                    "type": "string",
                    "required": True
                },
                {
                    "key": "datetime",
                    "label": "fecha y hora",
                    "type": "datetime",
                    "required": True
                }
            ],
            "confirmation_message": "¡Listo! Tu cita con {stylist} para {name} es el {datetime}.",
            "stylists": [
                {
                    "name": "Ana Rivera",
                    "specialty": "Colorista"
                },
                {
                    "name": "Carlos Pérez",
                    "specialty": "Barbería"
                }
            ]
        }
    },
    # Agrega más empresas aquí copiando el mismo formato
]

async def create_companies():
    async with get_db_session() as session:
        for empresa in EMPRESAS:
            # Obtiene los valores de las variables de entorno
            company_number_raw = os.getenv(empresa["company_number_env"])
            if not company_number_raw:
                print(f"Error: {empresa['company_number_env']} no está configurado en las variables de entorno para {empresa['name']}.")
                continue
            cleaned_company_number = company_number_raw.replace("whatsapp:", "")
            whatsapp_token = os.getenv(empresa["whatsapp_token_env"])
            if not whatsapp_token:
                print(f"Error: {empresa['whatsapp_token_env']} no está configurado en las variables de entorno para {empresa['name']}.")
                continue

            # Verifica si ya existe la empresa
            result = await session.execute(
                select(Company).where(Company.company_number == cleaned_company_number)
            )
            existing = result.scalars().first()

            if existing:
                print(f"La empresa '{empresa['name']}' ya está registrada.")
                modified = False
                if existing.calendar_email != empresa["calendar_email"]:
                    existing.calendar_email = empresa["calendar_email"]
                    modified = True
                if existing.company_metadata != empresa["company_metadata"]:
                    existing.company_metadata = empresa["company_metadata"]
                    modified = True
                if modified:
                    await session.commit()
                    print(f"Datos actualizados para '{empresa['name']}'.")
                continue

            new_company = Company(
                name=empresa["name"],
                industry=empresa["industry"],
                catalog_url=empresa["catalog_url"],
                schedule=empresa["schedule"],
                company_number=cleaned_company_number,
                whatsapp_token=whatsapp_token,
                api_key=empresa["api_key"],
                calendar_email=empresa["calendar_email"],
                company_metadata=empresa["company_metadata"]
            )

            session.add(new_company)
            await session.commit()
            print(f"Empresa '{empresa['name']}' creada con éxito con número '{new_company.company_number}'.")

if __name__ == "__main__":
    asyncio.run(create_companies())