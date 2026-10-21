import random
from datetime import datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.entities import (
    Audit, CashFlow, CashMovement, CashSession, Category, Customer, Ingredient,
    Order, OrderItem, Payable, Product, Receivable, RecipeItem, Stock,
    StockMovement,
)
from services.demo_environment import clear_demo_records, track_demo_records
from utils.clock import local_now, local_today


DEMO_MARKER = "DADOS DE DEMONSTRAÇÃO"

PRODUCTS = (
    ("CAF001", "Café Expresso", "Cafés", 0.75, 7.5, "un"),
    ("CAF002", "Cappuccino", "Cafés", 2.02, 12.0, "un"),
    ("CAF003", "Mocha", "Cafés", 2.35, 15.0, "un"),
    ("LAN001", "Pão de Queijo", "Lanches", 1.2, 5.5, "un"),
    ("SOB001", "Brownie", "Sobremesas", 1.44, 9.0, "un"),
    ("LAN002", "Croissant", "Lanches", 2.1, 8.5, "un"),
)

INGREDIENTS = (
    ("INS001", "Grãos de café", "kg", 60.0, 2.0, 8.0),
    ("INS002", "Leite integral", "L", 5.2, 12.0, 30.0),
    ("INS003", "Pão de queijo congelado", "un", 1.0, 40.0, 120.0),
    ("INS004", "Chocolate", "kg", 18.0, 2.0, 8.0),
    ("INS005", "Croissant congelado", "un", 1.6, 30.0, 90.0),
)

RECIPES = {
    "CAF001": (("INS001", 0.012),),
    "CAF002": (("INS001", 0.018), ("INS002", 0.18)),
    "CAF003": (("INS001", 0.015), ("INS002", 0.15), ("INS004", 0.025)),
    "LAN001": (("INS003", 1.0),),
    "SOB001": (("INS004", 0.08),),
    "LAN002": (("INS005", 1.0),),
}


def populate_demo_data(session: Session) -> dict[str, int]:
    try:
        clear_demo_records(session)
        _ensure_catalog_is_available(session)
        with track_demo_records(session):
            return _generate_demo_data(session)
    finally:
        if session.in_transaction():
            session.rollback()


def _ensure_catalog_is_available(session: Session) -> None:
    category_names = ("Cafés", "Lanches", "Sobremesas", "Insumos")
    product_codes = tuple(code for code, *_ in PRODUCTS) + tuple(
        code for code, *_ in INGREDIENTS
    )
    existing_categories = set(session.scalars(
        select(Category.name).where(Category.name.in_(category_names))
    ))
    existing_codes = set(session.scalars(
        select(Product.code).where(Product.code.in_(product_codes))
    ))
    if existing_categories or existing_codes:
        conflicts = sorted(existing_categories | existing_codes)
        raise ValueError(
            "A geração foi bloqueada para preservar registros sem marca demo=True "
            f"que conflitam com o catálogo demonstrativo: {', '.join(conflicts)}."
        )


