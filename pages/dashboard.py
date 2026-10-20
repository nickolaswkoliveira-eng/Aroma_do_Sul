from datetime import date, datetime, timedelta
from html import escape
from collections.abc import Callable, Sequence
from sqlalchemy import func, select
from sqlalchemy.orm import Session
import streamlit as st

from components.layout import section_heading
from models.entities import CashSession, Order, OrderItem, Payable, Product, Stock
from services.domain import cash_balance, cmv_for_period
from utils.formatting import currency


def render_operational_home(session: Session, user_name: str, available_pages: Sequence[str],
                            on_navigate: Callable[[str], None]) -> None:
    hour = datetime.now().hour
    greeting = "Bom dia" if hour < 12 else "Boa tarde" if hour < 18 else "Boa noite"
    first_name = user_name.split()[0] if user_name and user_name != "Homologação" else "Dener"
    st.markdown(
        f'<div class="home-intro"><div class="home-eyebrow">Central de operação</div>'
        f'<div class="home-title">{greeting}, {escape(first_name)}.</div>'
        '<div class="home-description">O que você precisa fazer agora?</div></div>',
        unsafe_allow_html=True,
    )

    actions = [
        ("＋  Novo pedido", "Pedidos", "primary"),
        ("Cozinha", "Cozinha", "secondary"),
        ("Caixa", "Caixa", "secondary"),
        ("Estoque", "Estoque", "secondary"),
    ]
    available_actions = [action for action in actions if action[1] in available_pages]
    if available_actions:
        with st.container(key="home_actions"):
            action_columns = st.columns(len(available_actions))
            for column, (label, destination, button_type) in zip(action_columns, available_actions):
                with column:
                    if st.button(label, key=f"home_action_{destination}", type=button_type, width="stretch"):
                        on_navigate(destination)

    status_items: list[tuple[str, str]] = []
    if any(page in available_pages for page in ("Pedidos", "Cozinha")):
        active_orders = session.scalar(select(func.count(Order.id)).where(
            Order.status.in_(("Recebido", "Em preparo")))) or 0
        status_items.append(("Pedidos em andamento", str(active_orders)))
    if "Caixa" in available_pages:
        cash_is_open = session.scalar(select(CashSession.id).where(CashSession.is_open.is_(True)).limit(1))
        status_items.append(("Caixa", "Aberto" if cash_is_open else "Fechado"))
    if "Estoque" in available_pages:
        stock_rows = session.execute(select(Stock.quantity, Stock.minimum_quantity)).all()
        critical = sum(quantity <= minimum * .2 for quantity, minimum in stock_rows)
        status_items.append(("Alertas de estoque", str(critical)))
    if status_items:
        st.markdown('<div class="home-status"><div class="home-eyebrow">Status da operação</div></div>',
                    unsafe_allow_html=True)
        status_columns = st.columns(len(status_items))
        for column, (label, value) in zip(status_columns, status_items):
            with column:
                st.markdown(
                    f'<div class="home-status-label">{escape(label)}</div>'
                    f'<div class="home-status-value">{escape(value)}</div>',
                    unsafe_allow_html=True,
                )


