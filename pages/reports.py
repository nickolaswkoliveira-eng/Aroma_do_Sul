from datetime import date, timedelta
from io import BytesIO
from sqlalchemy import func, select
from sqlalchemy.orm import Session
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from components.layout import metric_card, module_card, section_heading
from components.charts import apply_chart_theme, format_sales_series
from models.entities import (
    CashMovement, CashSession, Comanda, ComandaOrder, Order, OrderItem, Payable,
    Product, Receivable, Stock, StockMovement,
)
from services.domain import cmv_for_period, product_unit_costs
from utils.clock import local_today
from utils.formatting import currency, date_only, date_time
from utils.palette import CHART_COLORS, CHART_SCALE
from utils.session_state import persistent_date_input, persistent_selectbox

REPORTS = ["Vendas", "Estoque", "Financeiro", "DRE", "Produtos", "Horários", "Caixa"]
REPORT_CARDS = {
    "Vendas": ("📊", "Faturamento, ticket médio e pedidos por período."),
    "Estoque": ("📦", "Posição, consumo médio e cobertura de estoque."),
    "Financeiro": ("💰", "Contas a pagar, recebíveis e vencimentos."),
    "DRE": ("📈", "Resultado operacional e análise vertical."),
    "Produtos": ("🍔", "Ranking, margem e participação de vendas."),
    "Horários": ("🕒", "Distribuição de pedidos por dia e hora."),
    "Caixa": ("🧾", "Turnos, entradas e saídas registrados."),
}


def _sales(session: Session, start: date, end: date):
    return session.scalars(select(Order).where(func.date(Order.created_at) >= start,
                                               func.date(Order.created_at) <= end,
                                               Order.status != "Cancelado").order_by(Order.created_at)).all()


def _period_label(target_day: date, end_day: date | None) -> str:
    if end_day is None or end_day == target_day:
        return f"{target_day:%d/%m/%Y}"
    return f"{target_day:%d/%m/%Y} a {end_day:%d/%m/%Y}"


def _daily_closed_comandas(session: Session, target_day: date, end_day: date | None = None) -> list[Comanda]:
    end_day = end_day or target_day
    return session.scalars(
        select(Comanda)
        .where(
            Comanda.status == "Fechada",
            func.date(Comanda.closed_at) >= target_day,
            func.date(Comanda.closed_at) <= end_day,
        )
        .order_by(Comanda.closed_at)
    ).all()


def _daily_sales_dataframe(
    session: Session, target_day: date, end_day: date | None = None
) -> tuple[pd.DataFrame, dict]:
    end_day = end_day or target_day
    is_range = end_day != target_day
    comandas = _daily_closed_comandas(session, target_day, end_day)
    if not comandas:
        return pd.DataFrame(), {"total": 0.0, "count": 0, "ticket": 0.0, "by_method": {}}
    comanda_ids = [item.id for item in comandas]
    movement_rows = session.scalars(
        select(CashMovement)
        .where(
            CashMovement.movement_type == "Entrada",
            func.date(CashMovement.created_at) >= target_day,
            func.date(CashMovement.created_at) <= end_day,
        )
        .order_by(CashMovement.created_at)
    ).all()
    movement_by_comanda = {}
    for movement in movement_rows:
        if not movement.description.startswith("Comanda #"):
            continue
        code = movement.description.split("#", 1)[1].strip()
        if code.isdigit():
            movement_by_comanda[int(code)] = movement
    order_count_rows = session.execute(
        select(ComandaOrder.comanda_id, func.count(ComandaOrder.id))
        .where(ComandaOrder.comanda_id.in_(comanda_ids))
        .group_by(ComandaOrder.comanda_id)
    ).all()
    order_count_by_comanda = {comanda_id: count for comanda_id, count in order_count_rows}
    rows = []
    total = 0.0
    by_method: dict[str, float] = {}
    for comanda in comandas:
        movement = movement_by_comanda.get(comanda.id)
        amount = movement.amount if movement is not None else comanda.total
        method = movement.method if movement is not None else "Não informado"
        total += amount
        by_method[method] = by_method.get(method, 0.0) + amount
        rows.append({
            "Hora": comanda.closed_at.strftime("%d/%m %H:%M" if is_range else "%H:%M") if comanda.closed_at else "-",
            "Comanda": comanda.id,
            "Mesa": f"{comanda.table_number:02d}" if comanda.table_number is not None else "-",
            "Pedidos": int(order_count_by_comanda.get(comanda.id, 0)),
            "Forma de pagamento": method,
            "Valor": float(amount),
        })
    frame = pd.DataFrame(rows)
    summary = {
        "total": float(total),
        "count": len(rows),
        "ticket": float(total / len(rows)) if rows else 0.0,
        "by_method": by_method,
    }
    return frame, summary


