from datetime import date, datetime, timedelta
from sqlalchemy import func, select
from sqlalchemy.orm import Session
import pandas as pd
import plotly.express as px
import streamlit as st

from components.layout import metric_card, module_card, section_heading
from components.charts import apply_chart_theme, format_sales_series
from models.entities import CashMovement, CashSession, Order, OrderItem, Payable, Product, Receivable, Stock, StockMovement
from services.domain import projected_cash
from utils.formatting import currency, date_only, date_time
from utils.palette import CHART_COLORS, CHART_SCALE
from utils.session_state import persistent_date_input, persistent_selectbox, persistent_select_slider

REPORTS = ["Vendas", "Estoque", "Financeiro", "DRE", "Produtos", "Horários", "Caixa", "Fluxo de caixa"]
REPORT_CARDS = {
    "Vendas": ("📊", "Faturamento, ticket médio e pedidos por período."),
    "Estoque": ("📦", "Posição, consumo médio e cobertura de estoque."),
    "Financeiro": ("💰", "Contas a pagar, recebíveis e vencimentos."),
    "DRE": ("📈", "Resultado operacional e análise vertical."),
    "Produtos": ("🍔", "Ranking, margem e participação de vendas."),
    "Horários": ("🕒", "Distribuição de pedidos por dia e hora."),
    "Caixa": ("🧾", "Turnos, entradas e saídas registrados."),
    "Fluxo de caixa": ("↗", "Projeção de saldo para os próximos períodos."),
}


def _sales(session: Session, start: date, end: date):
    return session.scalars(select(Order).where(func.date(Order.created_at) >= start,
                                               func.date(Order.created_at) <= end).order_by(Order.created_at)).all()


def render(session: Session) -> None:
    section_heading("Relatórios", "Consulta de dados operacionais e financeiros")
    available = list(REPORTS)
    if st.session_state.get("current_role") == "CAIXA":
        available = ["Vendas"]
    if st.session_state.get("reports_hide_dre"):
        available = [item for item in available if item != "DRE"]
    selected = st.session_state.get("report_section", "Vendas")
    if selected not in available:
        selected = available[0]
        st.session_state.report_section = selected
    cols = st.columns(4)
    for index, report in enumerate(available):
        icon, description = REPORT_CARDS[report]
        with cols[index % 4]:
            with st.container(key=f"module_card_report_{report.lower().replace(' ', '_')}"):
                st.markdown(f'<div class="module-icon">{icon}</div><div class="module-title">{report}</div><div class="module-description">{description}</div>', unsafe_allow_html=True)
                if st.button("Abrir relatório →", key=f"report_{report}", width="stretch",
                             type="primary" if selected == report else "secondary"):
                    st.session_state.report_section = report
                    st.rerun()
    selected = st.session_state.get("report_section", "Vendas")
    st.divider()
    if selected == "Vendas":
        _sales_report(session, basic=st.session_state.get("current_role") == "CAIXA")
    elif selected == "Produtos":
        _product_report(session)
    elif selected == "Estoque":
        _stock_report(session)
    elif selected == "DRE":
        _dre_report(session)
    elif selected == "Horários":
        _peak_report(session)
    elif selected == "Financeiro":
        _finance_report(session)
    elif selected == "Caixa":
        _cash_report(session)
    elif selected == "Fluxo de caixa":
        _cashflow_report(session)


def _period() -> tuple[date, date]:
    preset = persistent_selectbox("Período", ["Dia", "Semana", "Mês", "Ano", "Personalizado"],
                                  key="reports.period", default="Mês")
    today = date.today()
    if preset == "Dia":
        return today, today
    if preset == "Semana":
        return today - timedelta(days=today.weekday()), today
    if preset == "Mês":
        return today.replace(day=1), today
    if preset == "Ano":
        return today.replace(month=1, day=1), today
    value = persistent_date_input("Intervalo", key="reports.custom_period",
                                  default=(today - timedelta(days=30), today), format="DD/MM/YYYY")
    return value if isinstance(value, tuple) and len(value) == 2 else (today - timedelta(days=30), today)


