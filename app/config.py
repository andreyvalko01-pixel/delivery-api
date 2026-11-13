from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./delivery.db"
    redis_url: str = "redis://localhost:6379/0"

    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 60 * 12

    # ліміт запитів з одного IP за хвилину
    rate_limit_per_minute: int = 120

    # секрет, яким Нова пошта (або наш проксі до неї) підписує вебхуки
    np_webhook_secret: str = "np-secret"

    # у тестах і локально Celery виконує задачі одразу, без воркера
    celery_eager: bool = True


settings = Settings()
