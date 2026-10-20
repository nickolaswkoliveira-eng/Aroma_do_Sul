from sqlalchemy import select
from sqlalchemy.orm import Session
import streamlit as st

from components.layout import metric_card, section_heading
from models.entities import CashMovement, CashSession
from services.domain import add_cash_movement, cash_balance, close_cash, open_cash
from utils.formatting import currency, date_time
from utils.session_state import persistent_number_input, persistent_selectbox, persistent_text_input


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
        if history:
            st.subheader("Turnos recentes")
            st.dataframe([{"Operador": item.operator, "Abertura": date_time(item.opened_at),
                           "Saldo inicial": currency(item.opening_balance), "Saldo final": currency(item.closing_balance or 0),
                           "Status": "Aberto" if item.is_open else "Fechado"} for item in history], width="stretch", hide_index=True)
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
    if st.button("Fechar caixa", type="secondary"):
        final = close_cash(session, cash)
        st.success(f"Caixa fechado. Saldo apurado: {currency(final)}")
        st.rerun()
