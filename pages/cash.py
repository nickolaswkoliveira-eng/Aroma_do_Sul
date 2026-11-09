from io import BytesIO

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session
import streamlit as st

from components.layout import metric_card, section_heading
from models.entities import CashMovement, CashSession, ComandaOrder, Order, OrderItem, OwnConsumption, Product
from services.domain import add_cash_movement, cash_balance, close_cash, open_cash, register_own_consumption
from utils.formatting import currency, date_time
from utils.session_state import persistent_number_input, persistent_selectbox, persistent_text_input


def _build_cash_close_excel(session: Session, cash_session: CashSession) -> bytes:
    opened_at = cash_session.opened_at
    closed_at = cash_session.closed_at or cash_session.opened_at
    movements = session.scalars(
        select(CashMovement)
        .where(CashMovement.cash_session_id == cash_session.id)
        .order_by(CashMovement.created_at)
    ).all()
    methods_by_comanda: dict[int, list[str]] = {}
    for movement in movements:
        if movement.description.startswith("Comanda #"):
            try:
                comanda_id = int(movement.description.split("#", 1)[1].strip())
            except ValueError:
                continue
            methods_by_comanda.setdefault(comanda_id, []).append(movement.method)
    payment_by_comanda = {
        comanda_id: " + ".join(dict.fromkeys(methods)) for comanda_id, methods in methods_by_comanda.items()
    }
    orders = session.scalars(
        select(Order).where(
            Order.status == "Finalizado",
            Order.finished_at.is_not(None),
            Order.finished_at >= opened_at,
            Order.finished_at <= closed_at,
        )
    ).all()
    order_ids = [order.id for order in orders]
    links = session.scalars(select(ComandaOrder).where(ComandaOrder.order_id.in_(order_ids))).all() if order_ids else []
    comanda_by_order = {link.order_id: link.comanda_id for link in links}
    order_items = session.scalars(select(OrderItem).where(OrderItem.order_id.in_(order_ids))).all() if order_ids else []
    items_by_order: dict[int, list[OrderItem]] = {}
    product_ids: set[int] = set()
    for item in order_items:
        items_by_order.setdefault(item.order_id, []).append(item)
        product_ids.add(item.product_id)
    products_by_id = {
        product.id: product for product in session.scalars(select(Product).where(Product.id.in_(product_ids))).all()
    } if product_ids else {}
    details = []
    for order in orders:
        comanda_id = comanda_by_order.get(order.id)
        payment_method = payment_by_comanda.get(comanda_id, "-") if comanda_id else "-"
        for item in items_by_order.get(order.id, []):
            product = products_by_id.get(item.product_id)
            if product is None:
                continue
            details.append({
                "Data": order.finished_at.date().isoformat() if order.finished_at else "-",
                "Hora": order.finished_at.strftime("%H:%M") if order.finished_at else "-",
                "Comanda": comanda_id if comanda_id else "-",
                "Pedido": order.id,
                "Produto": product.name,
                "Quantidade": item.quantity,
                "Valor unitário": float(item.unit_price),
                "Valor total": float(item.quantity * item.unit_price),
                "Forma de pagamento": payment_method,
            })
    entries = sum(movement.amount for movement in movements if movement.movement_type == "Entrada")
    exits = sum(movement.amount for movement in movements if movement.movement_type == "Saída")
    summary = pd.DataFrame([{
        "Operador": cash_session.operator,
        "Abertura": date_time(cash_session.opened_at),
        "Fechamento": date_time(cash_session.closed_at),
        "Saldo inicial": float(cash_session.opening_balance),
        "Entradas": float(entries),
        "Saídas": float(exits),
        "Saldo final": float(cash_session.closing_balance or 0),
    }])
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pd.DataFrame(details).to_excel(writer, sheet_name="Movimentacao", index=False)
        summary.to_excel(writer, sheet_name="Resumo", index=False)
    return output.getvalue()


def _render_own_consumption(session: Session) -> None:
    st.subheader("Consumo próprio")
    st.caption("Baixa o estoque e registra o custo como perda. Não altera o saldo do caixa.")
    products = session.scalars(select(Product).where(Product.active.is_(True)).order_by(Product.name)).all()
    options = {f"{product.name} ({product.code})": product.id for product in products}
    if not options:
        st.info("Nenhum produto cadastrado.")
        return
    first, second, third = st.columns([2, 1, 1.5])
    with first:
        label = st.selectbox("Produto", list(options), key="cash.own.product")
    with second:
        quantity = st.number_input("Quantidade", min_value=1, step=1, value=1, key="cash.own.quantity")
    with third:
        consumed_by = st.text_input("Quem consumiu (opcional)", key="cash.own.by")
    if st.button("Registrar consumo próprio", key="cash.own.submit"):
        try:
            cost = register_own_consumption(
                session, options[label], int(quantity), consumed_by,
                responsible=st.session_state.get("acting_user", "SISTEMA_HOMOLOGACAO"),
            )
            st.success(f"Consumo registrado. Perda de {currency(cost)}.")
            st.rerun()
        except ValueError as error:
            st.error(str(error))
    recent = session.scalars(select(OwnConsumption).order_by(OwnConsumption.created_at.desc()).limit(10)).all()
    if recent:
        names = {product.id: product.name for product in products}
        st.dataframe([{
            "Data": date_time(item.created_at), "Produto": names.get(item.product_id, "-"),
            "Qtd": item.quantity, "Custo": currency(item.total_cost), "Quem": item.consumed_by or "-",
        } for item in recent], width="stretch", hide_index=True)