def render(session: Session) -> None:
    section_heading("Visão geral", "Indicadores gerenciais do negócio")
    today = date.today()
    yesterday = today - timedelta(days=1)
    revenue = session.scalar(select(func.coalesce(func.sum(Order.total), 0)).where(func.date(Order.created_at) == today)) or 0
    yesterday_revenue = session.scalar(select(func.coalesce(func.sum(Order.total), 0)).where(func.date(Order.created_at) == yesterday)) or 0
    in_progress = session.scalar(select(func.count(Order.id)).where(Order.status.in_(("Recebido", "Em preparo")))) or 0
    waiting = session.scalar(select(func.count(Order.id)).where(Order.status == "Recebido")) or 0
    completed = session.scalar(select(func.count(Order.id)).where(Order.status == "Finalizado",
                                                                    func.date(Order.finished_at) == today)) or 0
    yesterday_completed = session.scalar(select(func.count(Order.id)).where(Order.status == "Finalizado",
                                                                             func.date(Order.finished_at) == yesterday)) or 0
    cash = session.scalar(select(CashSession).where(CashSession.is_open.is_(True)))
    stock_rows = session.execute(select(Stock.quantity, Stock.minimum_quantity)).all()
    critical = sum(quantity <= minimum * .2 for quantity, minimum in stock_rows)
    attention = sum(quantity > 0 and minimum > 0 and minimum * .2 < quantity < minimum * .5
                    for quantity, minimum in stock_rows)
    today_orders = session.scalars(select(Order).where(func.date(Order.created_at) == today)).all()
    top_product = session.execute(select(Product.name, func.sum(OrderItem.quantity).label("units"))
                                  .join(OrderItem, OrderItem.product_id == Product.id)
                                  .join(Order, Order.id == OrderItem.order_id)
                                  .where(func.date(Order.created_at) == today)
                                  .group_by(Product.id).order_by(func.sum(OrderItem.quantity).desc()).limit(1)).first()
    revenue_trend = ""
    previous_7_days = session.scalar(select(func.coalesce(func.sum(Order.total), 0)).where(
        func.date(Order.created_at) >= today - timedelta(days=7), func.date(Order.created_at) < today)) or 0
    average_day = float(previous_7_days) / 7
    if average_day:
        change = (float(revenue) - average_day) / average_day
        revenue_trend = f"{'↑' if change >= 0 else '↓'} {abs(change):.0%} vs média de 7 dias"
    elif yesterday_revenue:
        change = (float(revenue) - float(yesterday_revenue)) / float(yesterday_revenue)
        revenue_trend = f"{'↑' if change >= 0 else '↓'} {abs(change):.0%} vs ontem"
    completed_trend = ""
    if yesterday_completed:
        change = (completed - yesterday_completed) / yesterday_completed
        completed_trend = f"{'↑' if change >= 0 else '↓'} {abs(change):.0%} vs ontem"
    values = [
        ("Faturamento", currency(float(revenue)), "Hoje", revenue_trend),
        ("Pedidos ativos", str(in_progress), f"{waiting} aguardando preparo", ""),
        ("Pedidos concluídos", str(completed), "Hoje", completed_trend),
        ("Caixa", "Aberto" if cash else "Fechado", f"{currency(cash_balance(session, cash))} hoje" if cash else "Nenhum turno aberto", ""),
        ("Estoque crítico", str(critical), "Itens em nível crítico", ""),
        ("Mais vendido", top_product[0] if top_product else "Sem vendas",
         f"{top_product[1]} unidades hoje" if top_product else "Aguardando pedidos", ""),
    ]
    st.subheader("Resumo do dia")
    for start in (0, 3):
        cols = st.columns(3)
        for column, (label, value, note, trend) in zip(cols, values[start:start + 3]):
            with column:
                st.metric(label, value, delta=trend or None, help=note)

    month_start = today.replace(day=1)
    week_start = today - timedelta(days=today.weekday())
    month_metrics = cmv_for_period(session, month_start, today)
    week_metrics = cmv_for_period(session, week_start, today)
    day_metrics = cmv_for_period(session, today, today)
    st.subheader("CMV")
    cmv_cols = st.columns(3)
    for column, label, metric in zip(cmv_cols, ("Hoje", "Semana", "Mês"),
                                     (day_metrics, week_metrics, month_metrics)):
        if metric["revenue"]:
            ratio = metric["ratio"]
            note = "Dentro da faixa recomendada" if ratio <= .35 else "Acima da meta recomendada"
            with column:
                st.metric(f"CMV · {label}", f"{ratio:.0%}", help=note)
        else:
            with column:
                st.metric(f"CMV · {label}", "—", help="Nenhuma venda no período")

    recent_production = session.scalars(select(Order).where(
        Order.started_at.is_not(None), Order.ready_at.is_not(None),
        func.date(Order.created_at) >= today - timedelta(days=30))).all()
    average_production = (sum((order.ready_at - order.started_at).total_seconds() / 60
                              for order in recent_production) / len(recent_production)) if recent_production else 15
    slow_orders = [order for order in today_orders if order.status == "Em preparo" and order.started_at
                   and (datetime.now() - order.started_at).total_seconds() / 60 > average_production * 1.5]
    due_soon = session.scalar(select(func.count(Payable.id)).where(
        Payable.status.in_(("Aberto", "Vencido")),
        Payable.due_date <= today + timedelta(days=7))) or 0
    st.subheader("Atenção hoje")
    attention_items = []
    if critical:
        attention_items.append(("🚨", f"{critical} produto(s) em nível crítico. Consulte Ações recomendadas no Estoque."))
    if attention:
        attention_items.append(("⚠", f"{attention} produto(s) em atenção no estoque."))
    if slow_orders:
        attention_items.append(("⏱", f"{len(slow_orders)} pedido(s) ultrapassaram 150% do tempo médio de produção."))
    attention_items.append(("✅" if cash else "⚠", "Caixa aberto." if cash else "Caixa fechado. Abra o caixa antes de receber pagamentos."))
    if revenue_trend:
        attention_items.append(("📈" if revenue >= average_day else "📉", f"Faturamento {revenue_trend.replace('↑ ', '').replace('↓ ', '')}."))
    if due_soon:
        attention_items.append(("🧾", f"{due_soon} conta(s) vencida(s) ou com vencimento nos próximos 7 dias."))
    if month_metrics["revenue"] and month_metrics["ratio"] > .35:
        attention_items.append(("⚠", f"CMV mensal em {month_metrics['ratio']:.0%}, acima da referência de 35%. Revise custos e perdas."))
    for icon, message in attention_items:
        st.markdown(f"{icon} {message}")


