from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from database.connection import SessionLocal
from models.entities import (
    Audit, CashFlow, CashMovement, CashSession, Category, Comanda, ComandaOrder,
    Customer, DemoRecord, Ingredient, Order, OrderItem, Payable, Product,
    Receivable, RecipeItem, Stock, StockMovement,
)
from services.demo_data import populate_demo_data
from services.demo_environment import clear_demo_records
from utils.clock import local_today
from utils.money import money

TOLERANCE = Decimal("0.01")

# Tabelas de negócio cujos registros reais impedem a carga demo (evita misturar os dados).
_BUSINESS_MODELS = (Category, Product, Customer, Order, CashSession, Payable, Receivable)


def _demo_ids(session: Session, entity: str) -> set[int]:
    return set(session.scalars(
        select(DemoRecord.record_id).where(DemoRecord.entity == entity, DemoRecord.demo.is_(True))
    ))


def contar_registros_demo(session: Session) -> dict[str, int]:
    """Quantidade de registros marcados como demonstração, por tabela."""
    rows = session.execute(
        select(DemoRecord.entity, func.count(DemoRecord.id))
        .where(DemoRecord.demo.is_(True)).group_by(DemoRecord.entity)
    ).all()
    return dict(sorted((entity, count) for entity, count in rows))


def registros_reais_por_tabela(session: Session) -> dict[str, int]:
    """Registros que NÃO são demonstração nas tabelas de negócio."""
    result = {}
    for model in _BUSINESS_MODELS:
        total = session.scalar(select(func.count(model.id))) or 0
        marked = session.scalar(
            select(func.count(DemoRecord.id)).where(
                DemoRecord.entity == model.__tablename__, DemoRecord.demo.is_(True))
        ) or 0
        if total - marked:
            result[model.__tablename__] = total - marked
    return result


def carregar_dados_demo(session: Session | None = None) -> dict:
    """Gera a base demonstrativa, valida a integridade e devolve o resumo."""
    owns_session = session is None
    session = session or SessionLocal()
    try:
        real = registros_reais_por_tabela(session)
        if real:
            raise ValueError(
                "Carga demo bloqueada: o banco já tem dados reais em "
                + ", ".join(f"{table} ({count})" for table, count in real.items())
                + ". Use um banco sem dados operacionais."
            )
        generated = populate_demo_data(session)
        checks = validar_dados_demo(session)
        return {
            "gerado": generated,
            "por_tabela": contar_registros_demo(session),
            "validacao": checks,
        }
    finally:
        if owns_session:
            session.close()


def limpar_dados_demo(session: Session | None = None) -> dict:
    """Remove somente os registros marcados como demonstração.

    Preserva estrutura, usuários, perfis, permissões, configurações, auditoria de login
    e qualquer registro real. A limpeza é bloqueada se algum registro real referenciar
    dados demo. Tudo ocorre em uma única transação.
    """
    owns_session = session is None
    session = session or SessionLocal()
    try:
        before = contar_registros_demo(session)
        deleted = clear_demo_records(session)
        session.commit()
        return {"removidos": deleted, "por_tabela": before}
    except Exception:
        session.rollback()
        raise
    finally:
        if owns_session:
            session.close()


def _check(results: list, name: str, problems: list[str]) -> None:
    results.append({
        "verificacao": name,
        "ok": not problems,
        "detalhe": "OK" if not problems else f"{len(problems)} problema(s): " + "; ".join(problems[:3]),
    })


def _day(value) -> date:
    return value.date() if isinstance(value, datetime) else value


