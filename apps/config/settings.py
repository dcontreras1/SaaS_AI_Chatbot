from pydantic import BaseSettings

class Settings(BaseSettings):
    app_name: str = "WhatsApp AI SaaS"
    environment: str = "development"
    openai_api_key: str
    whatsapp_token: str
    whatsapp_api_url: str
    database_url: str

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()
