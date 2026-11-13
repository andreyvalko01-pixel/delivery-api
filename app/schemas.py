from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from .models import OrderStatus, Role


class Coordinates(BaseModel):
    lat: float = Field(ge=-90, le=90, examples=[50.4501])
    lon: float = Field(ge=-180, le=180, examples=[30.5234])


# ---------- користувачі ----------

class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    full_name: str = Field(min_length=2, max_length=120)
    phone: str | None = Field(default=None, pattern=r"^\+380\d{9}$")


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    full_name: str
    phone: str | None
    role: Role


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ---------- кур'єри ----------

class CourierCreate(BaseModel):
    user_id: int
    vehicle: str = Field(default="bike", pattern="^(foot|bike|scooter|car)$")


class CourierOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    vehicle: str
    is_online: bool
    lat: float | None
    lon: float | None


class CourierNearby(CourierOut):
    distance_km: float


class LocationUpdate(Coordinates):
    is_online: bool = True


# ---------- замовлення ----------

class OrderCreate(BaseModel):
    pickup_address: str
    pickup: Coordinates
    dropoff_address: str
    dropoff: Coordinates
    weight_kg: float = Field(default=1, gt=0, le=50)
    comment: str | None = Field(default=None, max_length=500)
    np_ttn: str | None = Field(default=None, pattern=r"^\d{14}$", description="ТТН, якщо далі відправка Новою поштою")


class OrderHistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: OrderStatus
    note: str | None
    created_at: datetime


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: OrderStatus
    client_id: int
    courier_id: int | None
    pickup_address: str
    dropoff_address: str
    weight_kg: float
    price: float
    eta_minutes: int | None
    np_ttn: str | None
    created_at: datetime


class OrderDetail(OrderOut):
    history: list[OrderHistoryOut]


class StatusUpdate(BaseModel):
    status: OrderStatus
    note: str | None = None


class AssignCourier(BaseModel):
    courier_id: int | None = Field(default=None, description="Не вказано — підберемо найближчого вільного")


class Page(BaseModel):
    items: list[OrderOut]
    total: int
    limit: int
    offset: int


# ---------- вебхук Нової пошти ----------

class NovaPoshtaEvent(BaseModel):
    ttn: str = Field(pattern=r"^\d{14}$")
    status_code: int
    status: str
