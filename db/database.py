import os
import logging
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from contextlib import asynccontextmanager
from sqlalchemy import text

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL no está configurada en las variables de entorno.")

engine = create_async_engine(DATABASE_URL, echo=True, future=True)

Base = declarative_base()

SessionLocal = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

@asynccontextmanager
async def get_db_session():
    async with SessionLocal() as session:
        try:
            logger.info(f"DEBUG DB: Sesión CREADA (ID: {id(session)})")
            yield session
        except Exception as e:
            await session.rollback()
            logger.error(f"DB session rollback debido a error: {e}", exc_info=True)
            raise
        finally:
            logger.info(f"DEBUG DB: Sesión CERRADA (ID: {id(session)})")
            await session.close()

async def get_messages_by_session_id(session_id: str):
    """
    Recupera todos los mensajes asociados a una sesión específica ordenados cronológicamente.
    Usa los campos correctos según el esquema real: direction y body.
    """
    async with get_db_session() as session:
        query = text("""
            SELECT direction, body
            FROM messages
            WHERE chat_session_id = :session_id
            ORDER BY timestamp ASC
        """)
        result = await session.execute(query, {"session_id": session_id})
        rows = result.fetchall()
        return [{"direction": row.direction, "body": row.body} for row in rows]