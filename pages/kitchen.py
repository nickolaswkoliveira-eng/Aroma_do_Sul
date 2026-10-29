from datetime import timedelta
from sqlalchemy import func, select
import streamlit as st

from components.layout import metric_card, section_heading
from database.connection import get_session
from models.entities import Order, OrderItem, Product
from services.domain import update_order_status
from utils.clock import local_now, local_today
from utils.session_state import persistent_toggle

TV_MODE_STYLE = """
<style>
div[class*="st-key-top_navigation"],
div[class*="st-key-top_navigation_mobile"] { display: none !important; }
div[data-testid="stMainBlockContainer"] { max-width: none; padding: .75rem 1.5rem 1.5rem; }
div[data-testid="stMainBlockContainer"] [data-testid="stMetricValue"] { font-size: 2rem; }
div[data-testid="stMainBlockContainer"] [data-testid="stMetricLabel"] { font-size: 1rem; }
div[data-testid="stMainBlockContainer"] .panel-kpi { min-height: 160px; }
div[data-testid="stMainBlockContainer"] .panel-label { font-size: 1rem; }
div[data-testid="stMainBlockContainer"] .panel-value { font-size: 2rem; }
div[class*="st-key-kitchen_order_"] { min-height: 190px; border: 1px solid #BBA58E; border-radius: 12px; padding: 1rem; margin-bottom: .75rem; }
div[data-testid="stMainBlockContainer"] h4 { font-size: 1.35rem; }
div[data-testid="stMainBlockContainer"] div.stButton > button { min-height: 3.2rem; font-size: 1.1rem; }
@media (max-width: 900px) {
  div[data-testid="stMainBlockContainer"] [data-testid="stHorizontalBlock"] { flex-wrap: wrap; }
  div[data-testid="stMainBlockContainer"] [data-testid="stColumn"] { flex: 1 1 calc(50% - 1rem) !important; }
}
</style>
"""


def _minutes_label(minutes: float | None) -> str:
    if minutes is None:
        return "Sem dados"
    if 0 < minutes < 1:
        return "<1 min"
    return f"{minutes:.0f} min"


def _load_order_items_map(session, order_ids: list[int]) -> tuple[dict[int, list[OrderItem]], dict[int, Product]]:
    if not order_ids:
        return {}, {}
    items = session.scalars(select(OrderItem).where(OrderItem.order_id.in_(order_ids))).all()
    items_by_order: dict[int, list[OrderItem]] = {}
    product_ids: set[int] = set()
    for item in items:
        items_by_order.setdefault(item.order_id, []).append(item)
        product_ids.add(item.product_id)
    products_by_id = {
        product.id: product
        for product in session.scalars(select(Product).where(Product.id.in_(product_ids))).all()
    } if product_ids else {}
    return items_by_order, products_by_id