def _sales_report(session: Session, basic: bool = False) -> None:
    start, end = _period()
    orders = _sales(session, start, end)
    order_ids = [order.id for order in orders]
    items = session.scalars(select(OrderItem).where(OrderItem.order_id.in_(order_ids))).all() if order_ids else []
    costs = sum(item.quantity * session.get(Product, item.product_id).cost_price for item in items)
    revenue = sum(order.total for order in orders)
    average = revenue / len(orders) if orders else 0
    cols = st.columns(3 if basic else 4)
    with cols[0]: metric_card("Faturamento", currency(revenue), f"{start:%d/%m} a {end:%d/%m/%Y}")
    if not basic:
        with cols[1]: metric_card("Lucro bruto estimado", currency(revenue - costs), "Receita menos custo cadastrado")
    with cols[1 if basic else 2]: metric_card("Ticket médio", currency(average), "Por pedido registrado")
    with cols[2 if basic else 3]: metric_card("Pedidos", str(len(orders)), "No período")
    period = st.session_state.get("reports.period", "Mês")
    labels, values = format_sales_series(orders, period)
    frame = pd.DataFrame({"Período": labels, "Faturamento": values})
    if not frame.empty:
        chart = px.line(frame, x="Período", y="Faturamento", markers=True, color_discrete_sequence=CHART_COLORS)
        if len(labels) == 1:
            chart.update_traces(text=[currency(values[0])], texttemplate="%{text}", textposition="top center")
        chart.update_layout(height=360, xaxis={"type": "category", "categoryorder": "array", "categoryarray": labels})
        apply_chart_theme(chart, single_point=len(labels) == 1)
        st.plotly_chart(chart, width="stretch")
    else:
        st.info("Sem vendas no período selecionado.")
    production = [(order.ready_at - order.started_at).total_seconds() / 60 for order in orders
                  if order.started_at and order.ready_at]
    delivery = [(order.delivered_at - order.ready_at).total_seconds() / 60 for order in orders
                if order.ready_at and order.delivered_at]
    total_time = [(order.finished_at - order.created_at).total_seconds() / 60 for order in orders
                  if order.finished_at]
    with st.expander("Tempos operacionais"):
        timing = st.columns(3)
        with timing[0]: metric_card("Produção média", f"{sum(production) / len(production):.0f} min" if production else "Sem dados", "Início até pronto")
        with timing[1]: metric_card("Entrega média", f"{sum(delivery) / len(delivery):.0f} min" if delivery else "Sem dados", "Pronto até entregue")
        with timing[2]: metric_card("Tempo total", f"{sum(total_time) / len(total_time):.0f} min" if total_time else "Sem dados", "Pedido até finalizado")


def _product_report(session: Session) -> None:
    start, end = _period()
    rows = session.execute(select(Product.name, func.sum(OrderItem.quantity).label("units"),
                                 func.sum(OrderItem.quantity * OrderItem.unit_price).label("revenue"))
                           .join(OrderItem, OrderItem.product_id == Product.id).join(Order, Order.id == OrderItem.order_id)
                           .where(func.date(Order.created_at) >= start, func.date(Order.created_at) <= end)
                           .group_by(Product.id).order_by(func.sum(OrderItem.quantity).desc())).all()
    if not rows:
        st.info("Sem itens vendidos no período.")
        return
    frame = pd.DataFrame([{"Produto": row.name, "Unidades": row.units, "Faturamento": row.revenue,
                           "Margem": (row.revenue - row.units * session.scalar(select(Product.cost_price).where(Product.name == row.name))) / row.revenue if row.revenue else 0}
                          for row in rows])
    frame["Pareto %"] = frame["Faturamento"].cumsum() / frame["Faturamento"].sum() * 100
    first, second = st.columns(2)
    with first:
        st.subheader("Ranking de vendas")
        fig = px.bar(frame.head(12), x="Unidades", y="Produto", orientation="h", color="Unidades", color_continuous_scale=CHART_SCALE)
        fig.update_layout(height=420, yaxis={"categoryorder": "total ascending"}, margin=dict(l=0, r=0, t=10, b=0))
        apply_chart_theme(fig)
        st.plotly_chart(fig, width="stretch")
    with second:
        st.subheader("Pareto de faturamento")
        fig = px.line(frame, x="Produto", y="Pareto %", markers=True, color_discrete_sequence=CHART_COLORS)
        fig.update_layout(height=420, yaxis_title="Acumulado (%)", margin=dict(l=0, r=0, t=10, b=0))
        apply_chart_theme(fig)
        st.plotly_chart(fig, width="stretch")
    best = frame.sort_values("Margem", ascending=False).iloc[0]
    worst = frame.sort_values("Margem").iloc[0]
    st.caption(f"Maior margem: {best['Produto']} ({best['Margem']:.1%}) · Menor margem: {worst['Produto']} ({worst['Margem']:.1%})")
    st.dataframe(frame, width="stretch", hide_index=True)


