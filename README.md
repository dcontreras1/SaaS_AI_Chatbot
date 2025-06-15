# SaaS AI Chatbot

Proyecto SaaS de Atención al Cliente por Whatsapp con IA  
**Repositorio:** [dcontreras1/SaaS_AI_Chatbot](https://github.com/dcontreras1/SaaS_AI_Chatbot)

---

## Descripción

Este proyecto es una plataforma SaaS que permite a empresas gestionar la atención de clientes a través de WhatsApp, utilizando Inteligencia Artificial para automatizar la reserva de citas, respuestas frecuentes y la integración con servicios externos como Google Calendar.

---

## Características Principales

- **Atención Automatizada vía WhatsApp:**  
  Los clientes pueden interactuar con un asistente inteligente por WhatsApp para agendar citas, consultar horarios, cancelar reservas y más.

- **Agendamiento de Citas con Recursos Personalizados:**  
  - Soporte para múltiples recursos (ejemplo: doctores, especialistas, agentes).
  - Cada recurso puede tener distinta duración de cita.
  - Permite agendar citas en paralelo con diferentes recursos (configurable).
  - Chequeo de disponibilidad en tiempo real usando Google Calendar.

- **Flujo de Conversación Inteligente:**  
  - Extracción automática de nombre, recurso y fecha/hora usando IA (NLP).
  - Reconocimiento de intenciones: agendar, cancelar, consultar horarios, saludo y más.
  - Manejo de slots y preguntas dinámicas según la configuración de cada empresa.

- **Integración con Google Calendar:**  
  - Creación y eliminación automática de eventos.
  - Control de conflictos de horario basado en el recurso (doctor, agente, etc).

- **Gestión Multiempresa:**  
  - Cada empresa puede tener su propia configuración de recursos, horarios y mensajes de confirmación.
  - Soporte para múltiples empresas en la misma plataforma SaaS.

- **Persistencia y Seguridad:**  
  - Almacenamiento seguro de sesiones y datos en la base de datos.
  - Variables sensibles gestionadas mediante archivos `.env`.

- **Escalabilidad y Despliegue:**  
  - Preparado para despliegue en Docker.
  - Arquitectura asincrónica basada en FastAPI y SQLAlchemy.

---

## Tecnologías y Herramientas

- **Backend:** Python (FastAPI, SQLAlchemy)
- **Mensajería:** WhatsApp (Twilio API)
- **IA/NLP:** Extracción de entidades e intenciones
- **Calendario:** Google Calendar API
- **ORM:** SQLAlchemy (async)
- **Base de Datos:** PostgreSQL (recomendado)
- **Autenticación:** Google Service Account para Calendar
- **Entornos:** Docker, dotenv

---

## Ejemplo de Flujo de Citas

1. El cliente inicia la conversación por WhatsApp.
2. El bot saluda y guía al usuario para agendar una cita.
3. Solicita el recurso (ejemplo: doctor), nombre y fecha/hora.
4. Verifica disponibilidad en Google Calendar considerando si el recurso permite citas en paralelo.
5. Confirma la cita y la agenda en el calendario.
6. Permite cancelar o reprogramar citas mediante comandos simples.

---

## Configuración de una Empresa (Ejemplo)

```python
EMPRESA = {
    "name": "Clínica Odontológica Sonríe",
    "industry": "Salud",
    "schedule": "Lunes a Viernes, 8am a 8pm",
    "calendar_email": "empresa@gmail.com",
    "company_metadata": {
        "appointment_slots": [
            {
                "key": "doctor",
                "label": "doctor",
                "type": "string",
                "required": True,
                "options": ["María Martinez", "Eduardo López"]
            },
            {
                "key": "name",
                "label": "nombre",
                "type": "string",
                "required": True
            },
            {
                "key": "datetime",
                "label": "fecha y hora",
                "type": "datetime",
                "required": True
            }
        ],
        "appointment_durations": {
            "María Martinez": 30,
            "Eduardo López": 60
        },
        "allow_parallel_appointments": True,
        "confirmation_message": "Perfecto, {name}, tu cita con {doctor} fue agendada para el {datetime}.",
        "doctors": [
            {"name": "María Martinez", "specialty": "Ortodoncia"},
            {"name": "Eduardo López", "specialty": "Odontología general"}
        ]
    }
}