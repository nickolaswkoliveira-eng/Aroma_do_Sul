import streamlit as st
from sqlalchemy import func, select

from components.layout import section_heading
from config import (
    DATABASE_URL, MODULO_DRE, MODULO_FINANCEIRO, MODULO_INTELIGENCIA,
    MODULO_NFE, MODULO_USUARIOS, MODULO_WHATSAPP, MODO_HOMOLOGACAO,
)
from models.entities import Audit
from utils.formatting import date_time
from utils.session_state import persist_value


def render(session) -> None:
    section_heading("Configurações", "Parâmetros gerais do ambiente")
    first, second = st.columns(2)
    with first:
        with st.container(border=True):
            st.subheader("Ambiente")
            st.write(f"**Modo:** {'Homologação' if MODO_HOMOLOGACAO else 'Produção'}")
            st.write(f"**Banco:** {'SQLite' if DATABASE_URL.startswith('sqlite') else 'Banco externo'}")
            st.write("**Usuário ativo:**", st.session_state.get("acting_user", "SISTEMA_HOMOLOGACAO"))
    with second:
        with st.container(border=True):
            st.subheader("Módulos")
            flags = {
                "Financeiro": MODULO_FINANCEIRO,
                "DRE": MODULO_DRE,
                "Inteligência": MODULO_INTELIGENCIA,
                "Usuários": MODULO_USUARIOS,
                "NFe": MODULO_NFE,
                "WhatsApp": MODULO_WHATSAPP,
            }
            for label, enabled in flags.items():
                st.write(f"{'Ativo' if enabled else 'Desativado'} · {label}")
    st.info("Os parâmetros de implantação são definidos em config.py e por variáveis de ambiente. Alterações operacionais são registradas no histórico de auditoria.")
    st.subheader("Auditoria recente")
    page_size = 15
    total = session.scalar(select(func.count(Audit.id))) or 0
    page_count = max(1, (total + page_size - 1) // page_size)
    current_page = min(int(st.session_state.get("settings.audit_page", 1)), page_count)
    if current_page != st.session_state.get("settings.audit_page", 1):
        st.session_state["settings.audit_page"] = current_page
        persist_value("settings.audit_page", current_page)
    rows = session.scalars(select(Audit).order_by(Audit.created_at.desc())
                           .offset((current_page - 1) * page_size).limit(page_size)).all()
    if rows:
        st.dataframe([{"Data e hora": date_time(row.created_at), "Responsável": row.responsible,
                       "Ação": row.action, "Detalhes": row.details} for row in rows],
                     width="stretch", hide_index=True)
        previous, page_label, next_button = st.columns([1, 2, 1])
        if previous.button("← Anterior", disabled=current_page <= 1, key="settings.audit.previous"):
            st.session_state["settings.audit_page"] = current_page - 1
            persist_value("settings.audit_page", current_page - 1)
            st.rerun()
        page_label.caption(f"Página {current_page} de {page_count}")
        if next_button.button("Próxima →", disabled=current_page >= page_count, key="settings.audit.next"):
            st.session_state["settings.audit_page"] = current_page + 1
            persist_value("settings.audit_page", current_page + 1)
            st.rerun()
    else:
        st.caption("Nenhuma ação registrada ainda.")
