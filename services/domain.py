from collections.abc import Iterator
from collections.abc import Callable
from contextlib import nullcontext
from datetime import date, timedelta
from functools import wraps
from math import ceil
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from typing import Concatenate, ParamSpec, TypeVar

from config import MODO_DEMONSTRACAO
from models.entities import (
    Audit, CashMovement, CashSession, Comanda, ComandaOrder, Customer, Order,
    OrderItem, Payable, Product, Receivable, RecipeItem, Stock, StockMovement,
)
from services.demo_environment import track_demo_records
from utils.clock import local_now, local_today
from utils.money import money, money_float, money_sum


STATUSES = ("Recebido", "Em preparo", "Pronto", "Entregue", "Finalizado", "Cancelado")
_P = ParamSpec("_P")
_R = TypeVar("_R")


def _track_demo_mutations(
    function: Callable[Concatenate[Session, _P], _R],
) -> Callable[Concatenate[Session, _P], _R]:
    @wraps(function)
    def wrapper(session: Session, *args: _P.args, **kwargs: _P.kwargs) -> _R:
        tracking = track_demo_records(session) if MODO_DEMONSTRACAO else nullcontext()
        try:
            with tracking:
                return function(session, *args, **kwargs)
        except (ValueError, SQLAlchemyError, KeyError, TypeError):
            if session.in_transaction():
                session.rollback()
            raise

    return wrapper


def audit(session: Session, action: str, details: str = "", responsible: str = "SISTEMA_HOMOLOGACAO") -> None:
    session.add(Audit(responsible=responsible, action=action, details=details))


def stock_level(quantity: float, minimum: float) -> str:
    if quantity <= 0:
        return "Zerado"
    if minimum > 0:
        ratio = quantity / minimum
        if ratio <= .2:
            return "Crítico"
        if ratio < .5:
            return "Atenção"
    return "Adequado"


def _stock_requirements(session: Session, product_quantities: dict[int, int]) -> dict[int, float]:
    required: dict[int, float] = {}
    for product_id, quantity in product_quantities.items():
        recipes = session.scalars(select(RecipeItem).where(RecipeItem.product_id == product_id)).all()
        if recipes:
            for recipe in recipes:
                required[recipe.ingredient_id] = required.get(recipe.ingredient_id, 0) + recipe.quantity * quantity
        else:
            required[product_id] = required.get(product_id, 0) + quantity
    return required


def _products_require_preparation(session: Session, product_ids: set[int]) -> bool:
    if not product_ids:
        return False
    recipes = session.scalars(
        select(RecipeItem).where(RecipeItem.product_id.in_(product_ids))
    ).all()
    if not recipes:
        return False
    return any(recipe.ingredient_id != recipe.product_id for recipe in recipes)


def _consume_order_stock(
    session: Session,
    required_stock: dict[int, float],
    order_id: int,
    responsible: str,
    reason_prefix: str,
) -> None:
    for ingredient_id, required in required_stock.items():
        stock = session.scalar(select(Stock).where(Stock.product_id == ingredient_id))
        stock.quantity -= required
        stock.updated_at = local_now()
        session.add(StockMovement(
            product_id=ingredient_id,
            movement_type="Saída",
            quantity=required,
            reason=f"{reason_prefix} #{order_id}",
            responsible=responsible,
        ))


def _validate_stock(session: Session, required: dict[int, float]) -> None:
    for product_id, quantity in required.items():
        stock = session.scalar(select(Stock).where(Stock.product_id == product_id))
        product = session.get(Product, product_id)
        if stock is None or stock.quantity < quantity:
            raise ValueError(f"Estoque insuficiente: {product.name if product else 'produto/ingrediente'}.")


def _is_postgres(session: Session) -> bool:
    bind = session.get_bind()
    return bool(bind and bind.dialect.name == "postgresql")


def _lock_stocks(session: Session, product_ids: set[int]) -> dict[int, Stock]:
    if not product_ids:
        return {}
    query = select(Stock).where(Stock.product_id.in_(product_ids))
    if _is_postgres(session):
        query = query.with_for_update()
    locked = session.scalars(query).all()
    return {row.product_id: row for row in locked}


