from db.models.company import Company
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from db.database import get_db_session

async def get_company_by_number(phone_number_id: str, db: AsyncSession = None):
    if db is None:
        async for session in get_db_session():
            db = session
            break

    result = await db.execute(select(Company).where(Company.company_number == phone_number_id))
    return result.scalars().first()
