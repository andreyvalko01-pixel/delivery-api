from contextlib import asynccontextmanager

from fastapi import FastAPI

from .database import Base, engine
from .rate_limit import RateLimitMiddleware
from .routers import auth, couriers, orders, webhooks

DESCRIPTION = """
Бекенд для застосунку кур'єрської доставки.

* **Клієнт** створює замовлення і бачить його статус
* **Диспетчер** призначає кур'єрів (вручну або найближчого вільного)
* **Кур'єр** оновлює геолокацію і статуси
* **Нова пошта** присилає зміни статусів ТТН через вебхук

Авторизація — JWT (кнопка *Authorize*).
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    # для розробки створюємо таблиці автоматично; на продакшені — міграції Alembic
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="Delivery API", version="1.0.0", description=DESCRIPTION, lifespan=lifespan)
app.add_middleware(RateLimitMiddleware)

for router in (auth.router, orders.router, couriers.router, webhooks.router):
    app.include_router(router, prefix="/api/v1")


@app.get("/health", tags=["Службове"])
def health():
    return {"status": "ok"}
