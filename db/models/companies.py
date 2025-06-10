from db.models.company import Company
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

async def get_company_by_number(phone_number_id: str, db_session: AsyncSession) -> Company:
    """
    Obtiene una compañía por su número de WhatsApp.
    Asume que la sesión de DB es manejada por el llamador (e.g., FastAPI's Depends).
    """
    result = await db_session.execute(select(Company).where(Company.company_number == phone_number_id))
    return result.scalars().first()