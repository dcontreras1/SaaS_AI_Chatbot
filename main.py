import os
import sys
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import asyncio
import logging
from contextlib import asynccontextmanager

# === Configuración básica de logging ===
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# === Agregar la carpeta raíz al PYTHONPATH ===
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# === Cargar variables de entorno desde .env ===
dotenv_path = os.getenv('DOTENV_PATH', '.env')
load_dotenv(dotenv_path)

# === Importar routers ===
from apps.whatsapp.twilio_webhook_handler import webhook_router

# === Importar el servicio de purga de tareas ===
from tasks import start_purging_service

# --- NUEVO: Manejador de eventos de Lifespan ---
# Define tu función de lifespan como un context manager
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manejador de eventos de ciclo de vida (startup/shutdown) para la aplicación FastAPI.
    Aquí se inician tareas en segundo plano y se cierran recursos.
    """
    logger.info("La aplicación se está iniciando (via lifespan)...")
    print("La aplicación se está iniciando (via lifespan)...")

    # Inicia la tarea de purga de mensajes en segundo plano.
    # Se ejecutará cada 3600 segundos (1 hora) y borrará mensajes con más de 24 horas.
    asyncio.create_task(start_purging_service(interval_seconds=3600, max_age_hours=24))
    logger.info("Servicio de purga de mensajes programado para ejecutarse periódicamente.")
    print("Servicio de purga de mensajes programado.")

    yield # Todo el código ANTES de 'yield' se ejecuta en el 'startup'

    logger.info("La aplicación se está apagando (via lifespan)...")
    print("La aplicación se está apagando (via lifespan)...")
    # El código después de 'yield' se ejecuta al apagar el servidor.
    # Aquí puedes cerrar conexiones, liberar recursos, etc.
    # Nota: No se pueden cancelar directamente las tareas creadas con asyncio.create_task() desde aquí.
    # Para detener tareas en segundo plano, se recomienda usar señales o guardar referencias a las tareas.
    # En el caso de la purga, se detendrá automáticamente al cerrar el servidor.



# === Inicializar la app de FastAPI ===
# Importante: Pasa el manejador de lifespan al constructor de FastAPI
app = FastAPI(title="WhatsApp IA SaaS", version="1.0.0", lifespan=lifespan) # Cambio aquí

# === Configurar CORS ===
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # ADVERTENCIA: Cambiar esto a los dominios específicos en producción
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# === Incluir routers ===
app.include_router(webhook_router, prefix="/whatsapp", tags=["WhatsApp"])

# === Ruta raíz de prueba ===
@app.get("/")
def root():
    return {"message": "API de WhatsApp IA SaaS está corriendo y el servicio de purga está activo."}