def _lock_order(session: Session, order_id: int) -> Order:
    query = select(Order).where(Order.id == order_id)
    if _is_postgres(session):
        query = query.with_for_update()
    locked = session.scalar(query)
    if locked is None:
        raise ValueError("Pedido não encontrado.")
    return locked


def _lock_comanda(session: Session, comanda_id: int) -> Comanda:
    query = select(Comanda).where(Comanda.id == comanda_id)
    if _is_postgres(session):
        query = query.with_for_update()
    locked = session.scalar(query)
    if locked is None:
        raise ValueError("Comanda não encontrada.")
    return locked


def _lock_open_cash(session: Session) -> CashSession | None:
    query = select(CashSession).where(CashSession.is_open.is_(True)).order_by(CashSession.id)
    if _is_postgres(session):
        query = query.with_for_update()
    return session.scalar(query)


@_track_demo_mutations
def create_order(session: Session, items: list[dict], customer_name: str = "", phone: str = "", notes: str = "",
                 responsible: str = "SISTEMA_HOMOLOGACAO",
                 comanda_id: int | None = None) -> Order:
    if not items:
        raise ValueError("Adicione ao menos um item ao pedido.")
    comanda = _lock_comanda(session, comanda_id) if comanda_id is not None else None
    if comanda_id is not None and (comanda is None or comanda.status != "Aberta"):
        raise ValueError("A comanda selecionada não está aberta.")
    if comanda is not None and (customer_name.strip() or phone.strip()):
        raise ValueError("Pedidos vinculados herdam o cliente da comanda.")
    cash = _lock_open_cash(session)
    if cash is None:
        raise ValueError("Caixa fechado. Abra um turno para registrar novos pedidos.")
    requested: dict[int, int] = {}
    total_parts: list[float] = []
    for entry in items:
        product = session.get(Product, int(entry["product_id"]))
        quantity = int(entry["quantity"])
        if product is None or not product.active or quantity < 1:
            raise ValueError("Produto ou quantidade inválida.")
        requested[product.id] = requested.get(product.id, 0) + quantity
        total_parts.append(money_float(money(product.sale_price) * quantity))
    total = money_float(money_sum(total_parts))
    required_stock = _stock_requirements(session, requested)
    locked_stocks = _lock_stocks(session, set(required_stock))
    for product_id, quantity in required_stock.items():
        stock = locked_stocks.get(product_id)
        product = session.get(Product, product_id)
        if stock is None or stock.quantity < quantity:
            raise ValueError(f"Estoque insuficiente: {product.name if product else 'produto/ingrediente'}.")
    requires_preparation = _products_require_preparation(session, set(requested))
    customer = session.get(Customer, comanda.customer_id) if comanda and comanda.customer_id else None
    if comanda is None and (customer_name.strip() or phone.strip()):
        customer = Customer(name=customer_name.strip() or "Cliente", phone=phone.strip())
        session.add(customer)
        session.flush()
    order = Order(customer_id=customer.id if customer else None, notes=notes.strip(), status="Recebido")
    session.add(order)
    session.flush()
    for entry in items:
        product = session.get(Product, int(entry["product_id"]))
        quantity = int(entry["quantity"])
        session.add(OrderItem(order_id=order.id, product_id=product.id, quantity=quantity,
                              unit_price=product.sale_price, notes=entry.get("notes", "")))
    order.total = total
    if comanda is not None:
        session.add(ComandaOrder(comanda_id=comanda.id, order_id=order.id))
        comanda.total += total
    if not requires_preparation:
        now = local_now()
        _consume_order_stock(session, required_stock, order.id, responsible, "Baixa imediata do pedido")
        order.status = "Finalizado"
        order.started_at = now
        order.ready_at = now
        order.delivered_at = now
        order.finished_at = now
        if comanda is None:
            comanda = Comanda(customer_id=order.customer_id, total=order.total)
            session.add(comanda)
            session.flush()
            session.add(ComandaOrder(comanda_id=comanda.id, order_id=order.id))
    audit(session, "Pedido criado", f"Pedido #{order.id} | Total R$ {total:.2f}", responsible)
    session.commit()
    return order


