from datetime import timedelta
from html import escape
from itertools import combinations
from sqlalchemy import func, select
from sqlalchemy.orm import Session
import streamlit as st

from components.layout import section_heading
from models.entities import Order, OrderItem, Payable, Product, RecipeItem
from services.domain import cmv_for_period, purchase_recommendations
from utils.clock import local_today


CATEGORY_ICONS = {"Estoque": "📦", "Vendas": "📈", "Financeiro": "💰", "Operação": "⚙️"}


def _collect_insights(session: Session) -> dict[str, list[dict[str, str]]]:
    insights = {"Estoque": [], "Vendas": [], "Financeiro": [], "Operação": []}

    def add(category: str, what: str, impact: str, action: str) -> None:
        insights[category].append({"what": what, "impact": impact, "action": action})

    today = local_today()
    recent_start = today - timedelta(days=30)
    orders_today = session.scalars(select(Order).where(func.date(Order.created_at) == today)).all()
    revenue_today = sum(order.total for order in orders_today)
    top_product = session.execute(
        select(Product.id, Product.name, func.sum(OrderItem.quantity * OrderItem.unit_price).label("revenue"))
        .join(OrderItem, OrderItem.product_id == Product.id).join(Order, Order.id == OrderItem.order_id)
        .where(func.date(Order.created_at) == today).group_by(Product.id)
        .order_by(func.sum(OrderItem.quantity * OrderItem.unit_price).desc()).limit(1)
    ).first()
    if top_product and revenue_today:
        share = top_product.revenue / revenue_today
        recipes = session.scalars(select(RecipeItem).where(RecipeItem.product_id == top_product.id)).all()
        ingredients = [session.get(Product, recipe.ingredient_id).name for recipe in recipes]
        stock_action = f"Garantir {', '.join(ingredients)}." if ingredients else "Revisar custo e disponibilidade do produto."
        add("Vendas", f"{top_product.name} representa {share:.0%} do faturamento de hoje.",
            "É o produto de maior participação no faturamento diário.", stock_action)

    week_start = today - timedelta(days=today.weekday())
    prior_week_start = week_start - timedelta(days=7)
    current_week = session.scalars(select(Order).where(func.date(Order.created_at) >= week_start,
                                                       func.date(Order.created_at) <= today)).all()
    previous_week = session.scalars(select(Order).where(func.date(Order.created_at) >= prior_week_start,
                                                        func.date(Order.created_at) < week_start)).all()
    current_total = sum(order.total for order in current_week)
    previous_total = sum(order.total for order in previous_week)
    if previous_total:
        change = (current_total - previous_total) / previous_total
        direction = "cresceram" if change >= 0 else "caíram"
        add("Vendas", f"As vendas {direction} {abs(change):.0%} em relação ao mesmo período da semana passada.",
            "Indica mudança recente na procura.",
            "Monitorar capacidade da cozinha." if change > 0 else "Revisar horários, mix de produtos e divulgação.")

    recent_orders = session.scalars(select(Order).where(func.date(Order.created_at) >= recent_start,
                                                       func.date(Order.created_at) <= today)).all()
    if recent_orders:
        recent_items = session.scalars(select(OrderItem).where(
            OrderItem.order_id.in_([order.id for order in recent_orders]))).all()
        products_by_order: dict[int, set[int]] = {}
        for item in recent_items:
            products_by_order.setdefault(item.order_id, set()).add(item.product_id)
        pairs: dict[tuple[int, int], int] = {}
        for product_ids in products_by_order.values():
            for pair in combinations(sorted(product_ids), 2):
                pairs[pair] = pairs.get(pair, 0) + 1
        if pairs:
            pair, count = max(pairs.items(), key=lambda item: item[1])
            first, second = session.get(Product, pair[0]), session.get(Product, pair[1])
            add("Vendas", f"{first.name} + {second.name} aparece junto em {count} pedidos nos últimos 30 dias.",
                "A combinação tem recorrência observada no histórico.",
                "Avaliar a oferta dos dois itens como combo.")

    stock_actions = [item for item in purchase_recommendations(session) if item["needs_action"]]
    if stock_actions:
        add("Estoque", f"{len(stock_actions)} item(ns) exigem atenção no estoque.",
            "Há risco de falta ou cobertura abaixo do nível recomendado.",
            "Consulte as recomendações detalhadas no módulo Estoque.")

    due_soon = session.scalars(select(Payable).where(
        Payable.status == "Aberto", Payable.due_date >= today,
        Payable.due_date <= today + timedelta(days=7))).all()
    if due_soon:
        total_due = sum(item.amount for item in due_soon)
        add("Financeiro", f"{len(due_soon)} conta(s), totalizando R$ {total_due:,.2f}, vencem nos próximos 7 dias.",
            "Os compromissos pressionam o saldo de curto prazo.",
            "Conferir o fluxo projetado e programar pagamentos.")

    cmv = cmv_for_period(session, today.replace(day=1), today)
    if cmv["revenue"]:
        if cmv["ratio"] > .35:
            add("Financeiro", f"O CMV está em {cmv['ratio']:.0%} neste mês.",
                "Acima da referência gerencial de 35%.",
                "Revisar custos da ficha técnica, perdas e preços de compra.")
        else:
            add("Financeiro", f"O CMV está em {cmv['ratio']:.0%} neste mês.",
                "Dentro da referência gerencial de até 35%.",
                "Manter conferência de custos e perdas.")

    finished_orders = session.scalars(select(Order).where(
        Order.started_at.is_not(None), Order.ready_at.is_not(None),
        func.date(Order.created_at) >= recent_start)).all()
    if finished_orders:
        average = sum((order.ready_at - order.started_at).total_seconds() / 60
                      for order in finished_orders) / len(finished_orders)
        add("Operação", f"O tempo médio de preparo nos últimos 30 dias foi de {average:.0f} minutos.",
            "Mede a velocidade média de saída da cozinha.",
            "Revisar escala e etapas de preparo se o tempo aumentar.")
    if recent_orders:
        busiest = max(range(24), key=lambda hour: sum(order.created_at.hour == hour for order in recent_orders))
        busiest_count = sum(order.created_at.hour == busiest for order in recent_orders)
        add("Operação", f"O pico de pedidos ocorreu entre {busiest:02d}:00 e {(busiest + 1) % 24:02d}:00, com {busiest_count} pedido(s) nos últimos 30 dias.",
            "A maior carga de atendimento se concentra nesse horário.",
            "Planejar equipe e pré-preparo para esse intervalo.")
    return insights