def _generate_demo_data(session: Session) -> dict[str, int]:
    rng = random.Random(20261020)
    today = local_today()
    now = local_now()
    start = today - timedelta(days=89)

    categories = {name: Category(name=name) for name in ("Cafés", "Lanches", "Sobremesas", "Insumos")}
    session.add_all(categories.values())
    session.flush()

    products_by_code = {}
    for code, name, category, cost, price, unit in PRODUCTS:
        product = Product(code=code, name=name, category_id=categories[category].id,
                          unit=unit, cost_price=cost, sale_price=price, active=True)
        session.add(product)
        products_by_code[code] = product

    ingredients_by_code = {}
    for code, name, unit, cost, initial, minimum in INGREDIENTS:
        product = Product(code=code, name=name, category_id=categories["Insumos"].id,
                          unit=unit, cost_price=cost, sale_price=0, active=True)
        session.add(product)
        ingredients_by_code[code] = product
    session.flush()

    stock_by_code = {}
    stock_quantity = {}
    for code, name, unit, cost, initial, minimum in INGREDIENTS:
        product = ingredients_by_code[code]
        session.add(Ingredient(product_id=product.id, name=name, unit=unit))
        stock = Stock(product_id=product.id, quantity=initial, minimum_quantity=minimum)
        session.add(stock)
        stock_by_code[code] = stock
        stock_quantity[code] = initial
        session.add(StockMovement(
            product_id=product.id, movement_type="Entrada", quantity=initial,
            reason=f"{DEMO_MARKER} · saldo inicial",
            responsible=DEMO_MARKER,
            created_at=datetime.combine(start - timedelta(days=1), time(7, 0)),
        ))

    for product_code, ingredients in RECIPES.items():
        for ingredient_code, quantity in ingredients:
            session.add(RecipeItem(
                product_id=products_by_code[product_code].id,
                ingredient_id=ingredients_by_code[ingredient_code].id,
                quantity=quantity,
            ))

    customers = [
        Customer(name=name, phone=f"(11) 9{index:03d}-{index * 37 % 10000:04d}",
                 notes=f"{DEMO_MARKER} · cliente recorrente")
        for index, name in enumerate(
            ("Ana Souza", "Bruno Lima", "Carla Mendes", "Diego Alves", "Elisa Rocha",
             "Felipe Costa", "Gabi Nunes", "Heitor Silva", "Iara Santos", "João Prado"),
            start=1,
        )
    ]
    session.add_all(customers)
    session.flush()

    recipe_quantities = {
        products_by_code[product_code].id: [
            (ingredients_by_code[ingredient_code].id, quantity)
            for ingredient_code, quantity in ingredients
        ]
        for product_code, ingredients in RECIPES.items()
    }
    product_weights = (0.18, 0.24, 0.12, 0.20, 0.13, 0.13)
    product_list = [products_by_code[code] for code, *_ in PRODUCTS]
    stock_consumption: dict[str, float] = {code: 0.0 for code, *_ in INGREDIENTS}
    total_orders = 0
    total_items = 0
    previous_cash_balance = 300.0
    cash_sessions = 0
    stock_movement_count = len(INGREDIENTS)

    for day_offset in range(90):
        business_day = start + timedelta(days=day_offset)
        day_start = datetime.combine(business_day, time(7, 0))
        day_end = datetime.combine(business_day, time(22, 0))
        cash = CashSession(
            operator=f"{DEMO_MARKER} · Operador",
            opening_balance=previous_cash_balance,
            opened_at=day_start,
            is_open=business_day == today,
        )
        session.add(cash)
        session.flush()
        cash_sessions += 1

        order_count = rng.randint(24, 34) if business_day.weekday() >= 5 else rng.randint(15, 25)
        if business_day == today:
            order_count = rng.randint(9, 15) if now.hour >= 7 else 0
        daily_revenue = 0.0
        daily_consumption: dict[int, float] = {}
        for order_index in range(order_count):
            business_hours = list(range(7, 22))
            hourly_weights = (1, 2, 3, 5, 7, 6, 4, 3, 4, 6, 7, 5, 3, 2, 1)
            if business_day == today:
                last_hour = min(21, max(7, now.hour))
                business_hours = business_hours[:last_hour - 6]
                hourly_weights = hourly_weights[:len(business_hours)]
            hour = rng.choices(business_hours, weights=hourly_weights, k=1)[0]
            latest_minute = now.minute if business_day == today and hour == now.hour else 59
            minute = rng.randint(0, latest_minute)
            latest_second = now.second if business_day == today and hour == now.hour and minute == now.minute else 59
            created_at = datetime.combine(
                business_day, time(hour, minute, rng.randint(0, latest_second))
            )
            selected_products = rng.choices(product_list, weights=product_weights, k=rng.choices((1, 2, 3), (0.68, 0.27, 0.05))[0])
            order = Order(
                customer_id=rng.choice(customers).id if rng.random() < 0.72 else None,
                notes=f"{DEMO_MARKER} · pedido",
                status="Finalizado",
                created_at=created_at,
            )
            is_active_today = business_day == today and order_index >= order_count - 3
            if is_active_today:
                status = ("Recebido", "Em preparo", "Pronto")[order_index - (order_count - 3)]
                order.status = status
                if status in ("Em preparo", "Pronto"):
                    order.started_at = created_at + timedelta(minutes=3)
                if status == "Pronto":
                    order.ready_at = order.started_at + timedelta(minutes=rng.randint(7, 16))
            else:
                order.started_at = created_at + timedelta(minutes=rng.randint(2, 8))
                order.ready_at = order.started_at + timedelta(minutes=rng.randint(5, 19))
                order.delivered_at = order.ready_at + timedelta(minutes=rng.randint(2, 12))
                if rng.random() < 0.9:
                    order.finished_at = order.delivered_at + timedelta(minutes=rng.randint(1, 8))
                    order.status = "Finalizado"
                else:
                    order.status = "Entregue"
            if business_day == today:
                for timestamp_field in ("started_at", "ready_at", "delivered_at", "finished_at"):
                    timestamp = getattr(order, timestamp_field)
                    if timestamp is not None and timestamp > now:
                        setattr(order, timestamp_field, now)
            session.add(order)
            session.flush()

            order_total = 0.0
            for product in selected_products:
                quantity = 2 if rng.random() < 0.18 else 1
                session.add(OrderItem(
                    order_id=order.id, product_id=product.id, quantity=quantity,
                    unit_price=product.sale_price,
                    notes=f"{DEMO_MARKER} · sem açúcar" if rng.random() < 0.06 else "",
                ))
                order_total += product.sale_price * quantity
                total_items += quantity
                for ingredient_id, amount in recipe_quantities[product.id]:
                    daily_consumption[ingredient_id] = daily_consumption.get(ingredient_id, 0.0) + amount * quantity
            order.total = order_total
            daily_revenue += order_total
            total_orders += 1

        for code, product in ingredients_by_code.items():
            used = daily_consumption.get(product.id, 0.0)
            stock_consumption[code] += used
            if used <= 0:
                continue
            stock = stock_by_code[code]
            if stock_quantity[code] < used:
                restock = max(stock.minimum_quantity, used * 2)
                stock_quantity[code] += restock
                session.add(StockMovement(
                    product_id=product.id, movement_type="Entrada", quantity=restock,
                    reason=f"{DEMO_MARKER} · reposição",
                    responsible=DEMO_MARKER,
                    created_at=datetime.combine(business_day, time(6, 30)),
                ))
                stock_movement_count += 1
            stock_quantity[code] -= used
            stock.quantity = stock_quantity[code]
            stock.updated_at = day_end
            session.add(StockMovement(
                product_id=product.id, movement_type="Saída", quantity=used,
                reason=f"{DEMO_MARKER} · consumo diário",
                responsible=DEMO_MARKER,
                created_at=min(day_end, now) if business_day == today else day_end,
            ))
            stock_movement_count += 1

        cash_expense = round(daily_revenue * rng.uniform(0.06, 0.12), 2)
        pix_amount = round(daily_revenue * 0.54, 2)
        card_amount = round(daily_revenue - pix_amount, 2)
        session.add_all((
            CashMovement(
                cash_session_id=cash.id, movement_type="Entrada", method="Pix",
                amount=pix_amount,
                description=f"{DEMO_MARKER} · recebimentos Pix",
                created_at=min(datetime.combine(business_day, time(18, 0)), now)
                if business_day == today else datetime.combine(business_day, time(18, 0)),
            ),
            CashMovement(
                cash_session_id=cash.id, movement_type="Entrada", method="Crédito",
                amount=card_amount,
                description=f"{DEMO_MARKER} · recebimentos cartão",
                created_at=min(datetime.combine(business_day, time(19, 0)), now)
                if business_day == today else datetime.combine(business_day, time(19, 0)),
            ),
            CashMovement(
                cash_session_id=cash.id, movement_type="Saída", method="Despesa",
                amount=cash_expense,
                description=f"{DEMO_MARKER} · despesas operacionais",
                created_at=min(datetime.combine(business_day, time(20, 0)), now)
                if business_day == today else datetime.combine(business_day, time(20, 0)),
            ),
        ))
        net_day = daily_revenue - cash_expense
        if business_day < today:
            cash.closing_balance = previous_cash_balance + net_day
            cash.closed_at = day_end
            previous_cash_balance = cash.closing_balance
        else:
            previous_cash_balance += net_day
        session.add_all((
            CashFlow(reference_date=business_day, entry_type="Entrada", amount=daily_revenue,
                     description=f"{DEMO_MARKER} · vendas do dia"),
            CashFlow(reference_date=business_day, entry_type="Saída", amount=cash_expense,
                     description=f"{DEMO_MARKER} · despesas operacionais"),
        ))

    for index in range(24):
        due_date = start + timedelta(days=3 + index * 4)
        amount = round(rng.uniform(380, 2600), 2)
        paid = due_date < today - timedelta(days=3) and index % 4 != 0
        session.add(Payable(
            description=f"{DEMO_MARKER} · {('Insumos', 'Aluguel', 'Energia', 'Internet')[index % 4]} #{index + 1}",
            category=("Insumos", "Aluguel", "Energia", "Internet")[index % 4],
            amount=amount,
            competence=due_date.replace(day=1),
            due_date=due_date,
            status="Pago" if paid else "Aberto" if due_date >= today else "Vencido",
            paid_at=datetime.combine(due_date, time(14, 0)) if paid else None,
        ))
    for index in range(12):
        due_date = start + timedelta(days=7 + index * 7)
        received = due_date < today - timedelta(days=5) and index % 3 != 0
        session.add(Receivable(
            description=f"{DEMO_MARKER} · recebível de cartão #{index + 1}",
            amount=round(rng.uniform(450, 2100), 2),
            due_date=due_date,
            status="Recebido" if received else "Aberto",
            received_at=datetime.combine(due_date, time(16, 0)) if received else None,
        ))

    session.add(Audit(
        responsible=DEMO_MARKER,
        action="Dados de demonstração gerados",
        details=f"Período: {start:%d/%m/%Y} a {today:%d/%m/%Y} · {total_orders} pedidos · {total_items} itens",
        created_at=local_now(),
    ))
    session.commit()
    return {
        "orders": total_orders,
        "items": total_items,
        "cash_sessions": cash_sessions,
        "stock_movements": stock_movement_count,
        "days": 90,
    }
