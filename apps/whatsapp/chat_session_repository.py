import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional

from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import flag_modified

from db.models.chat_session import ChatSession

logger = logging.getLogger(__name__)

# CONSTANTE: Define el tiempo de inactividad en minutos antes de que una sesión se considere inactiva.
SESSION_INACTIVITY_TIMEOUT_MINUTES = 30 

async def get_or_create_session(user_phone_number: str, company_id: int, db_session: AsyncSession) -> ChatSession:
    """
    Obtiene una sesión de chat existente para un usuario y compañía, o crea una nueva.
    Una sesión se considera activa si su estado es 'active' y su última actividad
    fue hace menos de SESSION_INACTIVITY_TIMEOUT_MINUTES.
    """
    logger.info(f"CHAT_SESSION_REPO: Buscando/Creando sesión para user={user_phone_number}, company_id={company_id}")
    try:
        current_time_utc_naive = datetime.now(timezone.utc).replace(tzinfo=None)
        inactivity_threshold = current_time_utc_naive - timedelta(minutes=SESSION_INACTIVITY_TIMEOUT_MINUTES)

        # 1. Intenta encontrar la sesión activa más reciente para este usuario y compañía.
        # No filtres por 'last_activity' aquí inicialmente, para poder evaluar la inactividad.
        result = await db_session.execute(
            select(ChatSession)
            .where(
                ChatSession.user_phone_number == user_phone_number,
                ChatSession.company_id == company_id,
                ChatSession.status == "active"
            )
            .order_by(ChatSession.last_activity.desc())
            .limit(1)
        )
        existing_session = result.scalar_one_or_none()

        if existing_session:
            # 2. Si se encontró una sesión existente, verifica si está inactiva
            if existing_session.last_activity >= inactivity_threshold:
                # La sesión está activa y dentro del umbral de tiempo
                logger.info(f"CHAT_SESSION_REPO: Sesión existente encontrada (ID: {existing_session.id}, Datos: {existing_session.session_data})")
                # Actualizar last_activity para mantenerla activa
                existing_session.last_activity = current_time_utc_naive
                db_session.add(existing_session)
                return existing_session
            else:
                # La sesión existe pero ha estado inactiva por demasiado tiempo
                logger.info(f"CHAT_SESSION_REPO: Sesión existente inactiva (ID: {existing_session.id}, última actividad: {existing_session.last_activity}). Marcando como inactiva y creando nueva.")
                existing_session.status = "inactive"
                db_session.add(existing_session)
                await db_session.flush()
        
        # 3. Si no se encontró una sesión existente activa dentro del umbral de tiempo, crea una nueva.
        logger.info(f"CHAT_SESSION_REPO: Creando nueva sesión.")
        new_session = ChatSession(
            user_phone_number=user_phone_number,
            company_id=company_id,
            session_data={},
            status="active",
            started_at=current_time_utc_naive,
            last_activity=current_time_utc_naive
        )
        db_session.add(new_session)
        await db_session.flush()
        logger.info(f"CHAT_SESSION_REPO: Nueva sesión creada (ID: {new_session.id})")
        return new_session

    except Exception as e:
        logger.error(f"CHAT_SESSION_REPO: Error al obtener o crear sesión para user={user_phone_number}, company_id={company_id}: {e}", exc_info=True)
        raise

async def update_session_data(session: ChatSession, new_data: Dict[str, Any], db_session: AsyncSession) -> None:
    """
    Actualiza el campo session_data de una ChatSession en la base de datos.
    También actualiza last_activity.
    """
    logger.info(f"CHAT_SESSION_REPO: Actualizando session_data para sesión ID: {session.id} con datos: {new_data}")
    try:
        if not isinstance(session.session_data, dict):
            session.session_data = {}

        session.session_data.update(new_data) 
        
        flag_modified(session, "session_data") 

        session.last_activity = datetime.now(timezone.utc).replace(tzinfo=None)
        db_session.add(session)
    except Exception as e:
        logger.error(f"CHAT_SESSION_REPO: Error al actualizar session_data para sesión ID {session.id}: {e}", exc_info=True)
        raise

async def clear_session_slots(session: ChatSession, db_session: AsyncSession, preserve_name: bool = False) -> None:
    """
    Limpia los slots de la sesión, conservando el nombre del cliente si se especifica.
    También actualiza last_activity.
    """
    logger.info(f"CHAT_SESSION_REPO: Limpiando slots para sesión ID: {session.id}. preserve_name={preserve_name}")
    
    if session.session_data is None:
        session.session_data = {}

    current_name = session.session_data.get('client_name') if preserve_name else None
    
    # Reiniciar la sesión con un diccionario vacío o solo el nombre si se debe preservar
    session.session_data = {}
    if preserve_name and current_name:
        session.session_data['client_name'] = current_name
        session.session_data['waiting_for_name'] = False
    
    # Restablecer flags iniciales para un nuevo flujo
    session.session_data['in_appointment_flow'] = False
    session.session_data['in_cancel_flow'] = False
    session.session_data['waiting_for_name'] = True 
    session.session_data['waiting_for_datetime'] = True
    session.session_data['waiting_for_cancel_datetime'] = True
    session.session_data['waiting_for_cancel_confirmation'] = False
    session.session_data['confirm_cancel_id'] = None
    session.session_data['appointment_datetime_to_cancel'] = None

    flag_modified(session, "session_data") 

    session.last_activity = datetime.now(timezone.utc).replace(tzinfo=None)
    db_session.add(session)
    logger.info(f"CHAT_SESSION_REPO: Slots de sesión limpiados para ID: {session.id}. Nuevos datos: {session.session_data}")