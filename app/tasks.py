"""Фонові задачі Celery: сповіщення і перерахунок ETA."""

import logging

from celery import Celery

from .config import settings

log = logging.getLogger(__name__)

celery_app = Celery("delivery", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    task_always_eager=settings.celery_eager,
    timezone="Europe/Kyiv",
    beat_schedule={
        "recalculate-eta-every-2-min": {"task": "app.tasks.recalculate_eta", "schedule": 120.0},
    },
)


STATUS_TEXT = {
    "assigned": "Кур'єр прийняв ваше замовлення",
    "picked_up": "Кур'єр забрав посилку",
    "in_transit": "Посилка в дорозі",
    "delivered": "Замовлення доставлено. Дякуємо!",
    "cancelled": "Замовлення скасовано",
}


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30)
def notify_status_change(self, order_id: int, status: str):
    """Тут підключається реальний канал: push через FCM, SMS або Telegram.
    Зараз лише логуємо — інтеграція залежить від того, що використовує застосунок."""
    try:
        text = STATUS_TEXT.get(status)
        if text:
            log.info("Замовлення #%s: %s", order_id, text)
    except Exception as exc:
        raise self.retry(exc=exc) from exc


@celery_app.task
def recalculate_eta():
    """Періодично оновлюємо ETA активних замовлень за свіжими координатами кур'єрів."""
    from .database import SessionLocal
    from .geo import estimate_eta
    from .models import Order, OrderStatus

    db = SessionLocal()
    try:
        active = db.query(Order).filter(
            Order.status.in_([OrderStatus.assigned, OrderStatus.picked_up, OrderStatus.in_transit]),
            Order.courier_id.isnot(None),
        )
        updated = 0
        for order in active:
            if order.courier and order.courier.lat is not None:
                order.eta_minutes = estimate_eta(order.courier, order)
                updated += 1
        db.commit()
        return updated
    finally:
        db.close()
