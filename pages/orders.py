from sqlalchemy import func, select
from sqlalchemy.orm import Session
import streamlit as st

from components.layout import metric_card, section_heading
from models.entities import Category, Order, OrderItem, Product, Stock
from services.domain import create_order
from utils.clock import local_today
from utils.formatting import currency, date_time
from utils.session_state import (
    persist_value, persistent_number_input, persistent_selectbox, persistent_text_input,
    persistent_widget,
)


def render(session: Session) -> None:
    section_heading("Pedidos", "Monte o pedido e acompanhe o atendimento")
    if "cart" not in st.session_state:
        st.session_state.cart = {}
    active_orders = session.scalar(select(func.count(Order.id)).where(Order.status.in_(("Recebido", "Em preparo")))) or 0
    waiting_orders = session.scalar(select(func.count(Order.id)).where(Order.status == "Recebido")) or 0
    completed_today = session.scalar(select(func.count(Order.id)).where(
        Order.status == "Finalizado", func.date(Order.finished_at) == local_today())) or 0
    status_cols = st.columns(3)
    with status_cols[0]: metric_card("Pedidos ativos", str(active_orders), "Em atendimento")
    with status_cols[1]: metric_card("Aguardando preparo", str(waiting_orders), "Na fila da cozinha")
    with status_cols[2]: metric_card("Concluídos hoje", str(completed_today), "Finalizados")
    products = session.scalars(select(Product).where(Product.active.is_(True), Product.sale_price > 0).order_by(Product.name)).all()
    categories = session.scalars(select(Category).where(Category.active.is_(True)).order_by(Category.name)).all()
    products_by_id = {product.id: product for product in products}
    category_by_id = {category.id: category.name for category in categories}
    stock_by_product = {stock.product_id: stock for stock in session.scalars(select(Stock).where(
        Stock.product_id.in_(products_by_id) if products_by_id else Stock.id == -1)).all()}
    favorites = st.session_state.setdefault("orders.favorites", set())
    best_sellers = session.execute(select(OrderItem.product_id, func.sum(OrderItem.quantity).label("units"))
                                   .join(Order, Order.id == OrderItem.order_id).group_by(OrderItem.product_id)
                                   .order_by(func.sum(OrderItem.quantity).desc())).all()
    popular_ids = {row.product_id for row in best_sellers[:8]}
    last_sold_rows = session.execute(select(OrderItem.product_id, func.max(Order.created_at).label("last_sold"))
                                     .join(Order, Order.id == OrderItem.order_id)
                                     .group_by(OrderItem.product_id)).all()
    last_sold = {row.product_id: row.last_sold for row in last_sold_rows}
    category_names = ["Todas"] + [category.name for category in categories]
    category_column, mode_column, search_column = st.columns([1, 1, 2])
    with category_column:
        selected_category = persistent_selectbox("Categoria", category_names, key="orders.category", default="Todas")
    with mode_column:
        filter_mode = persistent_selectbox("Exibir", ["Todos", "Favoritos", "Mais vendidos", "Últimos vendidos"],
                                           key="orders.product_filter", default="Todos")
    with search_column:
        search = persistent_text_input("Buscar produto", key="orders.search", placeholder="Nome ou código")
    visible = [product for product in products
               if (selected_category == "Todas" or category_by_id.get(product.category_id) == selected_category)
               and (filter_mode != "Favoritos" or product.id in favorites)
               and (filter_mode != "Mais vendidos" or product.id in popular_ids)
               and (filter_mode != "Últimos vendidos" or product.id in last_sold)
               and (not search or search.casefold() in product.name.casefold() or search.casefold() in product.code.casefold())]
    visible.sort(key=lambda product: (
        product.id not in favorites,
        product.id not in popular_ids,
        -(last_sold[product.id].timestamp() if product.id in last_sold else 0),
        product.name.casefold(),
    ))
    page_size = 9
    page_count = max(1, (len(visible) + page_size - 1) // page_size)
    catalog_page = min(int(st.session_state.get("orders.catalog_page", 1)), page_count)
    st.session_state["orders.catalog_page"] = catalog_page
    page_start = (catalog_page - 1) * page_size
    visible = visible[page_start:page_start + page_size]
    catalog, summary = st.columns([2.15, 1], gap="large")
    with catalog:
        st.caption(f"{len(visible)} produtos disponíveis")
        if not visible:
            st.info("Nenhum produto corresponde aos filtros atuais.")
        grid = st.columns(3)
        for index, product in enumerate(visible):
            with grid[index % 3]:
                with st.container(key=f"product_card_{product.id}"):
                    stock = stock_by_product.get(product.id)
                    stock_label = f"{stock.quantity:g} {product.unit} em estoque" if stock else "Sem saldo cadastrado"
                    st.markdown(f'<div class="product-card"><div class="panel-label">{category_by_id.get(product.category_id, "Produto")}</div><div class="module-title">{product.name}</div><div class="panel-value">{currency(product.sale_price)}</div><div class="panel-note">{product.code} · {stock_label}</div></div>', unsafe_allow_html=True)
                    if st.button("★" if product.id in favorites else "☆", key=f"favorite_{product.id}",
                                 help="Remover dos favoritos" if product.id in favorites else "Adicionar aos favoritos"):
                        if product.id in favorites:
                            favorites.remove(product.id)
                        else:
                            favorites.add(product.id)
                        st.rerun()
                    quantity = persistent_number_input("Quantidade", key=f"orders.quantity.{product.id}",
                                                       default=1, min_value=1, max_value=50)
                    note = persistent_text_input("Observação", key=f"orders.note.{product.id}",
                                                 placeholder="Ex.: sem açúcar")
                    if st.button("Adicionar", key=f"add_{product.id}", width="stretch"):
                        current = st.session_state.cart.get(product.id, {"quantity": 0, "notes": note})
                        current["quantity"] += int(quantity)
                        current["notes"] = note
                        st.session_state.cart[product.id] = current
                        st.rerun()
        if page_count > 1:
            previous, page_label, next_button = st.columns([1, 2, 1])
            if previous.button("←", help="Produtos anteriores", disabled=catalog_page <= 1, key="orders.catalog.previous"):
                st.session_state["orders.catalog_page"] = catalog_page - 1
                st.rerun()
            page_label.caption(f"Produtos {page_start + 1}–{min(page_start + page_size, len(visible) + page_start)} · página {catalog_page}/{page_count}")
            if next_button.button("→", help="Mais produtos", disabled=catalog_page >= page_count, key="orders.catalog.next"):
                st.session_state["orders.catalog_page"] = catalog_page + 1
                st.rerun()
    subtotal = sum(products_by_id[product_id].sale_price * item["quantity"]
                   for product_id, item in st.session_state.cart.items() if product_id in products_by_id)
    discount = 0.0
    total = subtotal - discount
    with summary:
        with st.container(key="order_summary_panel"):
            st.markdown("### Resumo do pedido")
            st.caption(f"{sum(item['quantity'] for item in st.session_state.cart.values())} itens")
            if not st.session_state.cart:
                st.caption("Adicione produtos para começar.")
            for product_id, item in list(st.session_state.cart.items()):
                product = products_by_id.get(product_id)
                if not product:
                    continue
                line, remove = st.columns([5, 1])
                line.markdown(f"**{item['quantity']}× {product.name}**  \n{currency(product.sale_price * item['quantity'])}")
                if remove.button("×", key=f"remove_order_item_{product_id}", help="Remover item"):
                    st.session_state.cart.pop(product_id, None)
                    st.rerun()
                if item.get("notes"):
                    st.caption(item["notes"])
            st.divider()
            st.write(f"Subtotal · {currency(subtotal)}")
            st.write(f"Descontos · {currency(discount)}")
            st.markdown(f"### Total · {currency(total)}")
            customer_name = st.text_input("Cliente (opcional)", **persistent_widget("orders.customer_name", ""))
            phone = st.text_input("Telefone (opcional)", **persistent_widget("orders.customer_phone", ""))
            notes = st.text_input("Observações do pedido", **persistent_widget("orders.notes", ""))
            if st.button("Finalizar Pedido", type="primary", width="stretch", disabled=not st.session_state.cart):
                try:
                    created = create_order(session, [{"product_id": product_id, **item} for product_id, item in st.session_state.cart.items()],
                                           customer_name, phone, notes, st.session_state.get("acting_user", "SISTEMA_HOMOLOGACAO"))
                    st.session_state.cart = {}
                    st.success(f"Pedido #{created.id} enviado para preparo.")
                    st.rerun()
                except ValueError as error:
                    st.error(str(error))
    st.divider()
    st.subheader("Pedidos recentes")
    page_size = 12
    total_orders = session.scalar(select(func.count(Order.id))) or 0
    page_count = max(1, (total_orders + page_size - 1) // page_size)
    current_page = min(int(st.session_state.get("orders.page", 1)), page_count)
    if current_page != st.session_state.get("orders.page", 1):
        st.session_state["orders.page"] = current_page
        persist_value("orders.page", current_page)
    orders = session.scalars(select(Order).order_by(Order.created_at.desc())
                             .offset((current_page - 1) * page_size).limit(page_size)).all()
    for order in orders:
        items = session.scalars(select(OrderItem).where(OrderItem.order_id == order.id)).all()
        product_names = [session.get(Product, item.product_id).name for item in items]
        st.write(f"**#{order.id} · {order.status}** · {date_time(order.created_at)} · {', '.join(product_names)} · {currency(order.total)}")
    if page_count > 1:
        previous, page_label, next_button = st.columns([1, 2, 1])
        if previous.button("← Anterior", disabled=current_page <= 1, key="orders.previous"):
            st.session_state["orders.page"] = current_page - 1
            persist_value("orders.page", current_page - 1)
            st.rerun()
        page_label.caption(f"Página {current_page} de {page_count}")
        if next_button.button("Próxima →", disabled=current_page >= page_count, key="orders.next"):
            st.session_state["orders.page"] = current_page + 1
            persist_value("orders.page", current_page + 1)
            st.rerun()
