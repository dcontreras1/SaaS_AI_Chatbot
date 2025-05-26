import os
import logging
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL")

# Asegurarse de que DATABASE_URL esté definida en tus variables de entorno Docker o .env
if not DATABASE_URL:
    raise ValueError("DATABASE_URL no está configurada en las variables de entorno.")

engine = create_async_engine(DATABASE_URL, echo=True, future=True)

Base = declarative_base()

SessionLocal = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

@asynccontextmanager
async def get_db_session():
    async with SessionLocal() as session:
        try:
            logger.info(f"DEBUG DB: Sesión CREADA (ID: {id(session)})") # <-- AÑADIR
            yield session
        except:
            await session.rollback()
            raise
        finally:
            logger.info(f"DEBUG DB: Sesión CERRADA (ID: {id(session)})") # <-- AÑADIR
            await session.close()