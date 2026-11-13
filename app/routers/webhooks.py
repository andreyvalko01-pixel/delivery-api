"""Вебхук трекінгу Нової пошти.

Нова пошта не шле вебхуки напряму — зазвичай статуси ТТН забирає окремий сервіс
(або інтегратор) і переправляє сюди. Запит підписується HMAC-SHA256 від тіла.
"""

import hashlib
import hmac

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import Order, OrderStatus
from ..schemas import NovaPoshtaEvent
from .orders import change_status

router = APIRouter(prefix="/webhooks", tags=["Вебхуки"])

# коди статусів НП -> наші статуси (повний список у документації НП)
NP_STATUS_MAP = {
    5: OrderStatus.in_transit,    # Відправлення прямує до міста
    6: OrderStatus.in_transit,    # У місті, очікується прибуття
    7: OrderStatus.in_transit,    # Прибуло на відділення
    9: OrderStatus.delivered,     # Отримано
    102: OrderStatus.cancelled,   # Відмова від отримання
}


def verify_signature(body: bytes, signature: str | None):
    expected = hmac.new(settings.np_webhook_secret.encode(), body, hashlib.sha256).hexdigest()
    if not signature or not hmac.compare_digest(expected, signature):
        raise HTTPException(401, "Невірний підпис")


@router.post("/nova-poshta")
async def nova_poshta_webhook(request: Request, x_signature: str | None = Header(None),
                              db: Session = Depends(get_db)):
    body = await request.body()
    verify_signature(body, x_signature)
    event = NovaPoshtaEvent.model_validate_json(body)

    order = db.query(Order).filter(Order.np_ttn == event.ttn).first()
    if not order:
        # не наша ТТН — відповідаємо 200, щоб відправник не повторював запит
        return {"ok": True, "ignored": True}

    new_status = NP_STATUS_MAP.get(event.status_code)
    if not new_status or new_status == order.status:
        return {"ok": True, "changed": False}

    # статуси НП можуть приходити не по порядку — пропускаємо неможливі переходи
    try:
        change_status(db, order, new_status, user=None, note=f"НП: {event.status}")
    except HTTPException:
        return {"ok": True, "changed": False}
    return {"ok": True, "changed": True}
