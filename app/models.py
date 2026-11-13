import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class Role(str, enum.Enum):
    admin = "admin"
    dispatcher = "dispatcher"
    courier = "courier"
    client = "client"


class OrderStatus(str, enum.Enum):
    created = "created"
    assigned = "assigned"
    picked_up = "picked_up"
    in_transit = "in_transit"
    delivered = "delivered"
    cancelled = "cancelled"


# які переходи статусів дозволені — щоб не можна було "доставити" скасоване замовлення
ALLOWED_TRANSITIONS = {
    OrderStatus.created: {OrderStatus.assigned, OrderStatus.cancelled},
    OrderStatus.assigned: {OrderStatus.picked_up, OrderStatus.created, OrderStatus.cancelled},
    OrderStatus.picked_up: {OrderStatus.in_transit, OrderStatus.cancelled},
    OrderStatus.in_transit: {OrderStatus.delivered},
    OrderStatus.delivered: set(),
    OrderStatus.cancelled: set(),
}


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(20))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(Enum(Role), default=Role.client)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    courier: Mapped["Courier | None"] = relationship(back_populates="user")


class Courier(Base):
    __tablename__ = "couriers"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    vehicle: Mapped[str] = mapped_column(String(30), default="bike")
    is_online: Mapped[bool] = mapped_column(default=False)
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    location_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="courier")
    orders: Mapped[list["Order"]] = relationship(back_populates="courier")


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    courier_id: Mapped[int | None] = mapped_column(ForeignKey("couriers.id"), index=True)
    status: Mapped[OrderStatus] = mapped_column(Enum(OrderStatus), default=OrderStatus.created, index=True)

    pickup_address: Mapped[str] = mapped_column(String(255))
    pickup_lat: Mapped[float] = mapped_column(Float)
    pickup_lon: Mapped[float] = mapped_column(Float)
    dropoff_address: Mapped[str] = mapped_column(String(255))
    dropoff_lat: Mapped[float] = mapped_column(Float)
    dropoff_lon: Mapped[float] = mapped_column(Float)

    weight_kg: Mapped[float] = mapped_column(Float, default=1)
    price: Mapped[float] = mapped_column(Float)
    comment: Mapped[str | None] = mapped_column(Text)
    np_ttn: Mapped[str | None] = mapped_column(String(20), index=True)  # ТТН Нової пошти, якщо відправка через НП
    eta_minutes: Mapped[int | None] = mapped_column(Integer)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    courier: Mapped[Courier | None] = relationship(back_populates="orders")
    history: Mapped[list["OrderHistory"]] = relationship(back_populates="order", order_by="OrderHistory.id")


class OrderHistory(Base):
    __tablename__ = "order_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    status: Mapped[OrderStatus] = mapped_column(Enum(OrderStatus))
    note: Mapped[str | None] = mapped_column(String(255))
    changed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    order: Mapped[Order] = relationship(back_populates="history")
