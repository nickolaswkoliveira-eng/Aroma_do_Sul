from datetime import datetime, timedelta
from sqlalchemy import select
import streamlit as st

from components.layout import metric_card, section_heading
from database.connection import get_session
from models.entities import Order, OrderItem, Product
from services.domain import update_order_status
from utils.clock import local_now, local_today
from utils.session_state import persistent_toggle


def _minutes_label(minutes: float | None) -> str:
    if minutes is None:
        return "Sem dados"
    if 0 < minutes < 1:
        return "<1 min"
    return f"{minutes:.0f} min"


@st.fragment(run_every="5s")
def _render_queue(tv_mode: bool, responsible: str) -> None:
    session = get_session()
    try:
        now = local_now()
        today = local_today()
        if tv_mode:
            st.markdown("""
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
            """, unsafe_allow_html=True)
        active = session.scalars(select(Order).where(
            (Order.status != "Finalizado") | (Order.finished_at.is_not(None) & (Order.finished_at >= datetime.combine(today, datetime.min.time())))
        ).order_by(Order.created_at)).all()
        recent = session.scalars(select(Order).where(Order.created_at >= now - timedelta(days=30),
                                                    Order.started_at.is_not(None), Order.ready_at.is_not(None))).all()
        production_times = [(order.ready_at - order.started_at).total_seconds() / 60 for order in recent]
        delivery_times = [(order.delivered_at - order.ready_at).total_seconds() / 60 for order in recent
                          if order.delivered_at]
        average_minutes = sum(production_times) / len(production_times) if production_times else 15
        delivered_today = [order for order in active if order.finished_at and order.finished_at.date() == today]
        total_times = [(order.finished_at - order.created_at).total_seconds() / 60 for order in delivered_today]
        st.caption("Atualização automática a cada 5 s")
        metrics = st.columns(4)
        with metrics[0]: metric_card("Produção média", _minutes_label(sum(production_times) / len(production_times) if production_times else None), "Últimos 30 dias")
        with metrics[1]: metric_card("Até entrega", _minutes_label(sum(delivery_times) / len(delivery_times) if delivery_times else None), "Pronto até entregue")
        with metrics[2]: metric_card("Mais demorado", _minutes_label(max(total_times) if total_times else None), "Concluído hoje")
        with metrics[3]: metric_card("Mais rápido", _minutes_label(min(total_times) if total_times else None), "Concluído hoje")
        buckets = [
            ("Recebido", ["Recebido"]),
            ("Em preparo", ["Em preparo"]),
            ("Pronto", ["Pronto"]),
            ("Finalizado", ["Entregue", "Finalizado"]),
        ]
        columns = st.columns(4)
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
                        items = session.scalars(select(OrderItem).where(OrderItem.order_id == order.id)).all()
                        for item in items:
                            product = session.get(Product, item.product_id)
                            st.write(f"{item.quantity}× {product.name}" + (f" · {item.notes}" if item.notes else ""))
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
                            label = {"Em preparo": "Iniciar preparo", "Pronto": "Pedido pronto", "Entregue": "Marcar entregue", "Finalizado": "Finalizar"}[next_status]
                            if st.button(label, key=f"status_{order.id}", type="primary", width="stretch"):
                                try:
                                    update_order_status(session, order, next_status, responsible)
                                    st.rerun()
                                except ValueError as error:
                                    st.error(str(error))
        if not active:
            st.success("Cozinha em dia. Nenhum pedido pendente.")
    finally:
        session.close()


def render(session) -> None:
    tv_mode = persistent_toggle("Modo TV", key="kitchen.tv_mode", default=False)
    if tv_mode:
        st.title("Modo TV · Fila da cozinha")
        st.caption("Acompanhamento ampliado · atualização automática a cada 5 segundos")
    else:
        section_heading("Cozinha", "Fila de produção em tempo real")
    _render_queue(tv_mode, st.session_state.get("acting_user", "SISTEMA_HOMOLOGACAO"))
