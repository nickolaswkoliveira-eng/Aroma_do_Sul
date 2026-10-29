from datetime import timedelta
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
import pandas as pd
import plotly.express as px
import streamlit as st

from components.layout import metric_card, section_heading
from components.charts import apply_chart_theme
from models.entities import CashSession, Payable, Receivable
from services.domain import (
    add_payable, add_receivable, audit, cash_balance, mark_payable_paid,
    mark_receivable_received, projected_cash, update_overdue_payables,
)
from utils.clock import local_now, local_today
from utils.formatting import currency, date_only
from utils.session_state import (
    persistent_date_input, persistent_number_input, persistent_select_slider,
    persistent_selectbox, persistent_text_input,
)
from utils.palette import CHART_COLORS


def render(session: Session) -> None:
    update_overdue_payables(session)
    section_heading("Financeiro", "Contas a pagar, receitas previstas e projeções")
    tabs = st.tabs(["Visão geral", "Contas a pagar", "Receitas", "Fluxo projetado"])
    with tabs[0]:
        today = local_today()
        open_payables = session.scalars(select(Payable).where(Payable.status.in_(("Aberto", "Vencido")))).all()
        open_receivables = session.scalars(select(Receivable).where(Receivable.status == "Aberto")).all()
        due_next_week = [row for row in open_payables
                         if today <= row.due_date <= today + timedelta(days=7)]
        cash = session.scalar(select(CashSession).where(CashSession.is_open.is_(True)))
        cols = st.columns(4)
        with cols[0]: metric_card("A pagar", currency(sum(row.amount for row in open_payables)), f"{len(open_payables)} contas em aberto/vencidas")
        with cols[1]: metric_card("A receber", currency(sum(row.amount for row in open_receivables)), f"{len(open_receivables)} receitas previstas")
        with cols[2]: metric_card("Vencidas", currency(sum(row.amount for row in open_payables if row.status == "Vencido")), f"{sum(row.status == 'Vencido' for row in open_payables)} contas em atraso")
        with cols[3]: metric_card("Vence em 7 dias", currency(sum(row.amount for row in due_next_week)), f"{len(due_next_week)} compromissos próximos")
        if cash:
            st.info(f"Caixa do turno aberto: saldo atual de {currency(cash_balance(session, cash))}.")
        if open_payables:
            st.dataframe([{"Descrição": row.description, "Categoria": row.category, "Vencimento": date_only(row.due_date),
                           "Valor": currency(row.amount), "Status": row.status} for row in open_payables], width="stretch", hide_index=True)
    with tabs[1]:
        description_column, category_column = st.columns(2)
        with description_column:
            description = persistent_text_input("Descrição", key="finance.payable.description")
        with category_column:
            category = persistent_selectbox("Categoria", ["Aluguel", "Água", "Energia", "Internet", "Salários", "Contabilidade", "Compras", "Insumos", "Manutenção", "Transporte", "Diversos"],
                                            key="finance.payable.category", default="Diversos")
        amount_column, competence_column, due_column = st.columns(3)
        with amount_column:
            amount = persistent_number_input("Valor", key="finance.payable.amount", default=0.01, min_value=0.01, step=10.0)
        with competence_column:
            competence = persistent_date_input("Competência", key="finance.payable.competence", default=local_today(), format="DD/MM/YYYY")
        with due_column:
            due = persistent_date_input("Vencimento", key="finance.payable.due", default=local_today() + timedelta(days=7), format="DD/MM/YYYY")
        if st.button("Cadastrar conta", type="primary", key="finance.payable.submit"):
            try:
                add_payable(
                    session, description, category, amount, competence, due,
                    st.session_state.get("acting_user", "SISTEMA_HOMOLOGACAO"),
                )
                st.success("Conta cadastrada.")
                st.rerun()
            except (ValueError, SQLAlchemyError) as error:
                st.error(str(error))
        rows = session.scalars(select(Payable).order_by(Payable.due_date.desc())).all()
        for row in rows:
            cols = st.columns([3, 2, 1, 1])
            cols[0].write(f"{row.description} · {row.category}")
            cols[1].write(f"{date_only(row.due_date)} · {currency(row.amount)} · {row.status}")
            if row.status != "Pago" and cols[2].button("Marcar pago", key=f"paid_{row.id}"):
                try:
                    mark_payable_paid(
                        session, row,
                        st.session_state.get("acting_user", "SISTEMA_HOMOLOGACAO"),
                    )
                    st.rerun()
                except (ValueError, SQLAlchemyError) as error:
                    st.error(str(error))
    with tabs[2]:
        description_column, amount_column, due_column = st.columns([2, 1, 1])
        with description_column:
            description = persistent_text_input("Origem da receita", key="finance.receivable.description")
        with amount_column:
            amount = persistent_number_input("Valor previsto", key="finance.receivable.amount", default=0.01,
                                             min_value=0.01, step=10.0)
        with due_column:
            due = persistent_date_input("Data prevista", key="finance.receivable.due",
                                        default=local_today() + timedelta(days=7), format="DD/MM/YYYY")
        if st.button("Cadastrar receita", type="primary", key="finance.receivable.submit"):
            try:
                add_receivable(
                    session, description, amount, due,
                    st.session_state.get("acting_user", "SISTEMA_HOMOLOGACAO"),
                )
                st.success("Receita cadastrada.")
                st.rerun()
            except (ValueError, SQLAlchemyError) as error:
                st.error(str(error))
        rows = session.scalars(select(Receivable).order_by(Receivable.due_date)).all()
        for row in rows:
            cols = st.columns([3, 2, 1])
            cols[0].write(row.description)
            cols[1].write(f"{date_only(row.due_date)} · {currency(row.amount)} · {row.status}")
            if row.status == "Aberto" and cols[2].button("Recebido", key=f"received_{row.id}"):
                try:
                    mark_receivable_received(
                        session, row,
                        st.session_state.get("acting_user", "SISTEMA_HOMOLOGACAO"),
                    )
                    st.rerun()
                except (ValueError, SQLAlchemyError) as error:
                    st.error(str(error))
    with tabs[3]:
        days = persistent_select_slider("Horizonte de projeção", [7, 15, 30, 60], key="finance.projection_days",
                        default=30, format_func=lambda value: f"{value} dias")
        projection = list(projected_cash(session, days))
        if projection:
            frame = pd.DataFrame(projection)
            st.metric("Saldo projetado", currency(float(frame.iloc[-1]["Saldo projetado"])))
            figure = px.area(frame, x="Data", y="Saldo projetado", color_discrete_sequence=CHART_COLORS)
            figure.update_layout(margin=dict(l=0, r=0, t=12, b=0), height=350, xaxis={"type": "category"})
            apply_chart_theme(figure)
            st.plotly_chart(figure, width="stretch")
        st.caption("Projeção considera o saldo do caixa e contas a pagar/receber cadastradas com vencimento no período. Vendas não são incorporadas automaticamente; não substitui conciliação bancária.")