@_track_demo_mutations
def update_order_status(session: Session, order: Order, new_status: str,
                        responsible: str = "SISTEMA_HOMOLOGACAO") -> None:
    locked_order = _lock_order(session, order.id)
    if new_status not in STATUSES:
        raise ValueError("Status de pedido inválido.")
    next_status = {"Recebido": "Em preparo", "Em preparo": "Pronto",
                   "Pronto": "Entregue", "Entregue": "Finalizado"}.get(locked_order.status)
    if new_status != next_status:
        raise ValueError(f"O próximo status permitido é {next_status or 'nenhum'}.")
    if new_status == "Em preparo" and locked_order.started_at is None:
        order_items = session.scalars(select(OrderItem).where(OrderItem.order_id == locked_order.id)).all()
        product_quantities: dict[int, int] = {}
        for item in order_items:
            product_quantities[item.product_id] = product_quantities.get(item.product_id, 0) + item.quantity
        required_stock = _stock_requirements(session, product_quantities)
        _lock_stocks(session, set(required_stock))
        _validate_stock(session, required_stock)
        locked_order.started_at = local_now()
        _consume_order_stock(session, required_stock, locked_order.id, responsible, "Baixa do pedido")
    if new_status == "Pronto" and locked_order.ready_at is None:
        locked_order.ready_at = local_now()
    if new_status == "Entregue" and locked_order.delivered_at is None:
        locked_order.delivered_at = local_now()
    if new_status == "Finalizado" and locked_order.finished_at is None:
        locked_order.finished_at = local_now()
        comanda_order = session.scalar(
            select(ComandaOrder).where(ComandaOrder.order_id == locked_order.id)
        )
        if comanda_order is None:
            comanda = Comanda(customer_id=locked_order.customer_id, total=locked_order.total)
            session.add(comanda)
            session.flush()
            session.add(ComandaOrder(comanda_id=comanda.id, order_id=locked_order.id))
    locked_order.status = new_status
    audit(session, "Status do pedido alterado", f"Pedido #{locked_order.id}: {new_status}", responsible)
    session.commit()


@_track_demo_mutations
def cancel_order(session: Session, order: Order, reason: str,
                responsible: str = "SISTEMA_HOMOLOGACAO") -> None:
    locked_order = _lock_order(session, order.id)
    reason = reason.strip()
    if len(reason) < 5:
        raise ValueError("Informe um motivo com ao menos 5 caracteres.")
    if locked_order.status == "Cancelado":
        raise ValueError("Este pedido já foi cancelado.")
    if locked_order.status == "Finalizado":
        raise ValueError("Pedidos finalizados não podem ser cancelados; registre um estorno.")

    if locked_order.started_at is not None:
        items = session.scalars(select(OrderItem).where(OrderItem.order_id == locked_order.id)).all()
        product_quantities: dict[int, int] = {}
        for item in items:
            product_quantities[item.product_id] = product_quantities.get(item.product_id, 0) + item.quantity
        required_stock = _stock_requirements(session, product_quantities)
        _lock_stocks(session, set(required_stock))
        for product_id, quantity in required_stock.items():
            stock = session.scalar(select(Stock).where(Stock.product_id == product_id))
            if stock is None:
                stock = Stock(product_id=product_id, quantity=0, minimum_quantity=0)
                session.add(stock)
                session.flush()
            stock.quantity += quantity
            stock.updated_at = local_now()
            session.add(StockMovement(
                product_id=product_id,
                movement_type="Entrada",
                quantity=quantity,
                reason=f"Estorno do pedido #{locked_order.id}: {reason}",
                responsible=responsible,
            ))

    comanda_order = session.scalar(select(ComandaOrder).where(ComandaOrder.order_id == locked_order.id))
    if comanda_order is not None:
        comanda = _lock_comanda(session, comanda_order.comanda_id)
        if comanda and comanda.status == "Aberta":
            comanda.total -= locked_order.total

    locked_order.status = "Cancelado"
    audit(session, "Pedido cancelado", f"Pedido #{locked_order.id} | {reason}", responsible)
    session.commit()


