import random
from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.entities import (
    Audit, CashFlow, CashMovement, CashSession, Category, Comanda, ComandaOrder,
    Customer, Ingredient, Order, OrderItem, Payable, Product, Receivable,
    RecipeItem, Stock, StockMovement,
)
from services.demo_environment import clear_demo_records, track_demo_records
from utils.clock import local_now, local_today
from utils.money import money_float, money_sum


DEMO_MARKER = "DADOS DE DEMONSTRAÇÃO"
DEMO_DAYS = 90

CATEGORIES = ("Cafés", "Lanches", "Sobremesas", "Bebidas", "Insumos")

# (código, nome, categoria, custo, preço, unidade, peso de popularidade)
PRODUCTS = (
    ("CAF001", "Café Expresso", "Cafés", 0.75, 7.5, "un", 0.16),
    ("CAF002", "Cappuccino", "Cafés", 2.02, 12.0, "un", 0.14),
    ("CAF003", "Mocha", "Cafés", 2.35, 15.0, "un", 0.06),
    ("CAF004", "Café Coado", "Cafés", 0.55, 6.0, "un", 0.09),
    ("CAF005", "Café com Leite", "Cafés", 1.9, 11.0, "un", 0.08),
    ("LAN001", "Pão de Queijo", "Lanches", 1.2, 5.5, "un", 0.12),
    ("LAN002", "Croissant", "Lanches", 2.1, 8.5, "un", 0.07),
    ("LAN003", "Sanduíche Natural", "Lanches", 4.2, 16.0, "un", 0.05),
    ("LAN004", "Torrada com Queijo", "Lanches", 2.2, 10.5, "un", 0.05),
    ("SOB001", "Brownie", "Sobremesas", 1.44, 9.0, "un", 0.06),
    ("SOB002", "Bolo de Cenoura", "Sobremesas", 1.6, 8.5, "un", 0.05),
    ("SOB003", "Cheesecake", "Sobremesas", 3.4, 14.0, "un", 0.03),
    ("BEB001", "Suco de Laranja", "Bebidas", 2.9, 9.5, "un", 0.05),
    ("BEB002", "Água Mineral", "Bebidas", 0.9, 4.5, "un", 0.04),
    ("BEB003", "Chá Gelado", "Bebidas", 1.3, 8.0, "un", 0.03),
)

# (código, nome, unidade, custo, estoque inicial, estoque mínimo)
INGREDIENTS = (
    ("INS001", "Grãos de café", "kg", 60.0, 8.0, 2.0),
    ("INS002", "Leite integral", "L", 5.2, 40.0, 12.0),
    ("INS003", "Pão de queijo congelado", "un", 1.0, 160.0, 40.0),
    ("INS004", "Chocolate", "kg", 18.0, 8.0, 2.0),
    ("INS005", "Croissant congelado", "un", 1.6, 120.0, 30.0),
    ("INS006", "Queijo muçarela", "kg", 36.0, 8.0, 3.0),
    ("INS007", "Laranja", "kg", 4.8, 40.0, 10.0),
    ("INS008", "Pão de forma", "un", 0.45, 150.0, 40.0),
    ("INS009", "Cream cheese", "kg", 42.0, 6.0, 1.5),
)

RECIPES = {
    "CAF001": (("INS001", 0.012),),
    "CAF002": (("INS001", 0.018), ("INS002", 0.18)),
    "CAF003": (("INS001", 0.015), ("INS002", 0.15), ("INS004", 0.025)),
    "CAF004": (("INS001", 0.010),),
    "CAF005": (("INS001", 0.014), ("INS002", 0.22)),
    "LAN001": (("INS003", 1.0),),
    "LAN002": (("INS005", 1.0),),
    "LAN003": (("INS008", 2.0), ("INS006", 0.05)),
    "LAN004": (("INS008", 2.0), ("INS006", 0.04)),
    "SOB001": (("INS004", 0.08),),
    "SOB002": (("INS004", 0.03),),
    "SOB003": (("INS009", 0.06),),
    "BEB001": (("INS007", 0.45),),
}

CUSTOMER_NAMES = (
    "Ana Souza", "Bruno Lima", "Carla Mendes", "Diego Alves", "Elisa Rocha",
    "Felipe Costa", "Gabi Nunes", "Heitor Silva", "Iara Santos", "João Prado",
    "Karina Dias", "Lucas Faria", "Marina Teixeira", "Nelson Barros", "Olívia Campos",
    "Paulo Ribeiro", "Quésia Moura", "Rafael Pires", "Sabrina Lopes", "Tiago Moreira",
    "Úrsula Ferraz", "Vitor Gomes", "Wanda Cardoso", "Yuri Machado",
)

