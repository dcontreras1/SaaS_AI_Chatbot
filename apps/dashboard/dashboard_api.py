from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from db.database import get_db_session
from db.models.company import Company
from apps.auth.auth import get_current_company
import secrets

router = APIRouter()

@router.post("/register")
async def register_company(
    name: str,
    whatsapp_phone_number_id: str,
    whatsapp_token: str,
    industry: str = "",
    catalog_url: str = "",
    schedule: str = "",
    db: AsyncSession = Depends(get_db_session)
):
    # Evitar duplicados
    result = await db.execute(select(Company).where(Company.whatsapp_phone_number_id == whatsapp_phone_number_id))
    if result.scalar():
        return {"error": "Ya existe una empresa con ese número de WhatsApp"}

    api_key = secrets.token_hex(16)

    company = Company(
        name=name,
        whatsapp_phone_number_id=whatsapp_phone_number_id,
        whatsapp_token=whatsapp_token,
        industry=industry,
        catalog_url=catalog_url,
        schedule=schedule,
        api_key=api_key
    )
    db.add(company)
    await db.commit()
    return {"message": "Empresa registrada con éxito", "api_key": api_key}

@router.get("/me")
async def get_company_profile(company: Company = Depends(get_current_company)):
    return {
        "id": company.id,
        "name": company.name,
        "industry": company.industry,
        "catalog_url": company.catalog_url,
        "schedule": company.schedule,
        "whatsapp_phone_number_id": company.whatsapp_phone_number_id
    }