@_track_demo_mutations
def close_comanda(
    session: Session,
    comanda: Comanda,
    method: str,
    responsible: str = "SISTEMA_HOMOLOGACAO",
) -> float:
    locked_comanda = _lock_comanda(session, comanda.id)
    if locked_comanda.status != "Aberta":
        raise ValueError("Esta comanda já foi fechada.")
    allowed_methods = ("Dinheiro", "Pix", "Crédito", "Débito")
    if method not in allowed_methods:
        raise ValueError("Forma de pagamento inválida.")
    pending_order = session.scalar(
        select(Order.id)
        .join(ComandaOrder, ComandaOrder.order_id == Order.id)
        .where(
            ComandaOrder.comanda_id == locked_comanda.id,
            Order.status != "Finalizado",
        )
        .limit(1)
    )
    if pending_order is not None:
        raise ValueError("Finalize os pedidos vinculados à comanda antes de fechar a conta.")
    cash = _lock_open_cash(session)
    if cash is None:
        raise ValueError("Abra o caixa antes de receber o pagamento da comanda.")
    if locked_comanda.total <= 0:
        raise ValueError("Não é possível fechar uma comanda sem valor.")

    locked_comanda.status = "Fechada"
    locked_comanda.closed_at = local_now()
    locked_comanda.total = money_float(locked_comanda.total)
    session.add(CashMovement(
        cash_session_id=cash.id,
        movement_type="Entrada",
        method=method,
        amount=locked_comanda.total,
        description=f"Comanda #{locked_comanda.id}",
    ))
    audit(
        session,
        "Comanda fechada",
        f"Comanda #{locked_comanda.id} | {method} | R$ {locked_comanda.total:.2f}",
        responsible,
    )
    total = locked_comanda.total
    session.commit()
    return total


@_track_demo_mutations
def move_stock(session: Session, product_id: int, movement_type: str, quantity: float, reason: str = "",
               responsible: str = "SISTEMA_HOMOLOGACAO") -> None:
    if quantity <= 0:
        raise ValueError("A quantidade deve ser maior que zero.")
    stock_query = select(Stock).where(Stock.product_id == product_id)
    if _is_postgres(session):
        stock_query = stock_query.with_for_update()
    stock = session.scalar(stock_query)
    if stock is None:
        stock = Stock(product_id=product_id, quantity=0, minimum_quantity=0)
        session.add(stock)
        session.flush()
    if movement_type in ("Saída", "Perda"):
        if stock.quantity < quantity:
            raise ValueError("Estoque insuficiente para essa movimentação.")
        stock.quantity -= quantity
    elif movement_type == "Entrada":
        stock.quantity += quantity
    elif movement_type == "Ajuste":
        stock.quantity = quantity
    else:
        raise ValueError("Tipo de movimentação inválido.")
    stock.updated_at = local_now()
    session.add(StockMovement(product_id=product_id, movement_type=movement_type, quantity=quantity, reason=reason,
                              responsible=responsible))
    audit(session, "Movimentação de estoque", f"Produto #{product_id} | {movement_type} {quantity:g} | {reason}", responsible)
    session.commit()


@_track_demo_mutations
def open_cash(session: Session, opening_balance: float, operator: str = "SISTEMA_HOMOLOGACAO") -> CashSession:
    opening_balance = money_float(opening_balance)
    if opening_balance < 0:
        raise ValueError("O saldo inicial não pode ser negativo.")
    if not operator.strip():
        raise ValueError("Informe o operador responsável pelo caixa.")
    if _lock_open_cash(session):
        raise ValueError("Já existe um caixa aberto.")
    cash = CashSession(opening_balance=opening_balance, operator=operator)
    session.add(cash)
    audit(session, "Abertura de caixa", f"Saldo inicial R$ {opening_balance:.2f}", operator)
    session.commit()
    return cash


