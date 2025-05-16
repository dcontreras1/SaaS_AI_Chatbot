from fastapi import Header, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from db.models.models import Company
from db.database import get_db_session
from sqlalchemy.future import select

async def get_current_company(
    x_api_key: str = Header(...),
    db: AsyncSession = Depends(get_db_session),
) -> Company:
    result = await db.execute(select(Company).where(Company.api_key == x_api_key))
    company = result.scalars().first()
    if not company:
        raise HTTPException(status_code=401, detail="API Key inválida.")
    return company