def validar_dados_demo(session: Session) -> list[dict]:
    """Confere a consistência interna da base demonstrativa."""
    results: list[dict] = []
    today = local_today()
    order_ids = _demo_ids(session, "pedidos")
    orders = {
        order.id: order for order in session.scalars(select(Order)) if order.id in order_ids
    }

    dangling = []
    for model in (Category, Product, Customer, Order, OrderItem, Comanda, ComandaOrder, CashSession,
                  CashMovement, CashFlow, StockMovement, Stock, Ingredient, RecipeItem, Payable,
                  Receivable, Audit):
        existing = set(session.scalars(select(model.id)))
        missing = _demo_ids(session, model.__tablename__) - existing
        if missing:
            dangling.append(f"{model.__tablename__}: {len(missing)}")
    _check(results, "Marcadores demo apontam para registros existentes", dangling)

    items_by_order: dict[int, list[OrderItem]] = defaultdict(list)
    product_ids = {product_id for product_id in session.scalars(select(Product.id))}
    orphan_items = []
    for item in session.scalars(select(OrderItem)):
        if item.order_id in orders:
            items_by_order[item.order_id].append(item)
            if item.product_id not in product_ids:
                orphan_items.append(f"item {item.id}")
    _check(results, "Itens de pedido ligados a produtos existentes", orphan_items)

    total_problems = []
    for order in orders.values():
        expected = sum((money(i.unit_price) * i.quantity for i in items_by_order[order.id]), Decimal("0"))
        if not items_by_order[order.id] or abs(money(order.total) - money(expected)) > TOLERANCE:
            total_problems.append(f"pedido {order.id}")
    _check(results, "Total do pedido = soma dos itens", total_problems)

    status_problems = []
    for order in orders.values():
        if order.status == "Finalizado" and order.finished_at is None:
            status_problems.append(f"pedido {order.id} sem finished_at")
        if order.started_at and order.started_at < order.created_at:
            status_problems.append(f"pedido {order.id} iniciado antes de criado")
        if order.ready_at and order.started_at and order.ready_at < order.started_at:
            status_problems.append(f"pedido {order.id} pronto antes de iniciar")
        if order.status == "Cancelado" and order.started_at is not None:
            status_problems.append(f"pedido {order.id} cancelado após início")
    _check(results, "Status e horários dos pedidos coerentes", status_problems)

    link_problems = []
    comanda_ids = _demo_ids(session, "comandas")
    comandas = {c.id: c for c in session.scalars(select(Comanda)) if c.id in comanda_ids}
    linked: dict[int, list[int]] = defaultdict(list)
    link_count: dict[int, int] = defaultdict(int)
    for link in session.scalars(select(ComandaOrder)):
        if link.comanda_id in comandas:
            linked[link.comanda_id].append(link.order_id)
            link_count[link.order_id] += 1
    for order in orders.values():
        expected_links = 0 if order.status == "Cancelado" else 1
        if link_count[order.id] != expected_links:
            link_problems.append(f"pedido {order.id}")
    for comanda in comandas.values():
        total = sum((money(orders[o].total) for o in linked[comanda.id] if o in orders), Decimal("0"))
        if abs(money(comanda.total) - total) > TOLERANCE:
            link_problems.append(f"comanda {comanda.id} total divergente")
        if comanda.status == "Fechada" and comanda.closed_at is None:
            link_problems.append(f"comanda {comanda.id} fechada sem closed_at")
    _check(results, "Comandas: vínculos e totais", link_problems)

    cash_ids = _demo_ids(session, "caixa")
    sessions = sorted(
        (c for c in session.scalars(select(CashSession)) if c.id in cash_ids),
        key=lambda c: c.opened_at,
    )
    movement_ids = _demo_ids(session, "movimentacoes_caixa")
    entries: dict[int, Decimal] = defaultdict(Decimal)
    exits: dict[int, Decimal] = defaultdict(Decimal)
    for movement in session.scalars(select(CashMovement)):
        if movement.id in movement_ids:
            target = entries if movement.movement_type == "Entrada" else exits
            target[movement.cash_session_id] += money(movement.amount)
    cash_problems = []
    previous = None
    for cash in sessions:
        if not cash.is_open:
            expected = money(cash.opening_balance) + entries[cash.id] - exits[cash.id]
            if cash.closing_balance is None or abs(money(cash.closing_balance) - expected) > TOLERANCE:
                cash_problems.append(f"caixa {cash.id} saldo final divergente")
            if cash.closed_at is None:
                cash_problems.append(f"caixa {cash.id} sem closed_at")
        if previous is not None and previous.closing_balance is not None:
            if abs(money(cash.opening_balance) - money(previous.closing_balance)) > TOLERANCE:
                cash_problems.append(f"caixa {cash.id} abertura difere do fechamento anterior")
        previous = cash
    if sum(1 for cash in sessions if cash.is_open) > 1:
        cash_problems.append("mais de um caixa aberto")
    _check(results, "Caixa: saldos e continuidade entre turnos", cash_problems)

    revenue_by_day: dict[date, Decimal] = defaultdict(Decimal)
    for order in orders.values():
        if order.status != "Cancelado":
            revenue_by_day[_day(order.created_at)] += money(order.total)
    entries_by_day: dict[date, Decimal] = defaultdict(Decimal)
    for cash in sessions:
        entries_by_day[_day(cash.opened_at)] += entries[cash.id]
    flow_ids = _demo_ids(session, "fluxo_caixa")
    flow_by_day: dict[date, Decimal] = defaultdict(Decimal)
    for flow in session.scalars(select(CashFlow)):
        if flow.id in flow_ids and flow.entry_type == "Entrada":
            flow_by_day[_day(flow.reference_date)] += money(flow.amount)
    revenue_problems = []
    for day in sorted(set(revenue_by_day) | set(entries_by_day) | set(flow_by_day)):
        values = (revenue_by_day[day], entries_by_day[day], flow_by_day[day])
        if max(values) - min(values) > TOLERANCE:
            revenue_problems.append(f"{day:%d/%m/%Y}")
    _check(results, "Receita: pedidos = entradas do caixa = fluxo de caixa", revenue_problems)

    stock_ids = _demo_ids(session, "estoque")
    movement_ids = _demo_ids(session, "movimentacoes_estoque")
    balance: dict[int, Decimal] = defaultdict(Decimal)
    for movement in session.scalars(select(StockMovement)):
        if movement.id in movement_ids:
            sign = 1 if movement.movement_type == "Entrada" else -1
            balance[movement.product_id] += sign * Decimal(str(movement.quantity))
    stock_problems = []
    for stock in session.scalars(select(Stock)):
        if stock.id not in stock_ids:
            continue
        if stock.quantity < 0:
            stock_problems.append(f"produto {stock.product_id} negativo")
        if abs(Decimal(str(stock.quantity)) - balance[stock.product_id]) > Decimal("0.01"):
            stock_problems.append(f"produto {stock.product_id} saldo != movimentações")
    _check(results, "Estoque: saldo = entradas - saídas - perdas e sem negativos", stock_problems)

    finance_problems = []
    payable_ids = _demo_ids(session, "contas_pagar")
    for payable in session.scalars(select(Payable)):
        if payable.id not in payable_ids:
            continue
        if payable.status == "Pago" and payable.paid_at is None:
            finance_problems.append(f"conta a pagar {payable.id} paga sem data")
        if payable.status == "Aberto" and payable.due_date < today:
            finance_problems.append(f"conta a pagar {payable.id} aberta e vencida")
        if payable.status == "Vencido" and payable.due_date >= today:
            finance_problems.append(f"conta a pagar {payable.id} vencida no futuro")
        if money(payable.amount) <= 0:
            finance_problems.append(f"conta a pagar {payable.id} valor inválido")
    receivable_ids = _demo_ids(session, "contas_receber")
    for receivable in session.scalars(select(Receivable)):
        if receivable.id in receivable_ids:
            if receivable.status == "Recebido" and receivable.received_at is None:
                finance_problems.append(f"conta a receber {receivable.id} recebida sem data")
            if money(receivable.amount) <= 0:
                finance_problems.append(f"conta a receber {receivable.id} valor inválido")
    _check(results, "Contas a pagar e a receber coerentes", finance_problems)
    return results
