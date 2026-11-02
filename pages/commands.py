from html import escape

from sqlalchemy import select
from sqlalchemy.orm import Session
import streamlit as st

from components.layout import metric_card, section_heading
from models.entities import CashSession, Comanda, ComandaOrder, Customer, Order, OrderItem, Product
from services.domain import TABLE_MAX, assign_comanda_table, close_comanda
from utils.formatting import currency, date_time


PAYMENT_METHODS = ("Dinheiro", "Pix", "Crédito", "Débito")


def _customer_label(session: Session, comanda: Comanda) -> str:
    customer = session.get(Customer, comanda.customer_id) if comanda.customer_id else None
    return customer.name if customer else "Cliente sem cadastro"


def _render_tables_panel(open_comandas: list[Comanda]) -> None:
    st.subheader("Painel de mesas")
    by_table = {
        comanda.table_number: comanda
        for comanda in open_comandas
        if comanda.table_number is not None
    }
    cards = st.columns(min(TABLE_MAX, 5))
    for table_number in range(1, TABLE_MAX + 1):
        card = cards[(table_number - 1) % len(cards)]
        comanda = by_table.get(table_number)
        with card:
            title = f"Mesa {table_number:02d}"
            if comanda is None:
                metric_card(title, "Livre", "Sem comanda aberta")
            else:
                status = "Aguardando preparo" if comanda.total <= 0 else currency(comanda.total)
                metric_card(title, f"Comanda #{comanda.id}", status)


def _comanda_pending_orders(
    comanda: Comanda,
    links_by_comanda: dict[int, list[ComandaOrder]],
    orders_by_id: dict[int, Order],
) -> list[Order]:
    comanda_orders = [
        orders_by_id[link.order_id]
        for link in links_by_comanda.get(comanda.id, [])
        if link.order_id in orders_by_id
    ]
    return [order for order in comanda_orders if order.status != "Finalizado"]


