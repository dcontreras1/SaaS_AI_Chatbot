import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional

from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import flag_modified # ¡IMPORTACIÓN CLAVE AÑADIDA!

from db.models.chat_session import ChatSession # Asegúrate que esta importación sea correcta

logger = logging.getLogger(__name__)

# --- CONSTANTE: Define el tiempo de inactividad en minutos ---
# Puedes ajustar este valor. 30 minutos es un buen punto de partida.
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
            .order_by(ChatSession.last_activity.desc()) # Ordena por la más reciente
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
                existing_session.status = "inactive" # Opcional: marca la sesión antigua como inactiva
                db_session.add(existing_session)
                await db_session.flush() # Fuerza la escritura de este cambio antes de proceder, si es necesario
                # Continúa para crear una nueva sesión
        
        # 3. Si no se encontró una sesión existente activa dentro del umbral de tiempo, crea una nueva.
        logger.info(f"CHAT_SESSION_REPO: Creando nueva sesión.")
        new_session = ChatSession(
            user_phone_number=user_phone_number,
            company_id=company_id,
            session_data={}, # Una nueva sesión siempre comienza con datos vacíos
            status="active",
            started_at=current_time_utc_naive,
            last_activity=current_time_utc_naive
        )
        db_session.add(new_session)
        await db_session.flush() # Importante para obtener el ID de la nueva sesión antes del commit
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
        # Asegura que session.session_data sea un diccionario mutable.
        # Esto es importante si el default={} no se asignó correctamente al cargar la sesión
        if not isinstance(session.session_data, dict):
            session.session_data = {}

        # Actualiza el diccionario con los nuevos datos.
        session.session_data.update(new_data) 
        
        # --- ¡LÍNEA CLAVE AÑADIDA O MODIFICADA! ---
        # Esto le indica explícitamente a SQLAlchemy que el atributo 'session_data'
        # ha sido modificado y necesita ser persistido en la base de datos.
        flag_modified(session, "session_data") 

        session.last_activity = datetime.now(timezone.utc).replace(tzinfo=None) # Actualiza la actividad
        db_session.add(session) # Marca la sesión como modificada
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
        session.session_data['waiting_for_name'] = False # Si el nombre se conserva, ya no lo esperamos
    
    # Restablecer flags iniciales para un nuevo flujo
    session.session_data['in_appointment_flow'] = False
    session.session_data['in_cancel_flow'] = False
    # Estos flags se pueden ajustar según si quieres que se pidan de nuevo
    session.session_data['waiting_for_name'] = True 
    session.session_data['waiting_for_datetime'] = True
    session.session_data['waiting_for_cancel_datetime'] = True
    session.session_data['waiting_for_cancel_confirmation'] = False
    session.session_data['confirm_cancel_id'] = None
    session.session_data['appointment_datetime_to_cancel'] = None

    # --- ¡LÍNEA CLAVE AÑADIDA O MODIFICADA! ---
    # Al reemplazar el diccionario completo, también es buena práctica marcarlo como modificado.
    flag_modified(session, "session_data") 

    session.last_activity = datetime.now(timezone.utc).replace(tzinfo=None) # Actualiza la actividad al limpiar
    db_session.add(session) # Marca la sesión como modificada
    logger.info(f"CHAT_SESSION_REPO: Slots de sesión limpiados para ID: {session.id}. Nuevos datos: {session.session_data}")