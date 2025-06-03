import asyncio
from dotenv import load_dotenv
import os

# Especifica la ruta completa al archivo .env
# Esto asegura que dotenv lo encuentre, sin importar desde dónde ejecutes el script.
dotenv_path = '/home/dcontreras/SaaS_Chatbot_project/.env'
load_dotenv(dotenv_path)

from sqlalchemy.future import select
from db.database import get_db_session
from db.models.company import Company
from db.models.appointment import Appointment # Asegúrate de que esta importación sea necesaria o si la eliminaste

async def create_test_company():
    async with get_db_session() as session:
        # Obtener el número de teléfono de la variable de entorno
        twilio_phone_number_raw = os.getenv("TWILIO_PHONE_NUMBER")
        if not twilio_phone_number_raw:
            print("Error: TWILIO_PHONE_NUMBER no está configurado en las variables de entorno.")
            return

        # --- CAMBIO CLAVE AQUÍ: Limpiar el prefijo "whatsapp:" ---
        # Asegurarse de que el número se guarde en la DB sin el prefijo
        cleaned_company_number = twilio_phone_number_raw.replace("whatsapp:", "")
        # --------------------------------------------------------

        # Verifica si ya existe una compañía con este número limpio
        result = await session.execute(
            select(Company).where(Company.company_number == cleaned_company_number)
        )
        existing = result.scalars().first()

        if existing:
            print(f"La empresa con número '{cleaned_company_number}' ya está registrada.")
            # Opcional: Actualizar el email si ya existe y es diferente
            if existing.calendar_email != "contrerasdaniel2984@gmail.com":
                existing.calendar_email = "contrerasdaniel2984@gmail.com"
                await session.commit()
                print("Email de calendario actualizado para la empresa existente.")
            return

        new_company = Company(
            name="Empresa de Prueba",
            industry="Servicios",
            catalog_url=None,
            schedule="Lunes a Viernes, 9am a 6pm",
            company_number=cleaned_company_number, # Usar el número limpio
            whatsapp_token=os.getenv("TWILIO_AUTH_TOKEN"),
            api_key="test-api-key-123",
            calendar_email="contrerasdaniel2984@gmail.com"
        )

        session.add(new_company)
        await session.commit()
        print(f"Empresa de prueba creada con éxito con número '{new_company.company_number}' y email de calendario.")

if __name__ == "__main__":
    asyncio.run(create_test_company())