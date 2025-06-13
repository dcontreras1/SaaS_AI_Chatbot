# Whatsapp AI Assistant
Este proyecto es un asistente virtual de WhatsApp impulsado por Inteligencia Artificial, diseñado para automatizar la comunicación con clientes, responder preguntas frecuentes y gestionar tareas como el agendamiento de citas. Utiliza la API de Twilio para WhatsApp, Google Gemini como su cerebro de procesamiento de lenguaje natural (NLP) y Google Calendar para la gestión de citas.

## Características
- Integración con WhatsApp: Envía y recibe mensajes a través de la API de Twilio para WhatsApp.
- Procesamiento de Lenguaje Natural (NLP): Utiliza Google Gemini para entender las intenciones del usuario y extraer entidades (fechas, horas, nombres, teléfonos).
- Gestión de Citas: Permite a los usuarios agendar citas directamente a través de Google Calendar.
- Respuestas a Preguntas Frecuentes: Responde a preguntas sobre horarios, servicios y otra información de la empresa.
- Contexto Conversacional: Mantiene un historial limitado de la conversación para proporcionar respuestas más coherentes y guiar al usuario a través de flujos transaccionales como el agendamiento.
- Almacenamiento de Datos: Persiste mensajes y clientes (conocidos y desconocidos) en una base de datos PostgreSQL.
- Arquitectura Modular: Diseñado con módulos claros para IA, WhatsApp, calendario y base de datos.

## Tecnologías utilizadas
- Python 3.9+
- FastAPI: Para la creación de la API web.
- Twilio API: Para la integración con WhatsApp.
- Google Gemini API: Modelo de lenguaje grande (LLM) para inteligencia conversacional.
- Google Calendar API: Para la gestión de eventos y citas.
- SQLAlchemy (con Asyncio): ORM asíncrono para la interacción con la base de datos.
- PostgreSQL: Base de datos relacional para el almacenamiento de datos.
- Docker & Docker Compose: Para la contenerización y orquestación de servicios.
- `dateparser`: Librería robusta para el parseo de fechas y horas en lenguaje natural.

## Configuración del entorno
### 1. Variables de Entorno
Crea un archivo `.env` en la raíz del proyecto basándote en `.env.example`:
```
# .env

# Base de datos PostgreSQL
DATABASE_URL="postgresql+asyncpg://user:password@db:5432/dbname"

# Twilio
TWILIO_ACCOUNT_SID="ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
TWILIO_AUTH_TOKEN="your_twilio_auth_token"
TWILIO_WHATSAPP_NUMBER="whatsapp:+1234567890" # Tu número de Twilio con prefijo whatsapp:

# Google Gemini API
GOOGLE_API_KEY="AIzaSyAxxxxxxxxxxxxxxxxxxxxxxxxxxx"

# Google Calendar API (credenciales del archivo service_account.json)
# Ruta donde se guardará el archivo JSON de credenciales de Google Service Account.
# Este archivo debe generarse en la consola de Google Cloud y tener los permisos para Google Calendar.
GOOGLE_CALENDAR_CREDENTIALS_PATH="/app/google_credentials.json"
# El ID del calendario principal donde se agendarán las citas
GOOGLE_CALENDAR_ID="your-calendar-id@group.calendar.google.com"
```
Obtención de credenciales:
- Twilio: Regístrate en Twilio, configura tu número de WhatsApp y obtén tu `ACCOUNT_SID` y `AUTH_TOKEN` desde el dashboard de Twilio.
- Google Gemini: Habilita la API de Gemini en Google Cloud Console y crea una clave de API.
- Google Calendar:
1. Ve a Google Cloud Console.
2. Crea un nuevo proyecto (o selecciona uno existente).
3. Ve a "APIs y Servicios" -> "Credenciales".
4. Crea una "Cuenta de servicio".
5. Asigna un nombre a la cuenta de servicio y otórgale el rol de "Editor de Calendario" o "Propietario" (se recomienda "Editor de 6. Calendario" para permisos más restrictivos).
6. Genera una nueva clave JSON para esta cuenta de servicio. Descarga este archivo JSON.
7. Renombra el archivo JSON descargado a `google_credentials.json` y colócalo en la misma carpeta donde estará tu `Dockerfile` (la raíz del proyecto, `/app` dentro del contenedor).
8. Comparte el correo electrónico de la cuenta de servicio (ej. `nombre-de-servicio@proyecto-id.iam.gserviceaccount.com`) con tu Google Calendar principal, dándole permisos de "Realizar cambios y gestionar uso compartido".
9. Obtén el ID del Calendario que quieres usar para agendar citas (generalmente se encuentra en la configuración del calendario en Google Calendar).

