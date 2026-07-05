from sqlalchemy import (
    Column, String, Integer, BigInteger, Boolean,
    DateTime, ForeignKey, Text
)
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime, timezone
import json

Base = declarative_base()


def now_utc():
    return datetime.now(timezone.utc)


class Group(Base):
    __tablename__ = "groups"

    group_id = Column(String, primary_key=True)           # LINE groupId
    _admin_ids = Column("admin_ids", Text, default="[]")  # JSON 字串存管理員清單
    current_menu_id = Column(Integer, ForeignKey("menus.menu_id"), nullable=True)

    # 用 property 讓其他程式碼可以繼續用 group.admin_ids 當作 list 操作
    @property
    def admin_ids(self):
        return json.loads(self._admin_ids or "[]")

    @admin_ids.setter
    def admin_ids(self, value):
        self._admin_ids = json.dumps(value or [])

    menus = relationship("Menu", back_populates="group", foreign_keys="Menu.group_id")
    orders = relationship("Order", back_populates="group")


class Menu(Base):
    __tablename__ = "menus"

    menu_id = Column(Integer, primary_key=True, autoincrement=True)
    group_id = Column(String, ForeignKey("groups.group_id"), nullable=False)
    store_name = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=now_utc)

    group = relationship("Group", back_populates="menus", foreign_keys=[group_id])
    items = relationship("MenuItem", back_populates="menu", cascade="all, delete-orphan")


class MenuItem(Base):
    __tablename__ = "menu_items"

    item_id = Column(Integer, primary_key=True, autoincrement=True)
    menu_id = Column(Integer, ForeignKey("menus.menu_id"), nullable=False)
    number = Column(Integer, nullable=False)   # 點餐編號，如 1、2、3
    name = Column(String, nullable=False)
    price = Column(Integer, nullable=False)    # 以元為單位
    category = Column(String, nullable=True)   # 分類，如「茶類」，可為 None

    menu = relationship("Menu", back_populates="items")


class Order(Base):
    __tablename__ = "orders"

    order_id = Column(Integer, primary_key=True, autoincrement=True)
    group_id = Column(String, ForeignKey("groups.group_id"), nullable=False)
    menu_id = Column(Integer, ForeignKey("menus.menu_id"), nullable=False)
    is_open = Column(Boolean, default=True)
    opened_at = Column(DateTime(timezone=True), default=now_utc)
    closed_at = Column(DateTime(timezone=True), nullable=True)

    group = relationship("Group", back_populates="orders")
    order_items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")


class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(Integer, ForeignKey("orders.order_id"), nullable=False)
    user_id = Column(String, nullable=False)       # LINE userId
    user_name = Column(String, nullable=False)     # 顯示名稱
    item_id = Column(Integer, ForeignKey("menu_items.item_id"), nullable=False)
    quantity = Column(Integer, nullable=False, default=1)  # 數量
    note = Column(Text, nullable=True)             # 備註，如「少冰」
    created_at = Column(DateTime(timezone=True), default=now_utc)

    order = relationship("Order", back_populates="order_items")
    item = relationship("MenuItem")