def _stock_report(session: Session) -> None:
    rows = session.execute(select(Product, Stock).join(Stock, Stock.product_id == Product.id)).all()
    output = []
    for product, stock in rows:
        consumed = session.scalar(select(func.coalesce(func.sum(StockMovement.quantity), 0)).where(
            StockMovement.product_id == product.id, StockMovement.movement_type.in_(("Saída", "Perda")),
            func.date(StockMovement.created_at) >= date.today() - timedelta(days=30))) or 0
        avg = float(consumed) / 30
        output.append({"Produto": product.name, "Saldo": stock.quantity, "Mínimo": stock.minimum_quantity,
                       "Consumo/dia": round(avg, 2), "Dias de cobertura": round(stock.quantity / avg, 1) if avg else None,
                       "Comprar": max(0, round(stock.minimum_quantity * 2 - stock.quantity, 2))})
    if output:
        st.dataframe(output, width="stretch", hide_index=True)


def _finance_report(session: Session) -> None:
    start, end = _period()
    payables = session.scalars(select(Payable).where(Payable.due_date >= start, Payable.due_date <= end)
                               .order_by(Payable.due_date)).all()
    receivables = session.scalars(select(Receivable).where(Receivable.due_date >= start, Receivable.due_date <= end)
                                  .order_by(Receivable.due_date)).all()
    pending = sum(item.amount for item in payables if item.status in ("Aberto", "Vencido"))
    overdue = sum(item.amount for item in payables if item.status == "Vencido")
    incoming = sum(item.amount for item in receivables if item.status == "Aberto")
    cols = st.columns(3)
    with cols[0]: metric_card("Contas em aberto", currency(pending), f"{len([item for item in payables if item.status in ('Aberto', 'Vencido')])} no período")
    with cols[1]: metric_card("Vencidas", currency(overdue), "Requerem acompanhamento")
    with cols[2]: metric_card("Recebíveis previstos", currency(incoming), f"{len([item for item in receivables if item.status == 'Aberto'])} no período")
    fixed_categories = {"Aluguel", "Água", "Energia", "Internet", "Salários", "Contabilidade"}
    fixed = [item for item in payables if item.category in fixed_categories]
    variable = [item for item in payables if item.category not in fixed_categories]
    fixed_column, variable_column = st.columns(2)
    with fixed_column:
        st.subheader("Despesas fixas")
        st.dataframe([{"Vencimento": date_only(item.due_date), "Descrição": item.description,
                       "Valor": currency(item.amount), "Status": item.status} for item in fixed],
                     width="stretch", hide_index=True)
    with variable_column:
        st.subheader("Despesas variáveis")
        st.dataframe([{"Vencimento": date_only(item.due_date), "Descrição": item.description,
                       "Valor": currency(item.amount), "Status": item.status} for item in variable],
                     width="stretch", hide_index=True)


def _cash_report(session: Session) -> None:
    start, end = _period()
    sessions = session.scalars(select(CashSession).where(
        func.date(CashSession.opened_at) >= start, func.date(CashSession.opened_at) <= end
    ).order_by(CashSession.opened_at.desc())).all()
    movements = session.scalars(select(CashMovement).where(
        func.date(CashMovement.created_at) >= start, func.date(CashMovement.created_at) <= end
    ).order_by(CashMovement.created_at.desc())).all()
    entries = sum(item.amount for item in movements if item.movement_type == "Entrada")
    exits = sum(item.amount for item in movements if item.movement_type != "Entrada")
    cols = st.columns(3)
    with cols[0]: metric_card("Turnos", str(len(sessions)), "No período selecionado")
    with cols[1]: metric_card("Entradas", currency(entries), f"{sum(item.movement_type == 'Entrada' for item in movements)} lançamentos")
    with cols[2]: metric_card("Saídas", currency(exits), f"{sum(item.movement_type != 'Entrada' for item in movements)} lançamentos")
    st.subheader("Movimentações de caixa")
    st.dataframe([{"Data e hora": date_time(item.created_at), "Tipo": item.movement_type,
                   "Forma": item.method, "Valor": currency(item.amount), "Descrição": item.description}
                  for item in movements], width="stretch", hide_index=True)
    if sessions:
        st.subheader("Turnos")
        st.dataframe([{"Operador": item.operator, "Abertura": date_time(item.opened_at),
                       "Fechamento": date_time(item.closed_at),
                       "Saldo final": currency(item.closing_balance) if item.closing_balance is not None else "Aberto"}
                      for item in sessions], width="stretch", hide_index=True)


