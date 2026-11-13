from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..geo import find_nearby_couriers
from ..models import Courier, Role, User
from ..schemas import CourierCreate, CourierNearby, CourierOut, LocationUpdate
from ..security import require_roles

router = APIRouter(prefix="/couriers", tags=["Кур'єри"])

staff = require_roles(Role.admin, Role.dispatcher)


@router.post("", response_model=CourierOut, status_code=status.HTTP_201_CREATED)
def create_courier(data: CourierCreate, db: Session = Depends(get_db), _: User = Depends(require_roles(Role.admin))):
    user = db.get(User, data.user_id)
    if not user:
        raise HTTPException(404, "Користувача не знайдено")
    if user.courier:
        raise HTTPException(409, "Цей користувач вже кур'єр")

    user.role = Role.courier
    courier = Courier(user_id=user.id, vehicle=data.vehicle)
    db.add(courier)
    db.commit()
    return courier


@router.get("/nearby", response_model=list[CourierNearby])
def nearby(
    lat: float = Query(ge=-90, le=90),
    lon: float = Query(ge=-180, le=180),
    radius_km: float = Query(5, gt=0, le=50),
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
    _: User = Depends(staff),
):
    """Вільні кур'єри онлайн у радіусі від точки, найближчі — першими."""
    found = find_nearby_couriers(db, lat, lon, radius_km, limit)
    return [CourierNearby(**CourierOut.model_validate(c).model_dump(), distance_km=d) for c, d in found]


@router.put("/me/location", response_model=CourierOut)
def update_my_location(data: LocationUpdate, db: Session = Depends(get_db),
                       user: User = Depends(require_roles(Role.courier))):
    """Мобільний застосунок кур'єра шле координати кожні 15–30 секунд."""
    courier = user.courier
    courier.lat, courier.lon = data.lat, data.lon
    courier.is_online = data.is_online
    courier.location_updated_at = datetime.now(timezone.utc)
    db.commit()
    return courier
