from collections.abc import Iterator
from datetime import date, timedelta
from math import ceil
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models.entities import (
    Audit, CashMovement, CashSession, Customer, Order, OrderItem, Payable,
    Product, Receivable, RecipeItem, Stock, StockMovement,
)
from utils.clock import local_now, local_today


STATUSES = ("Recebido", "Em preparo", "Pronto", "Entregue", "Finalizado")


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


def _validate_stock(session: Session, required: dict[int, float]) -> None:
    for product_id, quantity in required.items():
        stock = session.scalar(select(Stock).where(Stock.product_id == product_id))
        product = session.get(Product, product_id)
        if stock is None or stock.quantity < quantity:
            raise ValueError(f"Estoque insuficiente: {product.name if product else 'produto/ingrediente'}.")


def create_order(session: Session, items: list[dict], customer_name: str = "", phone: str = "", notes: str = "",
                 responsible: str = "SISTEMA_HOMOLOGACAO") -> Order:
    if not items:
        raise ValueError("Adicione ao menos um item ao pedido.")
    requested: dict[int, int] = {}
    total = 0.0
    for entry in items:
        product = session.get(Product, int(entry["product_id"]))
        quantity = int(entry["quantity"])
        if product is None or not product.active or quantity < 1:
            raise ValueError("Produto ou quantidade inválida.")
        requested[product.id] = requested.get(product.id, 0) + quantity
        total += product.sale_price * quantity
    _validate_stock(session, _stock_requirements(session, requested))
    customer = None
    if customer_name.strip() or phone.strip():
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
    audit(session, "Pedido criado", f"Pedido #{order.id} | Total R$ {total:.2f}", responsible)
    session.commit()
    return order


def update_order_status(session: Session, order: Order, new_status: str,
                        responsible: str = "SISTEMA_HOMOLOGACAO") -> None:
    if new_status not in STATUSES:
        raise ValueError("Status de pedido inválido.")
    next_status = {"Recebido": "Em preparo", "Em preparo": "Pronto",
                   "Pronto": "Entregue", "Entregue": "Finalizado"}.get(order.status)
    if new_status != next_status:
        raise ValueError(f"O próximo status permitido é {next_status or 'nenhum'}.")
    if new_status == "Em preparo" and order.started_at is None:
        order_items = session.scalars(select(OrderItem).where(OrderItem.order_id == order.id)).all()
        product_quantities: dict[int, int] = {}
        for item in order_items:
            product_quantities[item.product_id] = product_quantities.get(item.product_id, 0) + item.quantity
        required_stock = _stock_requirements(session, product_quantities)
        _validate_stock(session, required_stock)
        order.started_at = local_now()
        for ingredient_id, required in required_stock.items():
            stock = session.scalar(select(Stock).where(Stock.product_id == ingredient_id))
            stock.quantity -= required
            stock.updated_at = local_now()
            session.add(StockMovement(product_id=ingredient_id, movement_type="Saída", quantity=required,
                                      reason=f"Baixa do pedido #{order.id}", responsible=responsible))
    if new_status == "Pronto" and order.ready_at is None:
        order.ready_at = local_now()
    if new_status == "Entregue" and order.delivered_at is None:
        order.delivered_at = local_now()
    if new_status == "Finalizado" and order.finished_at is None:
        order.finished_at = local_now()
    order.status = new_status
    audit(session, "Status do pedido alterado", f"Pedido #{order.id}: {new_status}", responsible)
    session.commit()


def move_stock(session: Session, product_id: int, movement_type: str, quantity: float, reason: str = "",
               responsible: str = "SISTEMA_HOMOLOGACAO") -> None:
    if quantity <= 0:
        raise ValueError("A quantidade deve ser maior que zero.")
    stock = session.scalar(select(Stock).where(Stock.product_id == product_id))
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


def open_cash(session: Session, opening_balance: float, operator: str = "SISTEMA_HOMOLOGACAO") -> CashSession:
    if session.scalar(select(CashSession).where(CashSession.is_open.is_(True))):
        raise ValueError("Já existe um caixa aberto.")
    cash = CashSession(opening_balance=opening_balance, operator=operator)
    session.add(cash)
    audit(session, "Abertura de caixa", f"Saldo inicial R$ {opening_balance:.2f}", operator)
    session.commit()
    return cash


def cash_balance(session: Session, cash: CashSession) -> float:
    movements = session.scalars(select(CashMovement).where(CashMovement.cash_session_id == cash.id)).all()
    balance = cash.opening_balance
    for movement in movements:
        balance += movement.amount if movement.movement_type == "Entrada" else -movement.amount
    return balance


def add_cash_movement(session: Session, cash: CashSession, movement_type: str, method: str,
                      amount: float, description: str = "",
                      responsible: str = "SISTEMA_HOMOLOGACAO") -> None:
    if amount <= 0:
        raise ValueError("O valor deve ser maior que zero.")
    session.add(CashMovement(cash_session_id=cash.id, movement_type=movement_type,
                             method=method, amount=amount, description=description))
    audit(session, f"Movimento de caixa: {movement_type}", f"{method} R$ {amount:.2f} | {description}", responsible)
    session.commit()


def close_cash(session: Session, cash: CashSession) -> float:
    balance = cash_balance(session, cash)
    cash.closing_balance = balance
    cash.closed_at = local_now()
    cash.is_open = False
    audit(session, "Fechamento de caixa", f"Saldo final R$ {balance:.2f}", cash.operator)
    session.commit()
    return balance


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
        func.date(Order.created_at) >= start, func.date(Order.created_at) <= end)).all()
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
