"""Пошук найближчих кур'єрів.

На PostgreSQL з PostGIS рахуємо відстань у базі через ST_DWithin / ST_Distance (з індексом це швидко).
На SQLite (локальна розробка, тести) — haversine в Python.
"""

import math

from sqlalchemy import text
from sqlalchemy.orm import Session

from .database import is_postgres
from .models import Courier, Order, OrderStatus

EARTH_RADIUS_KM = 6371.0

# швидкість для грубого ETA, км/год
SPEED = {"foot": 5, "bike": 15, "scooter": 25, "car": 30}


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def _busy_courier_ids(db: Session) -> set[int]:
    active = [OrderStatus.assigned, OrderStatus.picked_up, OrderStatus.in_transit]
    rows = db.query(Order.courier_id).filter(Order.status.in_(active), Order.courier_id.isnot(None)).all()
    return {r[0] for r in rows}


POSTGIS_QUERY = text("""
    SELECT id,
           ST_Distance(
               ST_SetSRID(ST_MakePoint(lon, lat), 4326)::geography,
               ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography
           ) / 1000 AS distance_km
    FROM couriers
    WHERE is_online
      AND lat IS NOT NULL
      AND ST_DWithin(
              ST_SetSRID(ST_MakePoint(lon, lat), 4326)::geography,
              ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,
              :radius_m)
    ORDER BY distance_km
    LIMIT :limit
""")


def find_nearby_couriers(db: Session, lat: float, lon: float, radius_km: float = 5, limit: int = 10,
                         only_free: bool = True) -> list[tuple[Courier, float]]:
    busy = _busy_courier_ids(db) if only_free else set()

    if is_postgres():
        rows = db.execute(POSTGIS_QUERY, {"lat": lat, "lon": lon, "radius_m": radius_km * 1000, "limit": limit * 2}).all()
        couriers = {c.id: c for c in db.query(Courier).filter(Courier.id.in_([r.id for r in rows]))}
        result = [(couriers[r.id], round(r.distance_km, 2)) for r in rows if r.id not in busy]
        return result[:limit]

    result = []
    for courier in db.query(Courier).filter(Courier.is_online.is_(True), Courier.lat.isnot(None)):
        if courier.id in busy:
            continue
        distance = haversine_km(lat, lon, courier.lat, courier.lon)
        if distance <= radius_km:
            result.append((courier, round(distance, 2)))

    result.sort(key=lambda pair: pair[1])
    return result[:limit]


def estimate_eta(courier: Courier, order: Order) -> int:
    """Хвилини: кур'єр -> точка забору -> точка доставки + 10 хв на передачу."""
    speed = SPEED.get(courier.vehicle, 15)
    to_pickup = haversine_km(courier.lat, courier.lon, order.pickup_lat, order.pickup_lon)
    route = haversine_km(order.pickup_lat, order.pickup_lon, order.dropoff_lat, order.dropoff_lon)
    # по прямій виходить оптимістично, множимо на 1.3 — так ближче до реальних доріг
    return round((to_pickup + route) * 1.3 / speed * 60) + 10


def calculate_price(distance_km: float, weight_kg: float) -> float:
    base, per_km, per_kg = 60, 14, 5
    extra_weight = max(0, weight_kg - 3)
    return round(base + distance_km * per_km + extra_weight * per_kg, 2)
