import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

from db.database import engine, Base
from db.models import company, appointment, chat_session, messages

async def init_models():
    async with engine.begin() as conn:
        if os.getenv("ENVIRONMENT", "development") == "development":
            await conn.run_sync(Base.metadata.drop_all)
            print("Todas las tablas eliminadas.")

        await conn.run_sync(Base.metadata.create_all)
        print("Tablas creadas correctamente.")

if __name__ == "__main__":
    asyncio.run(init_models())