def cash_balance(session: Session, cash: CashSession) -> float:
    movements = session.scalars(select(CashMovement).where(CashMovement.cash_session_id == cash.id)).all()
    balance = money(cash.opening_balance)
    for movement in movements:
        amount = money(movement.amount)
        balance += amount if movement.movement_type == "Entrada" else -amount
    return money_float(balance)


@_track_demo_mutations
def add_cash_movement(session: Session, cash: CashSession, movement_type: str, method: str,
                      amount: float, description: str = "",
                      responsible: str = "SISTEMA_HOMOLOGACAO") -> None:
    locked_cash_query = select(CashSession).where(CashSession.id == cash.id)
    if _is_postgres(session):
        locked_cash_query = locked_cash_query.with_for_update()
    locked_cash = session.scalar(locked_cash_query)
    if locked_cash is None:
        raise ValueError("Caixa não encontrado.")
    if not locked_cash.is_open:
        raise ValueError("Não é possível movimentar um caixa fechado.")
    if movement_type not in ("Entrada", "Saída"):
        raise ValueError("Tipo de movimento de caixa inválido.")
    if method not in ("Dinheiro", "Pix", "Crédito", "Débito", "Despesa", "Sangria"):
        raise ValueError("Forma de movimento de caixa inválida.")
    if amount <= 0:
        raise ValueError("O valor deve ser maior que zero.")
    amount = money_float(amount)
    session.add(CashMovement(cash_session_id=locked_cash.id, movement_type=movement_type,
                             method=method, amount=amount, description=description))
    audit(session, f"Movimento de caixa: {movement_type}", f"{method} R$ {amount:.2f} | {description}", responsible)
    session.commit()


@_track_demo_mutations
def close_cash(session: Session, cash: CashSession) -> float:
    locked_cash_query = select(CashSession).where(CashSession.id == cash.id)
    if _is_postgres(session):
        locked_cash_query = locked_cash_query.with_for_update()
    locked_cash = session.scalar(locked_cash_query)
    if locked_cash is None:
        raise ValueError("Caixa não encontrado.")
    if not locked_cash.is_open:
        raise ValueError("Este caixa já foi fechado.")
    if session.scalar(select(CashSession.id).where(
        CashSession.id != locked_cash.id,
        CashSession.is_open.is_(True),
    ).limit(1)) is not None:
        raise ValueError("Existe outro caixa aberto. Fechamentos simultâneos são inválidos.")
    balance = cash_balance(session, locked_cash)
    locked_cash.closing_balance = balance
    locked_cash.closed_at = local_now()
    locked_cash.is_open = False
    audit(session, "Fechamento de caixa", f"Saldo final R$ {balance:.2f}", locked_cash.operator)
    session.commit()
    return balance


@_track_demo_mutations
def add_payable(session: Session, description: str, category: str, amount: float,
                competence: date, due_date: date,
                responsible: str = "SISTEMA_HOMOLOGACAO") -> Payable:
    if not description.strip():
        raise ValueError("Informe a descrição da conta.")
    if amount <= 0:
        raise ValueError("O valor da conta deve ser maior que zero.")
    amount = money_float(amount)
    row = Payable(
        description=description.strip(), category=category,
        amount=amount, competence=competence, due_date=due_date,
    )
    session.add(row)
    audit(session, "Conta a pagar cadastrada", f"{row.description} · R$ {amount:.2f}", responsible)
    session.commit()
    return row


@_track_demo_mutations
def mark_payable_paid(session: Session, payable: Payable,
                      responsible: str = "SISTEMA_HOMOLOGACAO") -> None:
    payable_query = select(Payable).where(Payable.id == payable.id)
    if _is_postgres(session):
        payable_query = payable_query.with_for_update()
    locked_payable = session.scalar(payable_query)
    if locked_payable is None:
        raise ValueError("Conta não encontrada.")
    if locked_payable.status == "Pago":
        raise ValueError("Esta conta já está paga.")
    locked_payable.status = "Pago"
    locked_payable.paid_at = local_now()
    audit(session, "Conta a pagar quitada", locked_payable.description, responsible)
    session.commit()


