import asyncio
from datetime import datetime, timedelta, timezone
import logging

from sqlalchemy import delete
from db.database import get_db_session
from db.models.messages import Message

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def purge_old_messages(max_age_hours: int = 24):
    """
    Borra mensajes de la base de datos que sean más antiguos que max_age_hours.
    """
    async with get_db_session() as session:
        # Calcula la fecha y hora de corte (ej. 24 horas antes de ahora, en UTC)
        cutoff_datetime_aware = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        cutoff_datetime = cutoff_datetime_aware.replace(tzinfo=None)

        stmt = delete(Message).where(Message.timestamp < cutoff_datetime)

        result = await session.execute(stmt)
        deleted_count = result.rowcount

        await session.commit()

        logger.info(f"Tarea de purga: Se borraron {deleted_count} mensajes más antiguos que {max_age_hours} horas (antes de {cutoff_datetime.isoformat()}).")
        print(f"Tarea de purga: Se borraron {deleted_count} mensajes más antiguos que {max_age_hours} horas.")

async def start_purging_service(interval_seconds: int = 3600, max_age_hours: int = 24):
    logger.info(f"Servicio de purga iniciado: borrará mensajes más antiguos de {max_age_hours}h cada {interval_seconds} segundos.")
    print(f"Servicio de purga iniciado: borrará mensajes más antiguos de {max_age_hours}h cada {interval_seconds} segundos.")

    while True:
        try:
            await purge_old_messages(max_age_hours)
        except Exception as e:
            logger.error(f"Error durante la purga de mensajes: {e}")
            print(f"Error durante la purga de mensajes: {e}")
        await asyncio.sleep(interval_seconds)