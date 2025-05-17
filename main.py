import os
import sys
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

# === Agregar la carpeta raíz al PYTHONPATH
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# === Cargar variables de entorno desde .env ===
dotenv_path = os.getenv('DOTENV_PATH', '.env')
load_dotenv(dotenv_path)

# === Importar routers ===
from apps.whatsapp.twilio_webhook_handler import webhook_router

# === Inicializar la app de FastAPI ===
app = FastAPI(title="WhatsApp IA SaaS", version="1.0.0")

# === Configurar CORS ===
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Cambia esto en producción
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# === Incluir routers ===
app.include_router(webhook_router, prefix="/whatsapp", tags=["WhatsApp"])

# === Ruta raíz de prueba ===
@app.get("/")
def root():
    return {"message": "API de WhatsApp IA SaaS está corriendo"}
