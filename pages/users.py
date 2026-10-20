from sqlalchemy import select
from sqlalchemy.orm import Session
import streamlit as st

from components.layout import section_heading
from models.entities import Audit, Role, User
from services.auth import create_user, hash_password
from utils.session_state import persistent_selectbox, persistent_text_input


def render(session: Session) -> None:
    section_heading("Usuários", "Administração de acesso e perfis")
    roles = session.scalars(select(Role).order_by(Role.name)).all()
    username = persistent_text_input("Usuário", key="users.new.username")
    full_name = persistent_text_input("Nome completo", key="users.new.full_name")
    password = st.text_input("Senha inicial", type="password", key="users.new.password")
    roles_by_id = {role.id: role for role in roles}
    role_id = persistent_selectbox("Perfil", list(roles_by_id), key="users.new.role",
                                   default=next((role.id for role in roles if role.name == "ATENDENTE"), roles[0].id),
                                   format_func=lambda value: roles_by_id[value].name) if roles else None
    if st.button("Criar usuário", type="primary", key="users.new.submit"):
        try:
            role = roles_by_id[role_id]
            create_user(session, username, full_name, password, role.name,
                        st.session_state.get("acting_user", "SISTEMA_HOMOLOGACAO"))
            st.success("Usuário criado.")
            st.rerun()
        except Exception as error:
            session.rollback()
            st.error(f"Não foi possível criar o usuário: {error}")
    users = session.scalars(select(User).order_by(User.username)).all()
    for user in users:
        with st.container(border=True):
            role_name = session.get(Role, user.role_id).name if user.role_id else "Sem perfil"
            st.write(f"**{user.full_name}** · {user.username} · {role_name} · {'Ativo' if user.active else 'Bloqueado'}")
            first, second = st.columns(2)
            user_role_id = persistent_selectbox("Alterar perfil", list(roles_by_id), key=f"users.{user.id}.role",
                                                default=user.role_id or roles[0].id,
                                                format_func=lambda value: roles_by_id[value].name)
            new_password = second.text_input("Resetar senha", type="password", key=f"password_{user.id}")
            a, b = st.columns(2)
            if a.button("Salvar perfil", key=f"save_role_{user.id}"):
                user.role_id = user_role_id
                session.add(Audit(responsible=st.session_state.get("acting_user", "SISTEMA_HOMOLOGACAO"),
                                  action="Perfil de usuário alterado", details=user.username))
                session.commit()
                st.success("Perfil atualizado.")
                st.rerun()
            if b.button("Bloquear" if user.active else "Ativar", key=f"active_{user.id}"):
                user.active = not user.active
                session.add(Audit(responsible=st.session_state.get("acting_user", "SISTEMA_HOMOLOGACAO"),
                                  action="Status de usuário alterado", details=f"{user.username}: {user.active}"))
                session.commit()
                st.rerun()
            if new_password and st.button("Aplicar reset de senha", key=f"reset_{user.id}"):
                if len(new_password) < 8:
                    st.error("A nova senha precisa ter ao menos 8 caracteres.")
                else:
                    user.password_hash = hash_password(new_password)
                    session.add(Audit(responsible=st.session_state.get("acting_user", "SISTEMA_HOMOLOGACAO"),
                                      action="Senha de usuário redefinida", details=user.username))
                    session.commit()
                    st.success("Senha redefinida.")
                    st.rerun()
