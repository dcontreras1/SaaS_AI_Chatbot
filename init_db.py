import asyncio
import os
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

from db.database import engine
from db.models.company import Base
from db.models import appointment, client, messages, sessions, unknown_clients

async def init_models():
    async with engine.begin() as conn:
        # ⚠️ Precaución: esto borra todas las tablas. Solo usar en desarrollo.
        if os.getenv("ENVIRONMENT", "development") == "development":
            await conn.run_sync(Base.metadata.drop_all)
            print("Todas las tablas eliminadas.")

        await conn.run_sync(Base.metadata.create_all)
        print("Tablas creadas correctamente.")

if __name__ == "__main__":
    asyncio.run(init_models())