def _render_queue_content(session, responsible: str, show_auto_refresh_caption: bool = False) -> None:
    now = local_now()
    today = local_today()
    active = session.scalars(
        select(Order).where(Order.status != "Finalizado").order_by(Order.created_at)
    ).all()
    recent = session.scalars(select(Order).where(
        Order.created_at >= now - timedelta(days=30),
        Order.started_at.is_not(None),
        Order.ready_at.is_not(None),
    )).all()
    production_times = [(order.ready_at - order.started_at).total_seconds() / 60 for order in recent]
    delivery_times = [(order.delivered_at - order.ready_at).total_seconds() / 60 for order in recent if order.delivered_at]
    average_minutes = sum(production_times) / len(production_times) if production_times else 15
    delivered_today = session.scalars(
        select(Order).where(Order.status == "Finalizado", func.date(Order.finished_at) == today)
    ).all()
    total_times = [(order.finished_at - order.created_at).total_seconds() / 60 for order in delivered_today]
    if show_auto_refresh_caption:
        st.caption("Atualização automática a cada 8 s")
    metrics = st.columns(4)
    with metrics[0]: metric_card("Produção média", _minutes_label(sum(production_times) / len(production_times) if production_times else None), "Últimos 30 dias")
    with metrics[1]: metric_card("Até entrega", _minutes_label(sum(delivery_times) / len(delivery_times) if delivery_times else None), "Pronto até entregue")
    with metrics[2]: metric_card("Mais demorado", _minutes_label(max(total_times) if total_times else None), "Concluído hoje")
    with metrics[3]: metric_card("Mais rápido", _minutes_label(min(total_times) if total_times else None), "Concluído hoje")
    items_by_order, products_by_id = _load_order_items_map(session, [order.id for order in active])
    buckets = [("Recebido", {"Recebido"}), ("Em preparo", {"Em preparo"}), ("Pronto", {"Pronto"}), ("Entregue", {"Entregue"})]
    columns = st.columns(len(buckets))
    for column, (label, statuses) in zip(columns, buckets):
        board_orders = [order for order in active if order.status in statuses]
        with column:
            st.markdown(f"#### {label} <span class=\"kanban-count\">{len(board_orders)}</span>", unsafe_allow_html=True)
            if not board_orders:
                st.caption("Nenhum pedido")
            for order in board_orders:
                with st.container(key=f"kitchen_order_{order.id}"):
                    st.markdown(f"**Pedido #{order.id}** · {order.status}")
                    st.caption(f"Recebido às {order.created_at:%H:%M} · há {int((now - order.created_at).total_seconds() // 60)} min")
                    for item in items_by_order.get(order.id, []):
                        product = products_by_id.get(item.product_id)
                        st.write(f"{item.quantity}× {(product.name if product else 'Produto')}" + (f" · {item.notes}" if item.notes else ""))
                    if order.notes:
                        st.caption(order.notes)
                    timeline = [
                        ("Recebido", order.created_at), ("Preparo", order.started_at),
                        ("Pronto", order.ready_at), ("Entregue", order.delivered_at),
                        ("Finalizado", order.finished_at),
                    ]
                    milestones = [f"{name} {timestamp:%H:%M}" for name, timestamp in timeline if timestamp]
                    if milestones:
                        st.markdown(f'<div class="order-timeline">{"<br>".join(milestones)}</div>', unsafe_allow_html=True)
                    if order.started_at and order.status == "Em preparo":
                        prep_time = (now - order.started_at).total_seconds() / 60
                        if prep_time > average_minutes * 1.5:
                            st.warning(f"Preparo acima da média: {prep_time:.0f} min")
                    next_status = {"Recebido": "Em preparo", "Em preparo": "Pronto", "Pronto": "Entregue", "Entregue": "Finalizado"}.get(order.status)
                    if next_status:
                        button_label = {"Em preparo": "Iniciar preparo", "Pronto": "Pedido pronto", "Entregue": "Marcar entregue", "Finalizado": "Finalizar"}[next_status]
                        if st.button(button_label, key=f"status_{order.id}", type="primary", width="stretch"):
                            try:
                                update_order_status(session, order, next_status, responsible)
                                st.rerun()
                            except ValueError as error:
                                st.error(str(error))
    if not active:
        st.success("Cozinha em dia. Nenhum pedido pendente.")


@st.fragment(run_every="8s")
def _render_queue(tv_mode: bool, responsible: str) -> None:
    session = get_session()
    try:
        _render_queue_content(session, responsible, show_auto_refresh_caption=True)
    finally:
        session.close()


def render(_session) -> None:
    tv_mode = persistent_toggle("Modo TV", key="kitchen.tv_mode", default=False)
    live_refresh = persistent_toggle("Atualizar automaticamente (8s)", key="kitchen.live_refresh", default=True)
    if tv_mode:
        st.title("Modo TV · Fila da cozinha")
        st.caption("Acompanhamento ampliado · atualização automática a cada 8 segundos")
        st.markdown(TV_MODE_STYLE, unsafe_allow_html=True)
    else:
        section_heading("Cozinha", "Fila de produção em tempo real")
    if live_refresh:
        _render_queue(tv_mode, st.session_state.get("acting_user", "SISTEMA_HOMOLOGACAO"))
    else:
        session = get_session()
        try:
            _render_queue_content(session, st.session_state.get("acting_user", "SISTEMA_HOMOLOGACAO"))
            if st.button("Atualizar agora", key="kitchen.refresh_now", type="primary"):
                st.rerun()
        finally:
            session.close()