def render(session: Session) -> None:
    section_heading("Central de Inteligência", "Leituras automáticas dos dados da operação")
    st.caption("Insights calculados a partir de vendas, estoque, contas e tempos registrados.")
    insights = _collect_insights(session)
    for category, messages in insights.items():
        if not messages:
            continue
        st.subheader(f"{CATEGORY_ICONS[category]} {category}")
        columns = st.columns(2)
        for index, message in enumerate(messages):
            with columns[index % 2]:
                st.markdown(
                    f'<div class="insight-card"><div class="panel-label">{CATEGORY_ICONS[category]} {category}</div>'
                    f'<div><strong>O que aconteceu</strong><br>{escape(message["what"])}</div>'
                    f'<div><strong>Impacto</strong><br>{escape(message["impact"])}</div>'
                    f'<div><strong>Ação sugerida</strong><br>{escape(message["action"])}</div></div>',
                            unsafe_allow_html=True)
        if category == "Estoque" and st.button("Abrir recomendações no Estoque",
                                               key="intelligence.open_inventory"):
            st.session_state.active_page = "Estoque"
            st.query_params["pagina"] = "Estoque"
            st.rerun()
    if not any(insights.values()):
        st.info("Ainda não há dados suficientes para gerar insights. Registre vendas e movimentações para iniciar as análises.")
