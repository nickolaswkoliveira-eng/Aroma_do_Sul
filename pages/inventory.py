from sqlalchemy import func, select
from sqlalchemy.orm import Session
import pandas as pd
import streamlit as st
from pandas.io.formats.style import Styler

from components.layout import metric_card, section_heading
from models.entities import Category, Ingredient, Product, RecipeItem, Stock, StockMovement
from services.domain import audit, move_stock, purchase_recommendations, stock_level
from utils.formatting import currency, date_time
from utils.session_state import (
    persistent_checkbox, persistent_number_input, persistent_selectbox,
    persistent_text_input,
)


def render(session: Session) -> None:
    section_heading("Estoque", "Visibilidade de saldo, custo e risco operacional")
    rows = session.execute(select(Product, Stock).join(Stock, Stock.product_id == Product.id).order_by(Product.name)).all()
    active_count = session.scalar(select(func.count(Product.id)).where(Product.active.is_(True))) or 0
    attention_count = 0
    critical_count = 0
    inventory_value = 0.0
    for product, stock in rows:
        level = stock_level(stock.quantity, stock.minimum_quantity)
        critical_count += int(level in ("Zerado", "Crítico"))
        attention_count += int(level == "Atenção")
        inventory_value += stock.quantity * product.cost_price
    kpis = st.columns(4)
    with kpis[0]: metric_card("Produtos ativos", str(active_count), "No catálogo", prominent=True)
    with kpis[1]: metric_card("Em atenção", str(attention_count), "Acima de 20% e abaixo de 50% do mínimo", prominent=True)
    with kpis[2]: metric_card("Críticos", str(critical_count), "Até 20% do mínimo ou zerados", prominent=True)
    with kpis[3]: metric_card("Valor em estoque", currency(inventory_value), "Custo cadastrado × saldo", prominent=True)
    recommendations = purchase_recommendations(session)
    urgent_actions = [item for item in recommendations if item["needs_action"]]
    st.subheader("Ações recomendadas")
    if urgent_actions:
        action_columns = st.columns(2)
        for index, item in enumerate(urgent_actions[:4]):
            product = item["product"]
            days_left = item["days_remaining"]
            urgency = "🚨" if item["stock"].quantity <= 0 or (days_left is not None and days_left <= 3) else "⚠"
            days_text = f"Restam aproximadamente {days_left:.0f} dias de estoque." if days_left is not None else "Sem consumo recente suficiente para estimar cobertura."
            with action_columns[index % 2]:
                with st.container(border=True):
                    st.markdown(f"**{urgency} Comprar {product.name}**")
                    st.caption(days_text)
                    st.write(f"Sugestão: {item['suggested_quantity']:g} {product.unit}")
                    st.caption(item["reason"])
    else:
        adequate = next((item for item in recommendations if item["days_remaining"] is not None
                         and item["days_remaining"] > 20), None)
        if adequate:
            st.success(f"{adequate['product'].name} em nível adequado · previsão superior a 20 dias.")
        else:
            st.info("Sem itens críticos. Registre movimentações para melhorar previsões de compra.")
    st.write("")
    tabs = st.tabs(["Posição", "Movimentar", "Produtos", "Ficha técnica", "Sugestão de compra"])
    with tabs[0]:
        if rows:
            data = []
            for product, stock in rows:
                level = stock_level(stock.quantity, stock.minimum_quantity)
                data.append({"Código": product.code, "Produto": product.name, "Estoque": f"{stock.quantity:g} {product.unit}",
                             "Mínimo": f"{stock.minimum_quantity:g} {product.unit}", "Custo": currency(product.cost_price), "Nível": level})
            query = persistent_text_input("Pesquisar estoque", key="inventory.search", placeholder="Produto ou código")
            table = pd.DataFrame(data)
            if query:
                match = table["Código"].str.contains(query, case=False, na=False) | table["Produto"].str.contains(query, case=False, na=False)
                table = table[match]
            def row_style(row):
                background = "#FFFFFF" if row.name % 2 == 0 else "#FCFAF7"
                return [f"background-color: {background}; color: #30251D" for _ in row]
            def status_style(value):
                if value in ("Crítico", "Zerado"):
                    return "background-color: #FCE8E5; color: #8E332A; font-weight: 700"
                if value == "Atenção":
                    return "background-color: #FFF3D7; color: #7C5200; font-weight: 700"
                return "background-color: #E8F3EA; color: #315D3B; font-weight: 700"
            styled_table: Styler = table.style.apply(row_style, axis=1).map(status_style, subset=["Nível"])
            st.dataframe(styled_table, width="stretch", height=440, hide_index=True)
            zero_count = sum(stock_level(stock.quantity, stock.minimum_quantity) == "Zerado"
                             for _, stock in rows)
            critical_count = sum(stock_level(stock.quantity, stock.minimum_quantity) == "Crítico"
                                 for _, stock in rows)
            if zero_count:
                st.error(f"{zero_count} item(ns) sem saldo. Confira antes de aceitar novos pedidos.")
            elif critical_count:
                st.warning(f"{critical_count} item(ns) abaixo de 20% do estoque mínimo.")
        else:
            st.info("Cadastre produtos e insumos para iniciar o controle de estoque.")
        movements = session.scalars(select(StockMovement).order_by(StockMovement.created_at.desc()).limit(30)).all()
        if movements:
            with st.expander("Histórico recente de movimentações"):
                st.dataframe([{"Data e hora": date_time(movement.created_at), "Produto": session.get(Product, movement.product_id).name,
                               "Tipo": movement.movement_type, "Quantidade": movement.quantity, "Motivo": movement.reason}
                              for movement in movements], width="stretch", hide_index=True)
    with tabs[1]:
        products = session.scalars(select(Product).order_by(Product.name)).all()
        if products:
            products_by_id = {product.id: product for product in products}
            product_id = persistent_selectbox("Produto / insumo", list(products_by_id), key="inventory.movement.product",
                                              default=products[0].id,
                                              format_func=lambda value: f"{products_by_id[value].name} · {products_by_id[value].unit}")
            product = products_by_id[product_id]
            movement_type = persistent_selectbox("Movimentação", ["Entrada", "Saída", "Ajuste", "Perda"],
                                                 key="inventory.movement.type", default="Entrada")
            amount = persistent_number_input("Quantidade", key="inventory.movement.quantity", default=0.01,
                                             min_value=0.01, step=1.0)
            reason = persistent_text_input("Motivo", key="inventory.movement.reason")
            if st.button("Registrar movimentação", type="primary", key="inventory.movement.submit"):
                try:
                    move_stock(session, product.id, movement_type, amount, reason,
                               st.session_state.get("acting_user", "SISTEMA_HOMOLOGACAO"))
                    st.success("Movimentação registrada e auditada.")
                    st.rerun()
                except ValueError as error:
                    st.error(str(error))
    with tabs[2]:
        categories = session.scalars(select(Category).order_by(Category.name)).all()
        with st.expander("Cadastrar categoria"):
            category_name = persistent_text_input("Nome da categoria", key="inventory.category.new_name")
            if st.button("Adicionar categoria", key="inventory.category.submit"):
                if not category_name.strip():
                    st.error("Informe o nome da categoria.")
                elif session.scalar(select(Category).where(Category.name == category_name.strip())):
                    st.error("Esta categoria já existe.")
                else:
                    session.add(Category(name=category_name.strip()))
                    audit(session, "Categoria cadastrada", category_name.strip(),
                          st.session_state.get("acting_user", "SISTEMA_HOMOLOGACAO"))
                    session.commit()
                    st.success("Categoria criada.")
                    st.rerun()
        categories_by_id = {category.id: category for category in categories}
        code_column, name_column = st.columns(2)
        with code_column:
            code = persistent_text_input("Código", key="inventory.product.code")
        with name_column:
            name = persistent_text_input("Nome", key="inventory.product.name")
        category_column, unit_column = st.columns(2)
        with category_column:
            category_id = persistent_selectbox("Categoria", list(categories_by_id), key="inventory.product.category",
                                               default=categories[0].id if categories else None,
                                               format_func=lambda value: categories_by_id[value].name) if categories else None
        with unit_column:
            unit = persistent_selectbox("Unidade", ["un", "kg", "g", "L", "ml", "fatia", "porção"],
                                        key="inventory.product.unit", default="un")
        stock_column, minimum_column = st.columns(2)
        with stock_column:
            initial_stock = persistent_number_input("Estoque atual", key="inventory.product.initial_stock",
                                                    default=0.0, min_value=0.0, step=1.0)
        with minimum_column:
            minimum = persistent_number_input("Estoque mínimo", key="inventory.product.minimum", default=0.0,
                                              min_value=0.0, step=1.0)
        cost_column, sale_column = st.columns(2)
        with cost_column:
            cost = persistent_number_input("Preço de custo", key="inventory.product.cost", default=0.0,
                                           min_value=0.0, step=0.5)
        with sale_column:
            sale = persistent_number_input("Preço de venda", key="inventory.product.sale", default=0.0,
                                           min_value=0.0, step=0.5)
        if st.button("Cadastrar produto", type="primary", key="inventory.product.submit"):
            if not code or not name:
                st.error("Informe código e nome.")
            elif session.scalar(select(Product).where(Product.code == code)):
                st.error("Este código já está cadastrado.")
            else:
                product = Product(code=code, name=name, category_id=category_id,
                                  unit=unit, cost_price=cost, sale_price=sale)
                session.add(product)
                session.flush()
                session.add(Stock(product_id=product.id, quantity=initial_stock, minimum_quantity=minimum))
                responsible = st.session_state.get("acting_user", "SISTEMA_HOMOLOGACAO")
                session.add(StockMovement(product_id=product.id, movement_type="Entrada", quantity=initial_stock,
                                          reason="Saldo inicial do cadastro", responsible=responsible))
                audit(session, "Produto cadastrado", f"{code} · {name}", responsible)
                session.commit()
                st.success("Produto cadastrado.")
                st.rerun()
        edit_products = session.scalars(select(Product).order_by(Product.name)).all()
        if edit_products:
            with st.expander("Editar produto, preço e estoque mínimo"):
                edit_products_by_id = {product.id: product for product in edit_products}
                selected_product_id = persistent_selectbox("Produto para editar", list(edit_products_by_id),
                                                           key="inventory.edit.product",
                                                           default=edit_products[0].id,
                                                           format_func=lambda value: f"{edit_products_by_id[value].code} · {edit_products_by_id[value].name}")
                selected_product = edit_products_by_id[selected_product_id]
                selected_stock = session.scalar(select(Stock).where(Stock.product_id == selected_product.id))
                unit_options = list(dict.fromkeys([selected_product.unit, "un", "kg", "g", "L", "ml", "fatia", "porção"]))
                edit_key = f"inventory.edit.{selected_product.id}"
                edit_name = persistent_text_input("Nome", key=f"{edit_key}.name", default=selected_product.name)
                edit_category_id = persistent_selectbox("Categoria", list(categories_by_id),
                                                        key=f"{edit_key}.category",
                                                        default=selected_product.category_id or categories[0].id,
                                                        format_func=lambda value: categories_by_id[value].name) if categories else None
                edit_unit = persistent_selectbox("Unidade", unit_options, key=f"{edit_key}.unit",
                                                default=selected_product.unit)
                first, second = st.columns(2)
                with first:
                    edit_cost = persistent_number_input("Custo", key=f"{edit_key}.cost",
                                                        default=float(selected_product.cost_price), min_value=0.0, step=0.5)
                with second:
                    edit_sale = persistent_number_input("Venda", key=f"{edit_key}.sale",
                                                        default=float(selected_product.sale_price), min_value=0.0, step=0.5)
                edit_minimum = persistent_number_input("Estoque mínimo", key=f"{edit_key}.minimum",
                                                       default=float(selected_stock.minimum_quantity if selected_stock else 0),
                                                       min_value=0.0, step=1.0)
                edit_active = persistent_checkbox("Produto ativo", key=f"{edit_key}.active",
                                                  default=selected_product.active)
                if st.button("Salvar alterações", type="primary", key=f"{edit_key}.submit"):
                    previous_cost, previous_sale = selected_product.cost_price, selected_product.sale_price
                    selected_product.name = edit_name.strip()
                    selected_product.category_id = edit_category_id
                    selected_product.unit = edit_unit
                    selected_product.cost_price = edit_cost
                    selected_product.sale_price = edit_sale
                    selected_product.active = edit_active
                    if selected_stock is None:
                        selected_stock = Stock(product_id=selected_product.id, quantity=0, minimum_quantity=edit_minimum)
                        session.add(selected_stock)
                    else:
                        selected_stock.minimum_quantity = edit_minimum
                    responsible = st.session_state.get("acting_user", "SISTEMA_HOMOLOGACAO")
                    if previous_cost != edit_cost or previous_sale != edit_sale:
                        audit(session, "Preço de produto alterado",
                              f"{selected_product.code}: custo {previous_cost:.2f} → {edit_cost:.2f}; venda {previous_sale:.2f} → {edit_sale:.2f}",
                              responsible)
                    audit(session, "Produto atualizado", f"{selected_product.code} · {selected_product.name}", responsible)
                    session.commit()
                    st.success("Produto atualizado.")
                    st.rerun()
    with tabs[3]:
        sellable = session.scalars(select(Product).where(Product.sale_price > 0).order_by(Product.name)).all()
        ingredient_products = session.scalars(select(Product).join(Ingredient, Ingredient.product_id == Product.id)
                                              .order_by(Product.name)).all()
        if not sellable or not ingredient_products:
            st.info("Cadastre produtos vendáveis e insumos antes de montar fichas técnicas.")
        else:
            sellable_by_id = {product.id: product for product in sellable}
            ingredients_by_id = {product.id: product for product in ingredient_products}
            sold_product_id = persistent_selectbox("Produto vendido", list(sellable_by_id),
                                                   key="inventory.recipe.product", default=sellable[0].id,
                                                   format_func=lambda value: f"{sellable_by_id[value].code} · {sellable_by_id[value].name}")
            ingredient_id = persistent_selectbox("Ingrediente consumido", list(ingredients_by_id),
                                                 key="inventory.recipe.ingredient", default=ingredient_products[0].id,
                                                 format_func=lambda value: f"{ingredients_by_id[value].name} · {ingredients_by_id[value].unit}")
            sold_product = sellable_by_id[sold_product_id]
            ingredient = ingredients_by_id[ingredient_id]
            recipe_quantity = persistent_number_input("Quantidade consumida por unidade vendida",
                                                      key="inventory.recipe.quantity", default=1.0,
                                                      min_value=0.001, step=0.1, format="%.3f")
            if st.button("Adicionar à ficha técnica", type="primary", key="inventory.recipe.submit"):
                recipe = session.scalar(select(RecipeItem).where(RecipeItem.product_id == sold_product.id,
                                                                 RecipeItem.ingredient_id == ingredient.id))
                if recipe:
                    recipe.quantity = recipe_quantity
                else:
                    session.add(RecipeItem(product_id=sold_product.id, ingredient_id=ingredient.id,
                                           quantity=recipe_quantity))
                audit(session, "Ficha técnica atualizada", f"{sold_product.name}: {recipe_quantity:g} {ingredient.unit} {ingredient.name}",
                      st.session_state.get("acting_user", "SISTEMA_HOMOLOGACAO"))
                session.commit()
                st.success("Ficha técnica atualizada.")
                st.rerun()
            recipes = session.scalars(select(RecipeItem).order_by(RecipeItem.product_id, RecipeItem.id)).all()
            for recipe in recipes:
                sold_product = session.get(Product, recipe.product_id)
                ingredient = session.get(Product, recipe.ingredient_id)
                first, second = st.columns([5, 1])
                first.write(f"{sold_product.name}: {recipe.quantity:g} {ingredient.unit} {ingredient.name}")
                if second.button("Remover", key=f"remove_recipe_{recipe.id}"):
                    audit(session, "Item removido da ficha técnica", f"{sold_product.name} · {ingredient.name}",
                          st.session_state.get("acting_user", "SISTEMA_HOMOLOGACAO"))
                    session.delete(recipe)
                    session.commit()
                    st.rerun()
    with tabs[4]:
        st.caption("Cálculo com saídas/perdas dos últimos 7 dias, comparadas aos 7 dias anteriores. Meta de cobertura: 14 dias.")
        suggestions = [item for item in recommendations if item["needs_action"]]
        if suggestions:
            columns = st.columns(2)
            for index, item in enumerate(suggestions):
                product = item["product"]
                days_text = f"{item['days_remaining']:.0f} dias restantes" if item["days_remaining"] is not None else "Cobertura não estimada"
                with columns[index % 2]:
                    with st.container(border=True):
                        st.markdown(f"### {product.name}")
                        st.caption(f"Saldo: {item['stock'].quantity:g} {product.unit} · {days_text}")
                        st.write(f"Consumo médio: {item['daily_average']:.2f} {product.unit}/dia")
                        st.markdown(f"**Sugestão: comprar {item['suggested_quantity']:g} {product.unit}**")
                        st.caption(item["reason"])
        else:
            st.success("Sem sugestão de compra imediata. Estoque acima da cobertura recomendada.")