def module_indicators(session: Session, module_name: str) -> list[str]:
    if module_name == "Pedidos":
        active = session.scalar(select(func.count(Order.id)).where(Order.status.in_(("Recebido", "Em preparo")))) or 0
        waiting = session.scalar(select(func.count(Order.id)).where(Order.status == "Recebido")) or 0
        return [f"{active} ativos", f"{waiting} aguardando preparo"]
    if module_name == "Cozinha":
        preparing = session.scalar(select(func.count(Order.id)).where(Order.status == "Em preparo")) or 0
        ready = session.scalar(select(func.count(Order.id)).where(Order.status == "Pronto")) or 0
        return [f"{preparing} em preparo", f"{ready} prontos"]
    if module_name == "Estoque":
        product_count = session.scalar(select(func.count(Product.id)).where(Product.active.is_(True))) or 0
        rows = session.execute(select(Stock.quantity, Stock.minimum_quantity)).all()
        critical = sum(quantity <= minimum * .2 for quantity, minimum in rows)
        attention = sum(minimum > 0 and minimum * .2 < quantity < minimum * .5 for quantity, minimum in rows)
        return [f"{product_count} produtos", f"{critical} críticos", f"{attention} atenção"]
    if module_name == "Caixa":
        cash = session.scalar(select(CashSession).where(CashSession.is_open.is_(True)))
        return ["Aberto" if cash else "Fechado", currency(cash_balance(session, cash)) if cash else "Sem turno"]
    if module_name == "Financeiro":
        pending = session.scalar(select(func.count(Payable.id)).where(Payable.status.in_(("Aberto", "Vencido")))) or 0
        return [f"{pending} contas pendentes"]
    if module_name == "Relatórios":
        return ["Vendas", "Produtos", "DRE", "Fluxo"]
    if module_name == "Central de Inteligência":
        return ["Insights", "Estoque", "Vendas", "Operação"]
    if module_name == "Configurações":
        return ["Ambiente", "Auditoria"]
    return []
