import streamlit as st
from sqlalchemy import select

from components.layout import configure_page, top_navigation
from components.qr_code import render_qr
from config import (
    APP_NAME, MODULO_DRE, MODULO_FINANCEIRO, MODULO_INTELIGENCIA,
    MODULO_USUARIOS, MODO_DEMONSTRACAO, MODO_HOMOLOGACAO,
)
from database.connection import get_session, init_database
from models.entities import Role, User
from pages import cash, dashboard, finance, intelligence, inventory, kitchen, orders, reports, settings, users
from services.auth import authenticate, can_access, create_user, seed_access_control
from utils.session_state import RESET_SESSION_ON_RERUN, initialize_app_state, persistent_text_input


MODULES = {
    "Pedidos": (orders.render, "orders", "🛒", "Registre pedidos, clientes e observações."),
    "Cozinha": (kitchen.render, "kitchen:view", "👨‍🍳", "Acompanhe preparo e andamento em tempo real."),
    "Estoque": (inventory.render, "inventory", "📦", "Produtos, insumos e fichas técnicas."),
    "Caixa": (cash.render, "cash", "💰", "Abertura, movimentos e fechamento do turno."),
    "Relatórios": (reports.render, "reports", "📊", "Vendas, produtos, DRE e fluxo de caixa."),
    "Central de Inteligência": (intelligence.render, "intelligence", "🧠", "Insights automáticos sobre a operação."),
    "Configurações": (settings.render, "settings", "⚙️", "Ambiente, módulos e preferências."),
}


def _login(session):
    st.title(f"Acesso ao {APP_NAME}")
    users_count = session.scalar(select(User.id).limit(1))
    if not users_count:
        st.subheader("Configuração inicial")
        st.caption("Crie a conta de administrador para iniciar o ambiente de produção.")
        username = persistent_text_input("Usuário", key="auth.first_admin.username")
        full_name = persistent_text_input("Nome completo", key="auth.first_admin.full_name")
        password = st.text_input("Senha", type="password")
        confirmation = st.text_input("Confirmar senha", type="password")
        if st.button("Criar administrador", type="primary", key="auth.first_admin.submit"):
            if not username or not full_name or len(password) < 8:
                st.error("Preencha usuário e nome; a senha precisa ter ao menos 8 caracteres.")
            elif password != confirmation:
                st.error("As senhas não conferem.")
            else:
                try:
                    create_user(session, username, full_name, password, "ADMINISTRADOR")
                    st.success("Administrador criado. Faça login para continuar.")
                    st.rerun()
                except Exception as error:
                    session.rollback()
                    st.error(f"Não foi possível criar a conta: {error}")
        return False
    username = persistent_text_input("Usuário", key="auth.username")
    password = st.text_input("Senha", type="password")
    if st.button("Entrar", type="primary", width="stretch", key="auth.login.submit"):
        user = authenticate(session, username, password)
        if user:
            st.session_state.user_id = user.id
            st.rerun()
        st.error("Usuário ou senha inválidos, ou usuário bloqueado.")
    return False


def _navigate(destination: str) -> None:
    st.session_state.active_page = destination
    if destination == "Início":
        st.query_params.clear()
    else:
        st.query_params["pagina"] = destination
    st.rerun()


def _logout() -> None:
    st.session_state.pop("user_id", None)
    st.session_state[RESET_SESSION_ON_RERUN] = True
    st.query_params.clear()
    st.rerun()