def render(session: Session) -> None:
    section_heading("Caixa", "Abertura, recebimentos, saídas e fechamento")
    cash = session.scalar(select(CashSession).where(CashSession.is_open.is_(True)))
    if cash is None:
        st.subheader("Abrir turno")
        opening = persistent_number_input("Valor inicial", key="cash.opening_balance", default=0.0,
                                          min_value=0.0, step=10.0)
        operator = persistent_text_input("Operador", key="cash.operator", default="Administrador")
        if st.button("Abrir caixa", type="primary", key="cash.open_button"):
            try:
                open_cash(session, opening, operator)
                st.success("Caixa aberto.")
                st.rerun()
            except ValueError as error:
                st.error(str(error))
        history = session.scalars(select(CashSession).order_by(CashSession.opened_at.desc()).limit(10)).all()
        exported_cash_id = st.session_state.get("cash.last_closed_id")
        if exported_cash_id:
            exported_cash = session.get(CashSession, exported_cash_id)
            if exported_cash and not exported_cash.is_open and exported_cash.closed_at:
                try:
                    excel_bytes = _build_cash_close_excel(session, exported_cash)
                    st.download_button(
                        "Baixar fechamento em Excel",
                        data=excel_bytes,
                        file_name=f"fechamento-caixa-{exported_cash.closed_at:%Y%m%d-%H%M}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key=f"cash.download.last.{exported_cash.id}",
                    )
                except (ImportError, ValueError) as error:
                    st.error(f"Não foi possível gerar o Excel de fechamento: {error}")
        if history:
            st.subheader("Turnos recentes")
            st.dataframe([{"Operador": item.operator, "Abertura": date_time(item.opened_at),
                           "Saldo inicial": currency(item.opening_balance), "Saldo final": currency(item.closing_balance or 0),
                           "Status": "Aberto" if item.is_open else "Fechado"} for item in history], width="stretch", hide_index=True)
        _render_own_consumption(session)
        return
    balance = cash_balance(session, cash)
    cols = st.columns(3)
    with cols[0]: metric_card("Operador", cash.operator, f"Desde {date_time(cash.opened_at)}")
    with cols[1]: metric_card("Saldo inicial", currency(cash.opening_balance), "Abertura do turno")
    with cols[2]: metric_card("Saldo atual", currency(balance), "Entradas menos saídas")
    st.subheader("Registrar movimento")
    first, second, third = st.columns(3)
    with first:
        movement_type = persistent_selectbox("Tipo", ["Entrada", "Saída"], key="cash.movement_type", default="Entrada")
    with second:
        method = persistent_selectbox("Forma", ["Dinheiro", "Pix", "Crédito", "Débito", "Despesa", "Sangria"],
                                      key="cash.method", default="Dinheiro")
    with third:
        amount = persistent_number_input("Valor", key="cash.amount", default=0.01, min_value=0.01, step=5.0)
    description = persistent_text_input("Descrição", key="cash.description")
    if st.button("Registrar movimento", type="primary", key="cash.movement_button"):
        try:
            add_cash_movement(session, cash, movement_type, method, amount, description,
                              st.session_state.get("acting_user", "SISTEMA_HOMOLOGACAO"))
            st.success("Movimento registrado.")
            st.rerun()
        except ValueError as error:
            st.error(str(error))
    movements = session.scalars(select(CashMovement).where(CashMovement.cash_session_id == cash.id).order_by(CashMovement.created_at.desc())).all()
    if movements:
        st.dataframe([{"Data": date_time(item.created_at), "Tipo": item.movement_type, "Forma": item.method,
                       "Valor": currency(item.amount), "Descrição": item.description} for item in movements], width="stretch", hide_index=True)
    _render_own_consumption(session)
    if st.button("Fechar caixa", type="secondary"):
        final = close_cash(session, cash)
        st.session_state["cash.last_closed_id"] = cash.id
        st.success(f"Caixa fechado. Saldo apurado: {currency(final)}")
        st.rerun()