### 2. Base de Datos PostgreSQL
Asegúrate de que tu `DATABASE_URL` apunte a una base de datos PostgreSQL accesible. Si usas Docker Compose, el servicio `db` ya está configurado y se conectará automáticamente.

### 3. Instalación de Dependencias
Las dependencias están en `requirements.txt`. Docker se encargará de instalarlas automáticamente durante la construcción de la imagen.

## Despliegue con Docker Compose
La forma más sencilla de ejecutar este proyecto es usando Docker Compose.

1. Clona el repositorio:
```
git clone https://github.com/dcontreras1/SaaS_AI_Chatbot
cd SaaS_AI_Chatbot
```
2. Crea el archivo `.env` con tus credenciales, como se explicó anteriormente.
3. Construye y levanta los servicios:
```
docker-compose up --build
```
- `--build`: Reconstruye las imágenes Docker. Útil cuando haces cambios en el código.
- `-d`: Ejecuta los contenedores en segundo plano (detached mode).
Esto iniciará tres servicios:

- `db`: Un contenedor PostgreSQL para la base de datos.
- `adminer`: Una interfaz web para gestionar tu base de datos (accesible en `http://localhost:8080`).
- `whatsapp_ia_backend`: Tu aplicación FastAPI de Python.

4. Aplicar Migraciones de la Base de Datos:
Una vez que los contenedores estén corriendo, necesitas crear las tablas en la base de datos. Accede al shell del contenedor de tu aplicación y ejecuta un script para crear las tablas (asumiendo que tienes un script `db_init.py` o similar, o que el ORM las crea automáticamente):
```
docker exec -it whatsapp_ia_backend bash
# Dentro del contenedor, si tienes un script para crear tablas:
# python -m db.create_tables # (Ejemplo, adapta a tu configuración)
# exit
```
Nota: En tu configuración actual, si estás usando SQLAlchemy con `Base.metadata.create_all`, podrías necesitar un pequeño script de inicio para que se ejecute la primera vez y cree las tablas, o incorporarlo en la lógica de inicio de tu aplicación FastAPI.

## Configurar webhook de Twilio (API de Whatsapp)
Para que Twilio envíe los mensajes entrantes a tu aplicación, necesitas configurar un webhook:
1. Expón tu servicio: Si estás desarrollando localmente, usa una herramienta como `ngrok` para exponer tu puerto local a Internet.
`ngrok http 8000 # El puerto donde corre tu aplicación FastAPI`
`ngrok` te dará una URL pública (ej. `https://abcdef12345.ngrok-free.app`).
2. Configura el Webhook en Twilio:
- Ve al Dashboard de Twilio.
- Navega a Programmable Messaging > Senders > WhatsApp Senders.
- Haz clic en tu número de WhatsApp.
- En la sección "Messaging", debajo de "WHEN A MESSAGE COMES IN", selecciona Webhook y pega tu URL de `ngrok` seguida de `/webhook/whatsapp`. Ejemplo: `https://abcdef12345.ngrok-free.app/webhook/whatsapp`
- Asegúrate de que el método HTTP sea POST.
- Guarda los cambios.

## Uso y Flujo de la Conversación
El bot está diseñado para manejar los siguientes flujos de conversación:
1. Consultas Generales:
- Usuario: "Hola, ¿cuál es su horario de atención?"
- Bot: Responde con el horario configurado en la base de datos de la empresa.
2. Agendamiento de Citas:
- Usuario: "Quisiera agendar una cita."
- Bot: "Necesito la fecha y hora específicas para programar tu cita. ¿Podrías proporcionármelas?"
- Usuario: "El viernes 30 de mayo a las 3 de la tarde."
- Bot: "¡Perfecto! Ya tengo la fecha y hora: 30/05/2025 a las 15:00. Ahora necesito tu nombre y un número de teléfono de contacto para poder agendar tu cita."
- Usuario: "Mi nombre es Manuel Rodríguez y mi teléfono es 3123456789."
- Bot: "¡Perfecto! Tu cita ha sido programada para el 30/05/2025 a las 15:00. Te esperamos, Manuel Rodríguez."
- (El bot creará un evento en Google Calendar con los detalles proporcionados.)
3. Provisión de Contacto:
- Usuario: "Mi nombre es Juan Pérez y mi número es 3001234567."
- Bot: "Gracias por tu información de contacto. ¿En qué más puedo ayudarte?"
4. Conversaciones Abiertas/Desconocidas:
- Si la intención no es clara, el bot utilizará Gemini para generar una respuesta basada en el contexto de la conversación y la información general de la empresa.