@_track_demo_mutations
def add_receivable(session: Session, description: str, amount: float, due_date: date,
                   responsible: str = "SISTEMA_HOMOLOGACAO") -> Receivable:
    if not description.strip():
        raise ValueError("Informe a origem da receita.")
    if amount <= 0:
        raise ValueError("O valor previsto deve ser maior que zero.")
    amount = money_float(amount)
    row = Receivable(description=description.strip(), amount=amount, due_date=due_date)
    session.add(row)
    audit(session, "Receita prevista cadastrada", f"{row.description} · R$ {amount:.2f}", responsible)
    session.commit()
    return row


@_track_demo_mutations
def mark_receivable_received(session: Session, receivable: Receivable,
                             responsible: str = "SISTEMA_HOMOLOGACAO") -> None:
    receivable_query = select(Receivable).where(Receivable.id == receivable.id)
    if _is_postgres(session):
        receivable_query = receivable_query.with_for_update()
    locked_receivable = session.scalar(receivable_query)
    if locked_receivable is None:
        raise ValueError("Receita não encontrada.")
    if locked_receivable.status == "Recebido":
        raise ValueError("Esta receita já está recebida.")
    locked_receivable.status = "Recebido"
    locked_receivable.received_at = local_now()
    audit(session, "Receita recebida", locked_receivable.description, responsible)
    session.commit()


def update_overdue_payables(session: Session) -> None:
    today = local_today()
    entries = session.scalars(select(Payable).where(Payable.status == "Aberto", Payable.due_date < today)).all()
    for entry in entries:
        entry.status = "Vencido"
    if entries:
        session.commit()


def purchase_recommendations(session: Session, coverage_days: int = 14) -> list[dict]:
    today = local_today()
    current_start = today - timedelta(days=6)
    previous_start = today - timedelta(days=13)
    previous_end = current_start
    rows = session.execute(select(Product, Stock).join(Stock, Stock.product_id == Product.id)
                           .where(Product.active.is_(True)).order_by(Product.name)).all()
    current_usage = dict(session.execute(select(StockMovement.product_id,
                                                func.sum(StockMovement.quantity))
                                         .where(StockMovement.movement_type.in_(("Saída", "Perda")),
                                                func.date(StockMovement.created_at) >= current_start)
                                         .group_by(StockMovement.product_id)).all())
    previous_usage = dict(session.execute(select(StockMovement.product_id,
                                                 func.sum(StockMovement.quantity))
                                          .where(StockMovement.movement_type.in_(("Saída", "Perda")),
                                                 func.date(StockMovement.created_at) >= previous_start,
                                                 func.date(StockMovement.created_at) < previous_end)
                                          .group_by(StockMovement.product_id)).all())
    recommendations = []
    for product, stock in rows:
        recent_quantity = current_usage.get(product.id, 0) or 0
        previous_quantity = previous_usage.get(product.id, 0) or 0
        current_average = float(recent_quantity) / 7
        previous_average = float(previous_quantity) / 7
        if current_average and previous_average:
            daily_average = current_average * .7 + previous_average * .3
            change = (current_average - previous_average) / previous_average
            trend = "consumo acelerou" if change >= .1 else "consumo reduziu" if change <= -.1 else "consumo estável"
        else:
            daily_average = current_average or previous_average
            trend = "consumo dos últimos 7 dias" if current_average else "histórico recente de 14 dias"
        days_remaining = stock.quantity / daily_average if daily_average else None
        minimum = stock.minimum_quantity
        needs_action = stock.quantity <= 0 or (minimum > 0 and stock.quantity < minimum) or (
            days_remaining is not None and days_remaining <= coverage_days)
        target_quantity = max(minimum * 2, daily_average * coverage_days)
        suggested_quantity = max(0, ceil(target_quantity - stock.quantity))
        if needs_action and suggested_quantity == 0:
            suggested_quantity = 1
        if not daily_average:
            reason = "Sem saídas recentes; recomendação baseada em duas vezes o estoque mínimo."
        elif previous_average:
            reason = f"Média ponderada dos últimos 14 dias; {trend} na semana atual."
        else:
            reason = "Consumo observado nos últimos 7 dias."
        recommendations.append({
            "product": product,
            "stock": stock,
            "daily_average": daily_average,
            "days_remaining": days_remaining,
            "suggested_quantity": suggested_quantity,
            "reason": reason,
            "needs_action": needs_action,
        })
    recommendations.sort(key=lambda item: (
        not item["needs_action"],
        item["days_remaining"] if item["days_remaining"] is not None else float("inf"),
        item["product"].name.casefold(),
    ))
    return recommendations


