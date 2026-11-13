from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..geo import calculate_price, estimate_eta, find_nearby_couriers, haversine_km
from ..models import ALLOWED_TRANSITIONS, Courier, Order, OrderHistory, OrderStatus, Role, User
from ..schemas import AssignCourier, OrderCreate, OrderDetail, OrderOut, Page, StatusUpdate
from ..security import get_current_user, require_roles
from ..tasks import notify_status_change

router = APIRouter(prefix="/orders", tags=["Замовлення"])

STAFF = (Role.admin, Role.dispatcher)


def get_order_for(user: User, order_id: int, db: Session) -> Order:
    order = db.query(Order).options(selectinload(Order.history)).get(order_id)
    if not order:
        raise HTTPException(404, "Замовлення не знайдено")

    # клієнт бачить свої замовлення, кур'єр — призначені йому, персонал — усі
    allowed = (
        user.role in STAFF
        or (user.role == Role.client and order.client_id == user.id)
        or (user.role == Role.courier and user.courier and order.courier_id == user.courier.id)
    )
    if not allowed:
        raise HTTPException(404, "Замовлення не знайдено")
    return order


def change_status(db: Session, order: Order, new_status: OrderStatus, user: User | None, note: str | None = None):
    if new_status not in ALLOWED_TRANSITIONS[order.status]:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Не можна змінити статус з '{order.status.value}' на '{new_status.value}'",
        )
    order.status = new_status
    db.add(OrderHistory(order_id=order.id, status=new_status, note=note, changed_by=user.id if user else None))
    db.commit()
    notify_status_change.delay(order.id, new_status.value)


@router.post("", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
def create_order(data: OrderCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    distance = haversine_km(data.pickup.lat, data.pickup.lon, data.dropoff.lat, data.dropoff.lon)
    if distance > 60:
        raise HTTPException(422, "Доставка працює в межах міста (до 60 км)")

    order = Order(
        client_id=user.id,
        pickup_address=data.pickup_address,
        pickup_lat=data.pickup.lat,
        pickup_lon=data.pickup.lon,
        dropoff_address=data.dropoff_address,
        dropoff_lat=data.dropoff.lat,
        dropoff_lon=data.dropoff.lon,
        weight_kg=data.weight_kg,
        comment=data.comment,
        np_ttn=data.np_ttn,
        price=calculate_price(distance, data.weight_kg),
    )
    db.add(order)
    db.flush()
    db.add(OrderHistory(order_id=order.id, status=OrderStatus.created, changed_by=user.id))
    db.commit()
    return order


@router.get("", response_model=Page)
def list_orders(
    status_filter: OrderStatus | None = Query(None, alias="status"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = db.query(Order)
    if user.role == Role.client:
        query = query.filter(Order.client_id == user.id)
    elif user.role == Role.courier:
        query = query.filter(Order.courier_id == (user.courier.id if user.courier else -1))
    if status_filter:
        query = query.filter(Order.status == status_filter)

    total = query.count()
    items = query.order_by(Order.id.desc()).offset(offset).limit(limit).all()
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.get("/{order_id}", response_model=OrderDetail)
def get_order(order_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return get_order_for(user, order_id, db)


@router.post("/{order_id}/assign", response_model=OrderOut)
def assign_courier(order_id: int, data: AssignCourier, db: Session = Depends(get_db),
                   user: User = Depends(require_roles(*STAFF))):
    order = get_order_for(user, order_id, db)
    if order.status != OrderStatus.created:
        raise HTTPException(409, "Призначити кур'єра можна лише новому замовленню")

    if data.courier_id:
        courier = db.get(Courier, data.courier_id)
        if not courier or not courier.is_online:
            raise HTTPException(409, "Кур'єр недоступний")
    else:
        nearby = find_nearby_couriers(db, order.pickup_lat, order.pickup_lon, radius_km=10, limit=1)
        if not nearby:
            raise HTTPException(409, "Поруч немає вільних кур'єрів")
        courier = nearby[0][0]

    order.courier_id = courier.id
    if courier.lat is not None:
        order.eta_minutes = estimate_eta(courier, order)
    change_status(db, order, OrderStatus.assigned, user, note=f"Кур'єр #{courier.id}")
    return order


@router.patch("/{order_id}/status", response_model=OrderOut)
def update_status(order_id: int, data: StatusUpdate, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    order = get_order_for(user, order_id, db)

    # клієнт може тільки скасувати, і тільки поки кур'єр не забрав посилку
    if user.role == Role.client and data.status != OrderStatus.cancelled:
        raise HTTPException(403, "Клієнт може лише скасувати замовлення")

    change_status(db, order, data.status, user, data.note)
    return order