def render(
    session: Session,
    can_add: bool = False,
    can_close: bool = False,
) -> None:
    section_heading("Comandas", "Atendimentos abertos e cobrança no caixa")
    open_comandas = session.scalars(
        select(Comanda)
        .where(Comanda.status == "Aberta")
        .order_by(Comanda.created_at)
    ).all()
    cash_is_open = session.scalar(
        select(CashSession.id).where(CashSession.is_open.is_(True)).limit(1)
    ) is not None
    metric_card("Comandas abertas", str(len(open_comandas)), "Aguardando fechamento")
    if not open_comandas:
        _render_tables_panel(open_comandas)
        st.success("Nenhuma comanda em aberto.")
        return
    _render_tables_panel(open_comandas)

    comanda_ids = [comanda.id for comanda in open_comandas]
    order_links = session.scalars(
        select(ComandaOrder).where(ComandaOrder.comanda_id.in_(comanda_ids))
    ).all()
    links_by_comanda: dict[int, list[ComandaOrder]] = {}
    for link in order_links:
        links_by_comanda.setdefault(link.comanda_id, []).append(link)
    order_ids = [link.order_id for link in order_links]
    orders = session.scalars(select(Order).where(Order.id.in_(order_ids))).all() if order_ids else []
    orders_by_id = {order.id: order for order in orders}
    order_items = session.scalars(
        select(OrderItem).where(OrderItem.order_id.in_(order_ids))
    ).all() if order_ids else []
    items_by_order: dict[int, list[OrderItem]] = {}
    for item in order_items:
        items_by_order.setdefault(item.order_id, []).append(item)
    product_ids = {item.product_id for item in order_items}
    products_by_id = {
        product.id: product for product in session.scalars(select(Product).where(Product.id.in_(product_ids))).all()
    } if product_ids else {}
    customer_ids = {comanda.customer_id for comanda in open_comandas if comanda.customer_id}
    customers_by_id = {
        customer.id: customer.name for customer in session.scalars(select(Customer).where(Customer.id.in_(customer_ids))).all()
    } if customer_ids else {}
    pending_by_comanda = {
        comanda.id: _comanda_pending_orders(comanda, links_by_comanda, orders_by_id)
        for comanda in open_comandas
    }

    if can_close:
        with st.expander("Finalização em lote por mesa"):
            if not cash_is_open:
                st.warning("Caixa fechado: abertura obrigatória para recebimentos.")
            ready = [
                comanda
                for comanda in open_comandas
                if comanda.table_number is not None and not pending_by_comanda.get(comanda.id)
            ]
            if not ready:
                st.caption("Nenhuma comanda de mesa pronta para fechamento em lote.")
            else:
                batch_labels = {
                    comanda.id: (
                        f"Mesa {comanda.table_number:02d} · Comanda #{comanda.id} · "
                        f"{currency(comanda.total)}"
                    )
                    for comanda in ready
                }
                selected_comandas = st.multiselect(
                    "Mesas prontas para fechamento",
                    [comanda.id for comanda in ready],
                    format_func=lambda value: batch_labels[value],
                    key="comanda_batch_selection",
                )
                batch_method = st.selectbox(
                    "Forma de pagamento (lote)",
                    PAYMENT_METHODS,
                    key="comanda_batch_payment",
                )
                if st.button(
                    "Fechar comandas selecionadas",
                    key="comanda_batch_close",
                    type="primary",
                    disabled=not selected_comandas or not cash_is_open,
                    width="stretch",
                ):
                    closed: list[int] = []
                    errors: list[str] = []
                    for comanda_id in selected_comandas:
                        target = next((item for item in ready if item.id == comanda_id), None)
                        if target is None:
                            continue
                        try:
                            close_comanda(
                                session,
                                target,
                                batch_method,
                                st.session_state.get("acting_user", "SISTEMA_HOMOLOGACAO"),
                            )
                            closed.append(target.id)
                        except ValueError as error:
                            errors.append(f"Comanda #{target.id}: {error}")
                    if closed:
                        st.success(
                            "Comandas fechadas: " + ", ".join(f"#{comanda_id}" for comanda_id in closed)
                        )
                    for message in errors:
                        st.error(message)
                    if closed:
                        st.rerun()

    for comanda in open_comandas:
        customer_name = customers_by_id.get(comanda.customer_id, "Cliente sem cadastro")
        comanda_orders = [
            orders_by_id[link.order_id]
            for link in links_by_comanda.get(comanda.id, [])
            if link.order_id in orders_by_id
        ]
        pending_orders = pending_by_comanda.get(comanda.id, [])
        with st.container(key=f"comanda_{comanda.id}"):
            table_label = f"Mesa {comanda.table_number:02d}" if comanda.table_number is not None else "Sem mesa"
            st.markdown(f"### Comanda #{comanda.id} · {table_label} · {escape(customer_name)}")
            st.caption(f"Aberta às {date_time(comanda.created_at)}")
            st.markdown(f"**Total da conta · {currency(comanda.total)}**")
            for order in comanda_orders:
                st.markdown(f"**Pedido #{order.id} · {order.status}**")
                items = items_by_order.get(order.id, [])
                for item in items:
                    product = products_by_id.get(item.product_id)
                    if product:
                        st.write(
                            f"{item.quantity}× {product.name} · "
                            f"{currency(item.quantity * item.unit_price)}"
                        )
            if pending_orders:
                st.info(
                    "Há pedidos em preparo. A conta poderá ser fechada quando "
                    "todos forem finalizados na cozinha."
                )
            actions = st.columns([1, 1, 1, 2])
            if can_add:
                with actions[0]:
                    if st.button(
                        "Adicionar pedido",
                        key=f"comanda_add_{comanda.id}",
                        width="stretch",
                        disabled=not cash_is_open,
                    ):
                        st.session_state["orders.comanda_target"] = comanda.id
                        st.session_state.active_page = "Pedidos"
                        st.query_params["pagina"] = "Pedidos"
                        st.rerun()
            else:
                actions[0].caption("Sem permissão para adicionar pedidos.")
            with actions[1]:
                table_number = st.selectbox(
                    "Mesa",
                    [None, *range(1, TABLE_MAX + 1)],
                    index=(
                        comanda.table_number
                        if comanda.table_number in range(1, TABLE_MAX + 1)
                        else 0
                    ),
                    format_func=lambda value: "Sem mesa / balcão" if value is None else f"Mesa {value:02d}",
                    key=f"comanda_table_{comanda.id}",
                )
                if st.button("Salvar mesa", key=f"comanda_table_save_{comanda.id}", width="stretch"):
                    try:
                        assign_comanda_table(
                            session,
                            comanda,
                            table_number,
                            st.session_state.get("acting_user", "SISTEMA_HOMOLOGACAO"),
                        )
                        st.success("Mesa atualizada.")
                        st.rerun()
                    except ValueError as error:
                        st.error(str(error))
            if can_close:
                with actions[2]:
                    method = st.selectbox(
                        "Pagamento",
                        PAYMENT_METHODS,
                        key=f"comanda_payment_{comanda.id}",
                        label_visibility="collapsed",
                    )
                with actions[3]:
                    if st.button(
                        "Fechar e receber",
                        key=f"comanda_close_{comanda.id}",
                        type="primary",
                        width="stretch",
                        disabled=bool(pending_orders) or not cash_is_open,
                    ):
                        try:
                            total = close_comanda(
                                session,
                                comanda,
                                method,
                                st.session_state.get(
                                    "acting_user", "SISTEMA_HOMOLOGACAO"
                                ),
                            )
                            st.success(
                                f"Comanda #{comanda.id} fechada. "
                                f"Recebido {currency(total)}."
                            )
                            st.rerun()
                        except ValueError as error:
                            st.error(str(error))
            else:
                actions[1].caption("A cobrança é restrita ao Caixa.")
            if not cash_is_open:
                st.warning("Caixa fechado: abertura obrigatória para novos pedidos e recebimentos.")
            st.divider()