def cmv_for_period(session: Session, start: date, end: date) -> dict[str, float]:
    items = session.scalars(select(OrderItem).join(Order, Order.id == OrderItem.order_id).where(
        func.date(Order.created_at) >= start, func.date(Order.created_at) <= end,
        Order.status != "Cancelado")).all()
    if not items:
        return {"revenue": 0.0, "cost": 0.0, "ratio": 0.0}
    product_ids = {item.product_id for item in items}
    unit_costs = product_unit_costs(session, product_ids)
    revenue = sum(item.quantity * item.unit_price for item in items)
    cost = sum(item.quantity * unit_costs.get(item.product_id, 0) for item in items)
    return {"revenue": revenue, "cost": cost, "ratio": cost / revenue if revenue else 0.0}


def product_unit_costs(session: Session, product_ids: set[int]) -> dict[int, float]:
    if not product_ids:
        return {}
    products = {product.id: product for product in session.scalars(
        select(Product).where(Product.id.in_(product_ids))).all()}
    recipes = session.scalars(select(RecipeItem).where(RecipeItem.product_id.in_(product_ids))).all()
    recipes_by_product: dict[int, list[RecipeItem]] = {}
    ingredient_ids = set()
    for recipe in recipes:
        recipes_by_product.setdefault(recipe.product_id, []).append(recipe)
        ingredient_ids.add(recipe.ingredient_id)
    ingredient_costs = {product.id: product.cost_price for product in session.scalars(
        select(Product).where(Product.id.in_(ingredient_ids))).all()} if ingredient_ids else {}
    unit_costs = {product_id: product.cost_price for product_id, product in products.items()}
    for product_id, product_recipes in recipes_by_product.items():
        unit_costs[product_id] = sum(recipe.quantity * ingredient_costs.get(recipe.ingredient_id, 0)
                                     for recipe in product_recipes)
    return unit_costs


def projected_cash(session: Session, days: int) -> Iterator[dict[str, date | float]]:
    today = local_today()
    latest_cash = session.scalar(select(CashSession).order_by(CashSession.opened_at.desc()).limit(1))
    start_balance = cash_balance(session, latest_cash) if latest_cash and latest_cash.is_open else (latest_cash.closing_balance or 0 if latest_cash else 0)
    balance = float(start_balance)
    payable_rows = session.scalars(select(Payable).where(Payable.status.in_(("Aberto", "Vencido")),
                                                          Payable.due_date <= today + timedelta(days=days))).all()
    due_by_date: dict[date, float] = {}
    for payable in payable_rows:
        due_by_date[payable.due_date] = due_by_date.get(payable.due_date, 0) - payable.amount
    receivables = session.scalars(select(Receivable).where(Receivable.status == "Aberto",
                                                           Receivable.due_date <= today + timedelta(days=days))).all()
    for receivable in receivables:
        due_by_date[receivable.due_date] = due_by_date.get(receivable.due_date, 0) + receivable.amount
    for offset in range(1, days + 1):
        current = today + timedelta(days=offset)
        balance += due_by_date.get(current, 0)
        yield {"Data": current, "Saldo projetado": balance}