def _daily_sales_excel(frame: pd.DataFrame, summary: dict, target_day: date, end_day: date | None = None) -> bytes:
    output = BytesIO()
    methods = summary.get("by_method", {})
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        header = pd.DataFrame([{
            "Data": _period_label(target_day, end_day),
            "Total vendido": summary["total"],
            "Comandas fechadas": summary["count"],
            "Ticket médio": summary["ticket"],
        }])
        header.to_excel(writer, index=False, sheet_name="Resumo")
        if methods:
            method_rows = pd.DataFrame([
                {"Forma de pagamento": method, "Valor": value}
                for method, value in sorted(methods.items())
            ])
            method_rows.to_excel(writer, index=False, sheet_name="Pagamento")
        frame.to_excel(writer, index=False, sheet_name="Vendas")
    output.seek(0)
    return output.getvalue()


def _daily_sales_pdf(frame: pd.DataFrame, summary: dict, target_day: date, end_day: date | None = None) -> bytes:
    try:
        from fpdf import FPDF
        from fpdf.enums import XPos, YPos
    except ImportError as error:
        raise RuntimeError("Biblioteca de PDF indisponível. Instale fpdf2 para exportar.") from error

    pdf = FPDF(unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=12)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "Relatório de vendas", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 8, f"Período: {_period_label(target_day, end_day)}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.cell(0, 8, f"Total vendido: {currency(summary['total'])}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.cell(
        0,
        8,
        f"Comandas fechadas: {summary['count']}  |  Ticket médio: {currency(summary['ticket'])}",
        new_x=XPos.LMARGIN,
        new_y=YPos.NEXT,
    )
    pdf.ln(2)
    methods = summary.get("by_method", {})
    if methods:
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, "Recebimentos por forma de pagamento", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font("Helvetica", "", 11)
        for method, value in sorted(methods.items()):
            pdf.cell(0, 7, f"{method}: {currency(value)}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(2)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(30, 8, "Hora", border=1)
    pdf.cell(25, 8, "Comanda", border=1)
    pdf.cell(20, 8, "Mesa", border=1)
    pdf.cell(20, 8, "Pedidos", border=1)
    pdf.cell(50, 8, "Forma", border=1)
    pdf.cell(40, 8, "Valor", border=1, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "", 10)
    for row in frame.itertuples(index=False):
        pdf.cell(30, 7, str(row[0]), border=1)
        pdf.cell(25, 7, str(row[1]), border=1)
        pdf.cell(20, 7, str(row[2]), border=1)
        pdf.cell(20, 7, str(row[3]), border=1)
        pdf.cell(50, 7, str(row[4])[:25], border=1)
        pdf.cell(40, 7, currency(float(row[5])), border=1, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    return bytes(pdf.output())


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
            key = f"report_{report.lower().replace(' ', '_')}"
            if module_card(icon, report, description, key, selected=selected == report,
                           button_label="Abrir relatório →", button_key=f"report_{report}"):
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


def _period() -> tuple[date, date]:
    preset = persistent_selectbox("Período", ["Dia", "Semana", "Mês", "Ano", "Personalizado"],
                                  key="reports.period", default="Mês")
    today = local_today()
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
    costs = cmv_for_period(session, start, end)["cost"]
    revenue = sum(order.total for order in orders)
    average = revenue / len(orders) if orders else 0
    cols = st.columns(3 if basic else 4)
    with cols[0]: metric_card("Faturamento", currency(revenue), f"{start:%d/%m} a {end:%d/%m/%Y}")
    if not basic:
        with cols[1]: metric_card("Lucro bruto estimado", currency(revenue - costs), "Receita menos custo da ficha técnica quando disponível")
    with cols[1 if basic else 2]: metric_card("Ticket médio", currency(average), "Por pedido registrado")
    with cols[2 if basic else 3]: metric_card("Pedidos", str(len(orders)), "No período")
    period = st.session_state.get("reports.period", "Mês")
    labels, values = format_sales_series(orders, period, start, end)
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

    st.subheader("Consulta diária de vendas")
    consult_mode = st.radio(
        "Tipo de consulta",
        ["Um dia", "Período"],
        horizontal=True,
        key="reports.daily_sales_mode",
    )
    target_day = persistent_date_input(
        "Selecione a data" if consult_mode == "Um dia" else "Data inicial",
        key="reports.daily_sales_date",
        default=local_today(),
        format="DD/MM/YYYY",
    )
    end_day = None
    if consult_mode == "Período":
        end_day = persistent_date_input(
            "Data final",
            key="reports.daily_sales_end_date",
            default=local_today(),
            format="DD/MM/YYYY",
        )
        if end_day < target_day:
            st.error("A data final não pode ser anterior à data inicial.")
            return
    period_text = _period_label(target_day, end_day)
    file_suffix = f"{target_day:%Y-%m-%d}" if end_day is None else f"{target_day:%Y-%m-%d}_a_{end_day:%Y-%m-%d}"
    daily_frame, summary = _daily_sales_dataframe(session, target_day, end_day)
    daily_metrics = st.columns(3)
    with daily_metrics[0]:
        metric_card("Total vendido", currency(summary["total"]), period_text)
    with daily_metrics[1]:
        metric_card("Comandas fechadas", str(summary["count"]), "Recebimentos no caixa")
    with daily_metrics[2]:
        metric_card("Ticket médio", currency(summary["ticket"]), "Total dividido por comandas")
    if daily_frame.empty:
        st.info("Sem vendas registradas para o período selecionado.")
    else:
        by_method = summary.get("by_method", {})
        method_frame = pd.DataFrame(
            [{"Forma": method, "Valor": value} for method, value in sorted(by_method.items())]
        )
        method_chart = px.bar(
            method_frame,
            x="Forma",
            y="Valor",
            text=method_frame["Valor"].apply(currency),
            color="Forma",
            color_discrete_sequence=CHART_SCALE,
        )
        method_chart.update_layout(height=320, showlegend=False)
        method_chart.update_traces(textposition="outside")
        apply_chart_theme(method_chart)
        st.plotly_chart(method_chart, width="stretch", config={"displayModeBar": False})
        st.dataframe(
            [
                {
                    "Hora": row["Hora"],
                    "Comanda": row["Comanda"],
                    "Mesa": row["Mesa"],
                    "Pedidos": row["Pedidos"],
                    "Forma de pagamento": row["Forma de pagamento"],
                    "Valor": currency(float(row["Valor"])),
                }
                for _, row in daily_frame.iterrows()
            ],
            width="stretch",
            hide_index=True,
        )
        export_columns = st.columns(2)
        with export_columns[0]:
            st.download_button(
                "Exportar Excel",
                data=_daily_sales_excel(daily_frame, summary, target_day, end_day),
                file_name=f"vendas_{file_suffix}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="reports.daily_sales_export_excel",
            )
        with export_columns[1]:
            try:
                pdf_data = _daily_sales_pdf(daily_frame, summary, target_day, end_day)
                st.download_button(
                    "Exportar PDF",
                    data=pdf_data,
                    file_name=f"vendas_{file_suffix}.pdf",
                    mime="application/pdf",
                    key="reports.daily_sales_export_pdf",
                )
            except RuntimeError as error:
                st.warning(str(error))
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
    rows = session.execute(select(Product.id, Product.name, func.sum(OrderItem.quantity).label("units"),
                                 func.sum(OrderItem.quantity * OrderItem.unit_price).label("revenue"))
                           .join(OrderItem, OrderItem.product_id == Product.id).join(Order, Order.id == OrderItem.order_id)
                           .where(func.date(Order.created_at) >= start, func.date(Order.created_at) <= end,
                                  Order.status != "Cancelado")
                           .group_by(Product.id).order_by(func.sum(OrderItem.quantity).desc())).all()
    if not rows:
        st.info("Sem itens vendidos no período.")
        return
    unit_costs = product_unit_costs(session, {row.id for row in rows})
    frame = pd.DataFrame([{"Produto": row.name, "Unidades": row.units, "Faturamento": row.revenue,
                           "Margem": (row.revenue - row.units * unit_costs.get(row.id, 0)) / row.revenue if row.revenue else 0}
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
            func.date(StockMovement.created_at) >= local_today() - timedelta(days=30))) or 0
        avg = float(consumed) / 30
        output.append({"Produto": product.name, "Saldo": stock.quantity, "Mínimo": stock.minimum_quantity,
                       "Consumo/dia": round(avg, 2), "Dias de cobertura": round(stock.quantity / avg, 1) if avg else None,
                       "Comprar": max(0, round(stock.minimum_quantity * 2 - stock.quantity, 2))})
    if output:
        frame = pd.DataFrame(output)
        chart_data = frame.dropna(subset=["Dias de cobertura"]).copy()
        if not chart_data.empty:
            st.subheader("Cobertura de estoque (dias)")
            chart_data = chart_data.sort_values("Dias de cobertura", ascending=True).head(12)
            fig = px.bar(
                chart_data,
                x="Dias de cobertura",
                y="Produto",
                orientation="h",
                color="Dias de cobertura",
                color_continuous_scale=CHART_SCALE,
            )
            fig.update_layout(
                height=420,
                margin=dict(l=0, r=0, t=10, b=0),
                yaxis={"categoryorder": "array", "categoryarray": chart_data["Produto"].tolist()},
                coloraxis_colorbar_title="Dias",
            )
            fig.add_vline(
                x=7,
                line_dash="dash",
                line_color="#7A5A3E",
                annotation_text="Meta 7 dias",
                annotation_position="top right",
            )
            apply_chart_theme(fig)
            st.plotly_chart(fig, width="stretch")
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
    gross = sum(order.total for order in orders)
    costs = cmv_for_period(session, start, end)["cost"]
    expenses = session.scalars(select(Payable).where(Payable.status == "Pago", Payable.due_date >= start, Payable.due_date <= end)).all()
    expense_total = sum(item.amount for item in expenses)
    lines = [("Receita bruta", gross), ("(-) Descontos", 0), ("Receita líquida", gross),
             ("(-) Custos dos produtos", -costs), ("Lucro bruto", gross - costs),
             ("(-) Despesas", -expense_total), ("Lucro operacional", gross - costs - expense_total),
             ("(-) Impostos", 0), ("Lucro líquido", gross - costs - expense_total)]
    st.dataframe([{"Demonstrativo": label, "Valor": currency(value),
                   "% Receita líquida": f"{value / gross:.1%}" if gross else "-"} for label, value in lines], width="stretch", hide_index=True)
    waterfall = go.Figure(
        go.Waterfall(
            name="DRE",
            orientation="v",
            measure=["absolute", "relative", "relative", "total"],
            x=["Receita líquida", "Custos", "Despesas", "Lucro operacional"],
            y=[gross, -costs, -expense_total, gross - costs - expense_total],
            connector={"line": {"color": "rgba(48,37,29,0.35)"}},
            increasing={"marker": {"color": CHART_COLORS[0]}},
            decreasing={"marker": {"color": CHART_COLORS[2]}},
            totals={"marker": {"color": CHART_COLORS[1]}},
            text=[
                currency(gross),
                currency(-costs),
                currency(-expense_total),
                currency(gross - costs - expense_total),
            ],
            textposition="outside",
        )
    )
    waterfall.update_layout(height=360, margin=dict(l=0, r=0, t=10, b=0), showlegend=False)
    apply_chart_theme(waterfall)
    st.plotly_chart(waterfall, width="stretch")
    st.caption("Descontos e impostos estão zerados até que sejam parametrizados. DRE gerencial estimada com custos e despesas cadastrados.")


def _peak_report(session: Session) -> None:
    window_label = persistent_selectbox(
        "Janela de análise",
        ["7 dias", "15 dias", "30 dias"],
        key="reports.peak_window",
        default="7 dias",
    )
    window_days = int(window_label.split()[0])
    end = local_today()
    start = end - timedelta(days=window_days - 1)
    orders = _sales(session, start, end)
    if not orders:
        st.info("Sem dados para identificar horários de pico.")
        return
    hours = pd.DataFrame([{"Hora": order.created_at.hour, "Pedidos": 1} for order in orders])
    summary = hours.groupby("Hora", as_index=False)["Pedidos"].sum().sort_values("Hora")
    busiest = summary.loc[summary["Pedidos"].idxmax()]
    quietest = summary.loc[summary["Pedidos"].idxmin()]
    st.markdown(
        f"<div style='color:#4A3527;font-weight:600;'>"
        f"Período: {start:%d/%m/%Y} a {end:%d/%m/%Y} · "
        f"Maior movimento: {int(busiest['Hora']):02d}h · "
        f"Menor movimento (com vendas): {int(quietest['Hora']):02d}h"
        "</div>",
        unsafe_allow_html=True,
    )
    summary["Faixa"] = summary["Hora"].map(lambda hour: f"{int(hour):02d}h")
    summary["Tipo"] = "Demais horários"
    summary.loc[summary["Hora"] == int(busiest["Hora"]), "Tipo"] = "Pico de pedidos"
    summary.loc[summary["Hora"] == int(quietest["Hora"]), "Tipo"] = "Menor movimento"
    bar = px.bar(
        summary,
        x="Pedidos",
        y="Faixa",
        orientation="h",
        color="Tipo",
        color_discrete_map={
            "Pico de pedidos": "#B08968",
            "Menor movimento": "#6D4C41",
            "Demais horários": "#3F6B52",
        },
        category_orders={"Tipo": ["Pico de pedidos", "Menor movimento", "Demais horários"]},
        text="Pedidos",
    )
    bar.update_layout(
        height=360,
        margin=dict(l=0, r=0, t=8, b=0),
        legend_title_text="Legenda",
        font={"color": "#30251D"},
        legend={
            "font": {"color": "#30251D", "size": 14},
            "title": {"font": {"color": "#30251D", "size": 15}},
        },
        xaxis={"title": {"text": "Quantidade de pedidos", "font": {"color": "#30251D"}},
               "tickfont": {"color": "#30251D"}},
        yaxis={"title": {"text": "Faixa", "font": {"color": "#30251D"}},
               "tickfont": {"color": "#30251D"},
               "categoryorder": "array",
               "categoryarray": summary["Faixa"].tolist()},
    )
    bar.update_traces(textposition="outside", cliponaxis=False, texttemplate="%{text}", textfont={"color": "#30251D"})
    apply_chart_theme(bar)
    st.plotly_chart(bar, width="stretch", config={"displayModeBar": False})