OPERATORS = ("Marina", "Rafael")
CANCEL_REASONS = (
    "Cliente desistiu do pedido", "Pedido duplicado no balcão", "Item indisponível no momento",
)

# (categoria, descrição, valor base, dia de vencimento, variação, competência no mês anterior)
PAYABLE_PLAN = (
    ("Aluguel", "Aluguel do salão", 3200.0, 5, 0.0, False),
    ("Folha de pagamento", "Salários e encargos", 5200.0, 5, 0.02, False),
    ("Energia", "Energia elétrica", 640.0, 10, 0.12, True),
    ("Internet", "Internet e telefonia", 199.9, 12, 0.0, False),
    ("Impostos", "Simples Nacional (DAS)", 1100.0, 20, 0.1, True),
    ("Embalagens e limpeza", "Embalagens e material de limpeza", 420.0, 20, 0.2, False),
    ("Manutenção", "Manutenção de equipamentos", 310.0, 25, 0.4, False),
)

PAYMENT_SHARES = (("Pix", 0.40), ("Crédito", 0.25), ("Débito", 0.15))
HOURLY_WEIGHTS = (1, 2, 3, 5, 7, 6, 4, 3, 4, 6, 7, 5, 3, 2, 1)


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
    product_codes = tuple(item[0] for item in PRODUCTS) + tuple(
        item[0] for item in INGREDIENTS
    )
    existing_categories = set(session.scalars(
        select(Category.name).where(Category.name.in_(CATEGORIES))
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


def _month_starts(first: date, last: date):
    current = first.replace(day=1)
    while current <= last:
        yield current
        current = (current.replace(day=28) + timedelta(days=4)).replace(day=1)


def _order_times(rng, business_day: date, count: int, today: date, now: datetime):
    hours = list(range(7, 22))
    weights = HOURLY_WEIGHTS
    if business_day == today:
        last_hour = min(21, max(7, now.hour))
        hours = hours[:last_hour - 6]
        weights = weights[:len(hours)]
    moments = []
    for _ in range(count):
        hour = rng.choices(hours, weights=weights, k=1)[0]
        latest_minute = now.minute if business_day == today and hour == now.hour else 59
        minute = rng.randint(0, latest_minute)
        latest_second = (
            now.second if business_day == today and hour == now.hour and minute == now.minute else 59
        )
        moments.append(datetime.combine(business_day, time(hour, minute, rng.randint(0, latest_second))))
    return sorted(moments)


def _generate_demo_data(session: Session) -> dict[str, int]:
    rng = random.Random(20261020)
    today = local_today()
    now = local_now()
    start = today - timedelta(days=DEMO_DAYS - 1)

    categories = {name: Category(name=name) for name in CATEGORIES}
    session.add_all(categories.values())
    session.flush()

    products_by_code = {}
    for code, name, category, cost, price, unit, _weight in PRODUCTS:
        product = Product(code=code, name=name, category_id=categories[category].id,
                          unit=unit, cost_price=cost, sale_price=price, active=True)
        session.add(product)
        products_by_code[code] = product

    ingredients_by_code = {}
    for code, name, unit, cost, _initial, _minimum in INGREDIENTS:
        product = Product(code=code, name=name, category_id=categories["Insumos"].id,
                          unit=unit, cost_price=cost, sale_price=0, active=True)
        session.add(product)
        ingredients_by_code[code] = product
    session.flush()

    stock_by_code = {}
    stock_quantity = {}
    initial_lot = {}
    minimum_by_code = {}
    for code, name, unit, _cost, initial, minimum in INGREDIENTS:
        product = ingredients_by_code[code]
        session.add(Ingredient(product_id=product.id, name=name, unit=unit))
        stock = Stock(product_id=product.id, quantity=initial, minimum_quantity=minimum)
        session.add(stock)
        stock_by_code[code] = stock
        stock_quantity[code] = initial
        initial_lot[code] = initial
        minimum_by_code[code] = minimum
        session.add(StockMovement(
            product_id=product.id, movement_type="Entrada", quantity=initial,
            reason=f"{DEMO_MARKER} · saldo inicial",
            responsible=DEMO_MARKER,
            created_at=datetime.combine(start - timedelta(days=1), time(7, 0)),
        ))
    stock_movement_count = len(INGREDIENTS)

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
        for index, name in enumerate(CUSTOMER_NAMES, start=1)
    ]
    session.add_all(customers)
    session.flush()

    recipe_quantities = {
        products_by_code[product_code].id: [
            (ingredient_code, quantity) for ingredient_code, quantity in ingredients
        ]
        for product_code, ingredients in RECIPES.items()
    }
    product_list = [products_by_code[item[0]] for item in PRODUCTS]
    product_weights = [item[6] for item in PRODUCTS]

    totals = {"orders": 0, "cancelled": 0, "items": 0, "comandas": 0, "cash_sessions": 0}
    previous_cash_balance = 300.0
    weekly_credit: dict[int, float] = {}
    audit_count = 0

    for day_offset in range(DEMO_DAYS):
        business_day = start + timedelta(days=day_offset)
        is_today = business_day == today
        day_start = datetime.combine(business_day, time(7, 0))
        day_end = datetime.combine(business_day, time(22, 0))
        operator = f"{DEMO_MARKER} · {OPERATORS[day_offset % 2]}"
        cash = CashSession(operator=operator, opening_balance=previous_cash_balance,
                           opened_at=day_start, is_open=is_today)

        if is_today:
            order_count = rng.randint(14, 22) if now.hour >= 7 else 0
        elif business_day.weekday() >= 5:
            order_count = rng.randint(46, 62)
        else:
            order_count = rng.randint(32, 44)

        built = []
        active_statuses = ("Entregue", "Recebido", "Em preparo", "Em preparo", "Pronto")
        first_active = order_count - len(active_statuses)
        for order_index, created_at in enumerate(_order_times(rng, business_day, order_count, today, now)):
            is_active_today = is_today and order_index >= first_active >= 0
            lines = []
            wanted = rng.choices((1, 2, 3), (0.60, 0.32, 0.08))[0]
            while len(lines) < wanted:
                product = rng.choices(product_list, weights=product_weights, k=1)[0]
                if all(line[0] is not product for line in lines):
                    quantity = 2 if rng.random() < 0.18 else 1
                    note = "sem açúcar" if rng.random() < 0.06 else ""
                    lines.append((product, quantity, note))
            order = Order(
                customer_id=customers[rng.randrange(len(customers))].id
                if is_active_today or rng.random() < 0.72 else None,
                notes=f"{DEMO_MARKER} · pedido",
                created_at=created_at,
                total=money_float(sum(p.sale_price * q for p, q, _ in lines)),
            )
            if is_active_today:
                order.status = active_statuses[order_index - first_active]
                if order.status in ("Em preparo", "Pronto", "Entregue"):
                    order.started_at = created_at + timedelta(minutes=3)
                if order.status in ("Pronto", "Entregue"):
                    order.ready_at = order.started_at + timedelta(minutes=rng.randint(7, 16))
                if order.status == "Entregue":
                    order.delivered_at = order.ready_at + timedelta(minutes=rng.randint(2, 6))
            elif rng.random() < 0.025:
                order.status = "Cancelado"
            else:
                order.started_at = created_at + timedelta(minutes=rng.randint(2, 8))
                order.ready_at = order.started_at + timedelta(minutes=rng.randint(5, 19))
                order.delivered_at = order.ready_at + timedelta(minutes=rng.randint(2, 12))
                order.finished_at = order.delivered_at + timedelta(minutes=rng.randint(1, 8))
                order.status = "Finalizado"
            if is_today:
                for field in ("started_at", "ready_at", "delivered_at", "finished_at"):
                    value = getattr(order, field)
                    if value is not None and value > now:
                        setattr(order, field, now)
            built.append((order, lines))

        groups: dict = {}
        for order, _lines in built:
            if order.status == "Cancelado":
                continue
            key = order.customer_id if order.customer_id is not None else ("anon", id(order))
            groups.setdefault(key, []).append(order)
        comandas = []
        for group in groups.values():
            all_done = all(order.status == "Finalizado" for order in group)
            comandas.append((Comanda(
                customer_id=group[0].customer_id,
                total=float(money_sum(order.total for order in group)),
                status="Fechada" if all_done else "Aberta",
                created_at=min(order.created_at for order in group),
                closed_at=max(order.finished_at for order in group) if all_done else None,
            ), group))

        session.add_all([cash, *(order for order, _ in built), *(c for c, _ in comandas)])
        session.flush()

        daily_consumption: dict[str, float] = {}
        revenue_orders = []
        for order, lines in built:
            cancelled = order.status == "Cancelado"
            for product, quantity, note in lines:
                session.add(OrderItem(
                    order_id=order.id, product_id=product.id, quantity=quantity,
                    unit_price=product.sale_price,
                    notes=f"{DEMO_MARKER} · {note}" if note else "",
                ))
                if cancelled:
                    continue
                totals["items"] += quantity
                for ingredient_code, amount in recipe_quantities.get(product.id, ()):
                    daily_consumption[ingredient_code] = (
                        daily_consumption.get(ingredient_code, 0.0) + amount * quantity
                    )
            if cancelled:
                totals["cancelled"] += 1
                session.add(Audit(
                    responsible=operator, action="Pedido cancelado",
                    details=f"Pedido #{order.id} | {rng.choice(CANCEL_REASONS)}",
                    created_at=order.created_at + timedelta(minutes=2),
                ))
                audit_count += 1
            else:
                revenue_orders.append(order)
        for comanda, group in comandas:
            for order in group:
                session.add(ComandaOrder(comanda_id=comanda.id, order_id=order.id))
        totals["orders"] += len(built)
        totals["comandas"] += len(comandas)

        for code, product in ingredients_by_code.items():
            used = daily_consumption.get(code, 0.0)
            if used > 0 and stock_quantity[code] < max(used, minimum_by_code[code]):
                restock = max(initial_lot[code], used * 3)
                stock_quantity[code] += restock
                session.add(StockMovement(
                    product_id=product.id, movement_type="Entrada", quantity=round(restock, 4),
                    reason=f"{DEMO_MARKER} · compra de reposição", responsible=DEMO_MARKER,
                    created_at=datetime.combine(business_day, time(6, 30)),
                ))
                session.add(Audit(
                    responsible=operator, action="Movimentação de estoque",
                    details=f"{product.name} | Entrada {restock:g} | compra de reposição",
                    created_at=datetime.combine(business_day, time(6, 30)),
                ))
                stock_movement_count += 1
                audit_count += 1
            if used > 0:
                stock_quantity[code] -= used
                session.add(StockMovement(
                    product_id=product.id, movement_type="Saída", quantity=round(used, 4),
                    reason=f"{DEMO_MARKER} · consumo diário", responsible=DEMO_MARKER,
                    created_at=min(day_end, now) if is_today else day_end,
                ))
                stock_movement_count += 1
            if used > 0 and rng.random() < 0.05 and stock_quantity[code] > minimum_by_code[code]:
                loss = round(max(0.01, used * 0.04), 4)
                stock_quantity[code] -= loss
                session.add(StockMovement(
                    product_id=product.id, movement_type="Perda", quantity=loss,
                    reason=f"{DEMO_MARKER} · perda operacional", responsible=DEMO_MARKER,
                    created_at=min(day_end, now) if is_today else day_end,
                ))
                stock_movement_count += 1
            stock = stock_by_code[code]
            stock.quantity = round(stock_quantity[code], 4)
            stock.updated_at = min(day_end, now) if is_today else day_end

        daily_revenue = float(money_sum(order.total for order in revenue_orders))
        amounts = {}
        remaining = daily_revenue
        for method, share in PAYMENT_SHARES:
            amounts[method] = money_float(daily_revenue * share)
            remaining -= amounts[method]
        amounts["Dinheiro"] = money_float(remaining)
        weekly_credit[day_offset // 7] = weekly_credit.get(day_offset // 7, 0.0) + amounts["Crédito"]
        cash_expense = money_float(daily_revenue * rng.uniform(0.03, 0.06))

        def at(hour: int) -> datetime:
            moment = datetime.combine(business_day, time(hour, 0))
            return min(moment, now) if is_today else moment

        session.add_all([
            CashMovement(cash_session_id=cash.id, movement_type="Entrada", method=method,
                         amount=amount, description=f"{DEMO_MARKER} · recebimentos {method}",
                         created_at=at(hour))
            for (method, amount), hour in zip(amounts.items(), (16, 17, 18, 19))
        ])
        session.add(CashMovement(
            cash_session_id=cash.id, movement_type="Saída", method="Despesa", amount=cash_expense,
            description=f"{DEMO_MARKER} · despesas operacionais", created_at=at(20),
        ))
        net_day = money_float(daily_revenue - cash_expense)
        if not is_today:
            cash.closing_balance = money_float(previous_cash_balance + net_day)
            cash.closed_at = day_end
            previous_cash_balance = cash.closing_balance
        else:
            previous_cash_balance = money_float(previous_cash_balance + net_day)
        session.add_all([
            CashFlow(reference_date=business_day, entry_type="Entrada", amount=daily_revenue,
                     description=f"{DEMO_MARKER} · vendas do dia"),
            CashFlow(reference_date=business_day, entry_type="Saída", amount=cash_expense,
                     description=f"{DEMO_MARKER} · despesas operacionais"),
            Audit(responsible=operator, action="Abertura de caixa",
                  details=f"Saldo inicial R$ {cash.opening_balance:.2f}", created_at=day_start),
        ])
        audit_count += 1
        if not is_today:
            session.add(Audit(responsible=operator, action="Fechamento de caixa",
                              details=f"Saldo final R$ {cash.closing_balance:.2f}", created_at=day_end))
            audit_count += 1
        totals["cash_sessions"] += 1
        session.flush()

    # Estoque crítico e em atenção no fim do período, para demonstrar os alertas.
    for code, target_ratio in (("INS004", 0.15), ("INS007", 0.40)):
        loss = round(stock_quantity[code] - minimum_by_code[code] * target_ratio, 4)
        if loss > 0:
            product = ingredients_by_code[code]
            stock_quantity[code] -= loss
            stock_by_code[code].quantity = round(stock_quantity[code], 4)
            stock_by_code[code].updated_at = now
            session.add(StockMovement(
                product_id=product.id, movement_type="Perda", quantity=loss,
                reason=f"{DEMO_MARKER} · validade vencida", responsible=DEMO_MARKER, created_at=now,
            ))
            stock_movement_count += 1

    payable_count = 0
    unpaid_energy_due = max(
        (month.replace(day=PAYABLE_PLAN[2][3]) for month in _month_starts(start, today)
         if month.replace(day=PAYABLE_PLAN[2][3]) < today),
        default=None,
    )
    for month in _month_starts(start, today + timedelta(days=40)):
        for category, label, base, day, spread, previous_month in PAYABLE_PLAN:
            due_date = month.replace(day=day)
            if due_date < start:
                continue
            competence = (month - timedelta(days=1)).replace(day=1) if previous_month else month
            overdue = category == "Energia" and due_date == unpaid_energy_due
            paid = due_date < today and not overdue
            paid_at = datetime.combine(due_date, time(14, 0)) if paid else None
            session.add(Payable(
                description=f"{DEMO_MARKER} · {label} {competence:%m/%Y}",
                category=category,
                amount=money_float(base * (1 + rng.uniform(-spread, spread))),
                competence=competence,
                due_date=due_date,
                status="Pago" if paid else "Vencido" if due_date < today else "Aberto",
                paid_at=paid_at,
            ))
            payable_count += 1
            if paid:
                session.add(Audit(responsible=f"{DEMO_MARKER} · Financeiro", action="Conta paga",
                                  details=f"{label} {competence:%m/%Y}", created_at=paid_at))
                audit_count += 1

    receivable_count = 0
    for block, credit_total in sorted(weekly_credit.items()):
        block_end = start + timedelta(days=block * 7 + 6)
        due_date = block_end + timedelta(days=14)
        received = due_date < today
        session.add(Receivable(
            description=f"{DEMO_MARKER} · recebível de cartão de crédito · semana até {block_end:%d/%m}",
            amount=money_float(credit_total * 0.97), due_date=due_date,
            status="Recebido" if received else "Aberto",
            received_at=datetime.combine(due_date, time(10, 0)) if received else None,
        ))
        receivable_count += 1
    for label, amount, due_date, received in (
        ("Evento corporativo · Empresa Alfa", 2400.0, today + timedelta(days=9), False),
        ("Coffee break · Escritório Beta", 1850.0, start + timedelta(days=40), True),
        ("Encomenda de salgados · Escola Gama", 980.0, today - timedelta(days=6), False),
    ):
        session.add(Receivable(
            description=f"{DEMO_MARKER} · {label}", amount=amount, due_date=due_date,
            status="Recebido" if received else "Aberto",
            received_at=datetime.combine(due_date, time(11, 0)) if received else None,
        ))
        receivable_count += 1

    session.add(Audit(
        responsible=DEMO_MARKER,
        action="Dados de demonstração gerados",
        details=(f"Período: {start:%d/%m/%Y} a {today:%d/%m/%Y} · {totals['orders']} pedidos · "
                 f"{totals['items']} itens"),
        created_at=local_now(),
    ))
    session.commit()
    return {
        "orders": totals["orders"],
        "cancelled_orders": totals["cancelled"],
        "items": totals["items"],
        "comandas": totals["comandas"],
        "cash_sessions": totals["cash_sessions"],
        "stock_movements": stock_movement_count,
        "payables": payable_count,
        "receivables": receivable_count,
        "audits": audit_count + 1,
        "days": DEMO_DAYS,
    }
