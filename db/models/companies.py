from db.models.company import Company
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

async def get_company_by_number(company_number, db_session):
    
    if company_number.startswith('whatsapp:'):
        company_number = company_number.replace('whatsapp:', '')
    result = await db_session.execute(
        select(Company).where(Company.company_number == company_number)
    )
    return result.scalar_one_or_none()