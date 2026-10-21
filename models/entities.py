from datetime import datetime
from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database.connection import Base
from utils.clock import local_now


class Role(Base):
    __tablename__ = "perfis"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(40), unique=True)
    description: Mapped[str] = mapped_column(String(180), default="")


class Permission(Base):
    __tablename__ = "permissoes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(80), unique=True)
    description: Mapped[str] = mapped_column(String(180), default="")


class RolePermission(Base):
    __tablename__ = "perfil_permissoes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("perfis.id"), index=True)
    permission_id: Mapped[int] = mapped_column(ForeignKey("permissoes.id"), index=True)


class User(Base):
    __tablename__ = "usuarios"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255), default="")
    role_id: Mapped[int | None] = mapped_column(ForeignKey("perfis.id"), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=local_now)


class Category(Base):
    __tablename__ = "categorias"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Product(Base):
    __tablename__ = "produtos"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(140), index=True)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categorias.id"), nullable=True)
    unit: Mapped[str] = mapped_column(String(20), default="un")
    cost_price: Mapped[float] = mapped_column(Float, default=0)
    sale_price: Mapped[float] = mapped_column(Float, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Ingredient(Base):
    __tablename__ = "ingredientes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("produtos.id"), unique=True)
    name: Mapped[str] = mapped_column(String(140))
    unit: Mapped[str] = mapped_column(String(20), default="un")


class Stock(Base):
    __tablename__ = "estoque"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("produtos.id"), unique=True)
    quantity: Mapped[float] = mapped_column(Float, default=0)
    minimum_quantity: Mapped[float] = mapped_column(Float, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=local_now, onupdate=local_now)


class RecipeItem(Base):
    __tablename__ = "ficha_tecnica"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("produtos.id"), index=True)
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("produtos.id"), index=True)
    quantity: Mapped[float] = mapped_column(Float, default=1)


class StockMovement(Base):
    __tablename__ = "movimentacoes_estoque"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("produtos.id"), index=True)
    movement_type: Mapped[str] = mapped_column(String(20))
    quantity: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(String(220), default="")
    responsible: Mapped[str] = mapped_column(String(80), default="SISTEMA_HOMOLOGACAO")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=local_now, index=True)


class Customer(Base):
    __tablename__ = "clientes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str] = mapped_column(String(30), default="")
    notes: Mapped[str] = mapped_column(Text, default="")


class Order(Base):
    __tablename__ = "pedidos"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("clientes.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="Recebido", index=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    total: Mapped[float] = mapped_column(Float, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=local_now, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ready_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class OrderItem(Base):
    __tablename__ = "itens_pedido"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("pedidos.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("produtos.id"))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    unit_price: Mapped[float] = mapped_column(Float)
    notes: Mapped[str] = mapped_column(Text, default="")


class CashSession(Base):
    __tablename__ = "caixa"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    operator: Mapped[str] = mapped_column(String(80), default="SISTEMA_HOMOLOGACAO")
    opening_balance: Mapped[float] = mapped_column(Float, default=0)
    closing_balance: Mapped[float | None] = mapped_column(Float, nullable=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime, default=local_now)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_open: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class CashMovement(Base):
    __tablename__ = "movimentacoes_caixa"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cash_session_id: Mapped[int] = mapped_column(ForeignKey("caixa.id"), index=True)
    movement_type: Mapped[str] = mapped_column(String(20))
    method: Mapped[str] = mapped_column(String(30), default="Dinheiro")
    amount: Mapped[float] = mapped_column(Float)
    description: Mapped[str] = mapped_column(String(220), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=local_now)


class Payable(Base):
    __tablename__ = "contas_pagar"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    description: Mapped[str] = mapped_column(String(180))
    category: Mapped[str] = mapped_column(String(80), default="Diversos")
    amount: Mapped[float] = mapped_column(Float)
    competence: Mapped[Date] = mapped_column(Date)
    due_date: Mapped[Date] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String(20), default="Aberto", index=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Receivable(Base):
    __tablename__ = "contas_receber"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    description: Mapped[str] = mapped_column(String(180))
    amount: Mapped[float] = mapped_column(Float)
    due_date: Mapped[Date] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String(20), default="Aberto", index=True)
    received_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class CashFlow(Base):
    __tablename__ = "fluxo_caixa"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reference_date: Mapped[Date] = mapped_column(Date, index=True)
    entry_type: Mapped[str] = mapped_column(String(20))
    amount: Mapped[float] = mapped_column(Float)
    description: Mapped[str] = mapped_column(String(180), default="")


class Audit(Base):
    __tablename__ = "auditoria"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    responsible: Mapped[str] = mapped_column(String(80), default="SISTEMA_HOMOLOGACAO")
    action: Mapped[str] = mapped_column(String(220))
    details: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=local_now, index=True)


class LoginAudit(Base):
    __tablename__ = "auditoria_login"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(80))
    success: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=local_now)


class DemoRecord(Base):
    __tablename__ = "registros_demo"
    __table_args__ = (UniqueConstraint("entity", "record_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity: Mapped[str] = mapped_column(String(80), index=True)
    record_id: Mapped[int] = mapped_column(Integer)
    demo: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