def _dre_report(session: Session) -> None:
    start, end = _period()
    orders = _sales(session, start, end)
    order_ids = [order.id for order in orders]
    items = session.scalars(select(OrderItem).where(OrderItem.order_id.in_(order_ids))).all() if order_ids else []
    gross = sum(order.total for order in orders)
    costs = sum(item.quantity * session.get(Product, item.product_id).cost_price for item in items)
    expenses = session.scalars(select(Payable).where(Payable.status == "Pago", Payable.due_date >= start, Payable.due_date <= end)).all()
    expense_total = sum(item.amount for item in expenses)
    lines = [("Receita bruta", gross), ("(-) Descontos", 0), ("Receita líquida", gross),
             ("(-) Custos dos produtos", -costs), ("Lucro bruto", gross - costs),
             ("(-) Despesas", -expense_total), ("Lucro operacional", gross - costs - expense_total),
             ("(-) Impostos", 0), ("Lucro líquido", gross - costs - expense_total)]
    st.dataframe([{"Demonstrativo": label, "Valor": currency(value),
                   "% Receita líquida": f"{value / gross:.1%}" if gross else "-"} for label, value in lines], width="stretch", hide_index=True)
    if gross:
        vertical = pd.DataFrame([{"Linha": label, "Percentual": value / gross * 100} for label, value in lines if label not in ("Receita bruta", "Receita líquida")])
        fig = px.bar(vertical, x="Linha", y="Percentual", color="Percentual", color_continuous_scale=CHART_SCALE)
        fig.update_layout(height=340, margin=dict(l=0, r=0, t=10, b=0))
        apply_chart_theme(fig)
        st.plotly_chart(fig, width="stretch")
    st.caption("Descontos e impostos estão zerados até que sejam parametrizados. DRE gerencial estimada com custos e despesas cadastrados.")


def _cashflow_report(session: Session) -> None:
    days = persistent_select_slider("Projeção", [7, 15, 30, 60], key="finance.projection_days",
                                    default=30, format_func=lambda value: f"{value} dias")
    frame = pd.DataFrame(list(projected_cash(session, days)))
    if not frame.empty:
        st.metric("Saldo ao final", currency(float(frame.iloc[-1]["Saldo projetado"])))
        frame["Data"] = frame["Data"].map(lambda value: value.strftime("%d/%m"))
        fig = px.area(frame, x="Data", y="Saldo projetado", color_discrete_sequence=CHART_COLORS)
        fig.update_layout(height=380, xaxis={"type": "category"})
        apply_chart_theme(fig)
        st.plotly_chart(fig, width="stretch")


def _peak_report(session: Session) -> None:
    start, end = _period()
    orders = _sales(session, start, end)
    if not orders:
        st.info("Sem dados para identificar horários de pico.")
        return
    hours = pd.DataFrame([{"Hora": order.created_at.hour, "Pedidos": 1} for order in orders])
    summary = hours.groupby("Hora", as_index=False)["Pedidos"].sum()
    busiest = summary.loc[summary["Pedidos"].idxmax()]
    quietest = summary.loc[summary["Pedidos"].idxmin()]
    st.caption(f"Maior movimento: {int(busiest['Hora']):02d}h · Menor movimento (entre horários com vendas): {int(quietest['Hora']):02d}h")
    weekday_names = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sab", "Dom"]
    heatmap_data = pd.DataFrame([{"Hora": order.created_at.hour, "Dia": weekday_names[order.created_at.weekday()]}
                                 for order in orders])
    fig = px.density_heatmap(heatmap_data, x="Hora", y="Dia", nbinsx=24,
                             category_orders={"Dia": weekday_names}, color_continuous_scale=CHART_SCALE)
    fig.update_layout(height=390, xaxis={"tickmode": "array", "tickvals": list(range(24)),
                                         "ticktext": [f"{hour:02d}:00" for hour in range(24)]},
                      coloraxis_colorbar_title="Pedidos")
    apply_chart_theme(fig)
    st.plotly_chart(fig, width="stretch")