def main() -> None:
    configure_page()
    initialize_app_state()
    init_database()
    session = get_session()
    try:
        if MODO_DEMONSTRACAO:
            seed_access_control(session)
            st.warning("AMBIENTE DE DEMONSTRAÇÃO · Os dados são isolados em banco separado.", icon="🧪")
        current_user = None
        if not MODO_HOMOLOGACAO:
            user_id = st.session_state.get("user_id")
            current_user = session.get(User, user_id) if user_id else None
            if current_user is None or not current_user.active:
                st.session_state.pop("user_id", None)
                _login(session)
                return
        if MODO_HOMOLOGACAO:
            st.session_state.current_role = "ADMINISTRADOR"
            st.session_state.acting_user = "SISTEMA_HOMOLOGACAO"
        else:
            role_name = session.get(Role, current_user.role_id).name
            st.session_state.current_role = role_name
            st.session_state.acting_user = current_user.full_name
        enabled_modules = dict(MODULES)
        if not MODULO_INTELIGENCIA:
            enabled_modules.pop("Central de Inteligência", None)
        if MODULO_FINANCEIRO:
            enabled_modules["Financeiro"] = (finance.render, "finance", "🧾", "Contas, compromissos e projeções financeiras.")
        if MODULO_USUARIOS and not MODO_HOMOLOGACAO:
            enabled_modules["Usuários"] = (users.render, "*", "👤", "Usuários, perfis e permissões.")
        if not MODULO_DRE:
            st.session_state.reports_hide_dre = True
        else:
            st.session_state.reports_hide_dre = False
        if not MODULO_INTELIGENCIA:
            st.session_state.reports_hide_intelligence = True
        else:
            st.session_state.reports_hide_intelligence = False
        visible = {}
        for name, target in enabled_modules.items():
            permission = target[1]
            if MODO_HOMOLOGACAO or permission is None:
                visible[name] = target
            elif name == "Pedidos" and (can_access(session, current_user, "orders") or can_access(session, current_user, "orders:create")):
                visible[name] = target
            elif name == "Relatórios" and can_access(session, current_user, "reports"):
                visible[name] = target
            elif name == "Configurações" and current_user and role_name == "ADMINISTRADOR":
                visible[name] = target
            elif can_access(session, current_user, permission):
                visible[name] = target

        if "Relatórios" in visible:
            visible["Visão geral"] = (dashboard.render, "reports", "◷", "Indicadores gerenciais do negócio.")

        operation_items = []
        if "Pedidos" in visible:
            operation_items.append(("Pedidos · novo pedido", "Pedidos"))
        for name in ("Cozinha", "Caixa", "Estoque"):
            if name in visible:
                operation_items.append((name, name))
        management_items = []
        if "Visão geral" in visible:
            management_items.append(("Visão geral", "Visão geral"))
        for name in ("Relatórios", "Financeiro"):
            if name in visible:
                management_items.append((name, name))
        intelligence_items = (
            [("Central de Inteligência", "Central de Inteligência")]
            if "Central de Inteligência" in visible else []
        )
        configuration_items = [
            (name, name) for name in ("Configurações", "Usuários") if name in visible
        ]
        groups = {
            "Operação": operation_items,
            "Gestão": management_items,
            "Inteligência": intelligence_items,
            "Configurações": configuration_items,
        }
        profile_name = "Homologação" if MODO_HOMOLOGACAO else current_user.full_name
        top_navigation(
            groups,
            profile_name,
            _navigate,
            None if MODO_HOMOLOGACAO else _logout,
        )

        if st.session_state.active_page == "Início":
            requested_page = st.query_params.get("pagina")
            if requested_page in visible:
                st.session_state.active_page = requested_page
            elif requested_page:
                st.query_params.clear()
        selected = st.session_state.active_page
        if selected != "Início" and selected not in visible:
            st.session_state.active_page = "Início"
            st.query_params.clear()
            st.rerun()
        if selected == "Início":
            dashboard.render_operational_home(
                session,
                profile_name if MODO_HOMOLOGACAO else current_user.full_name,
                list(visible),
                _navigate,
            )
            return
        render_function, _, _, _ = visible[selected]
        if selected == "Pedidos":
            render_qr()
        render_function(session)
    finally:
        session.close()


if __name__ == "__main__":
    st.navigation([st.Page(main, title=APP_NAME, default=True)], position="hidden").run()
