import sqlite3

import streamlit as st
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from components.layout import section_heading
from config import (
    APP_TIMEZONE, BACKUP_DIRECTORY, BACKUP_RETENTION_COUNT, DATABASE_URL,
    DEMO_DATABASE_URL, MODULO_DRE, MODULO_FINANCEIRO, MODULO_INTELIGENCIA,
    MODULO_NFE, MODULO_USUARIOS, MODULO_WHATSAPP, MODO_HOMOLOGACAO,
    MODO_DEMONSTRACAO,
)
from database.connection import demo_engine, engine
from models.entities import Audit, Category, DemoRecord, Order, Product
from services.demo_data import populate_demo_data
from services.database_backup import export_sqlite_backup, latest_automatic_backup
from services.database_health import database_health
from services.demo_environment import (
    delete_demo_data, export_demo_data, restore_demo_backup,
)
from utils.clock import local_now
from utils.formatting import date_time
from utils.session_state import persist_value


def _render_homologation(session) -> None:
    st.subheader("Homologação")
    st.warning(
        "Estas ações atuam exclusivamente no arquivo SQLite isolado de demonstração. "
        "Usuários, perfis, permissões e auditorias não marcadas como demo são preservados. "
        "A limpeza também registra sua própria operação na auditoria."
    )
    st.caption(
        "A limpeza remove somente registros com marca demo=True. "
        "Dados sem essa marca não são apagados."
    )
    has_demo_markers = session.scalar(
        select(DemoRecord.id).where(DemoRecord.demo.is_(True)).limit(1)
    )
    has_untagged_data = any((
        session.scalar(select(Category.id).limit(1)),
        session.scalar(select(Product.id).limit(1)),
        session.scalar(select(Order.id).limit(1)),
    ))
    if has_untagged_data and not has_demo_markers:
        st.warning(
            "Este banco contém registros sem marca demo=True, possivelmente criados "
            "por uma versão anterior. Eles serão preservados; revise e faça backup "
            "antes de tentar gerar um catálogo que possa ter códigos ou categorias repetidos."
        )
    if st.button("Popular Dados de Demonstração", type="primary", key="settings.populate_demo"):
        try:
            result = populate_demo_data(session)
            st.success(
                f"{result['days']} dias gerados: {result['orders']} pedidos, "
                f"{result['items']} itens, {result['cash_sessions']} turnos e "
                f"{result['stock_movements']} movimentações de estoque."
            )
        except (SQLAlchemyError, ValueError) as error:
            session.rollback()
            st.error(f"Não foi possível gerar os dados de demonstração: {error}")

    with st.expander("Apagar Dados de Demonstração"):
        st.warning(
            'Será criado um backup automático antes da exclusão. '
            'Digite "CONFIRMAR" para prosseguir.'
        )
        delete_confirmation = st.text_input(
            'Digite "CONFIRMAR"',
            key="settings.demo_delete_confirmation",
        )
        if st.button(
            "Confirmar exclusão dos dados demo",
            disabled=delete_confirmation != "CONFIRMAR",
            key="settings.demo_delete",
        ):
            try:
                deleted_count, backup_path = delete_demo_data(
                    session,
                    st.session_state.get("acting_user", "SISTEMA_HOMOLOGACAO"),
                    "Dados de demonstração apagados",
                )
                st.success(
                    f"{deleted_count} registros demo apagados. "
                    f"Backup automático: {backup_path}"
                )
                st.session_state.pop("settings.demo_backup_download", None)
            except (SQLAlchemyError, OSError, ValueError, sqlite3.Error) as error:
                st.error(f"Não foi possível apagar os dados demo: {error}")

    with st.expander("Reset Completo do Ambiente"):
        st.warning(
            'O reset remove todos os registros demo marcados, mas preserva usuários, '
            'perfis, permissões, dados sem marcação e auditorias não demo. '
            'A operação será registrada na auditoria. Digite "CONFIRMAR".'
        )
        reset_confirmation = st.text_input(
            'Digite "CONFIRMAR" para reset',
            key="settings.demo_reset_confirmation",
        )
        if st.button(
            "Confirmar reset do ambiente demo",
            disabled=reset_confirmation != "CONFIRMAR",
            key="settings.demo_reset",
        ):
            try:
                deleted_count, backup_path = delete_demo_data(
                    session,
                    st.session_state.get("acting_user", "SISTEMA_HOMOLOGACAO"),
                    "Reset completo do ambiente de demonstração",
                )
                st.success(
                    f"Reset concluído: {deleted_count} registros demo removidos. "
                    f"Backup automático: {backup_path}"
                )
                st.session_state.pop("settings.demo_backup_download", None)
            except (SQLAlchemyError, OSError, ValueError, sqlite3.Error) as error:
                st.error(f"Não foi possível resetar o ambiente demo: {error}")

    st.markdown("#### Exportar Backup")
    if st.button("Preparar Backup para Download", key="settings.demo_export"):
        try:
            st.session_state["settings.demo_backup_download"] = export_demo_data(
                session,
                st.session_state.get("acting_user", "SISTEMA_HOMOLOGACAO"),
            )
            st.session_state["settings.demo_backup_filename"] = (
                f"cafeteria-demo-{local_now():%Y%m%d-%H%M%S}.sqlite3"
            )
        except (SQLAlchemyError, OSError, ValueError, sqlite3.Error) as error:
            st.error(f"Não foi possível exportar o backup: {error}")
    backup_data = st.session_state.get("settings.demo_backup_download")
    if backup_data:
        st.download_button(
            "Baixar Backup",
            data=backup_data,
            file_name=st.session_state["settings.demo_backup_filename"],
            mime="application/vnd.sqlite3",
            key="settings.demo_download",
        )

    st.markdown("#### Importar Backup")
    uploaded_backup = st.file_uploader(
        "Selecione um backup SQLite exportado por este aplicativo",
        type=["sqlite3", "sqlite", "db"],
        max_upload_size=100,
        key="settings.demo_import_file",
    )
    import_confirmation = st.text_input(
        'Digite "CONFIRMAR" para substituir os dados demo pelo backup',
        key="settings.demo_import_confirmation",
    )
    if st.button(
        "Importar Backup",
        disabled=uploaded_backup is None or import_confirmation != "CONFIRMAR",
        key="settings.demo_import",
    ):
        try:
            backup_path = restore_demo_backup(
                session,
                uploaded_backup.getvalue(),
                st.session_state.get("acting_user", "SISTEMA_HOMOLOGACAO"),
            )
            st.success(
                f"Backup importado. Backup automático do estado anterior: {backup_path}"
            )
            st.session_state.pop("settings.demo_backup_download", None)
        except (SQLAlchemyError, OSError, ValueError, sqlite3.Error) as error:
            st.error(f"Não foi possível importar o backup: {error}")


def render(session) -> None:
    section_heading("Configurações", "Parâmetros gerais do ambiente")
    first, second = st.columns(2)
    with first:
        with st.container(border=True):
            st.subheader("Ambiente")
            st.write(f"**Modo de acesso:** {'Homologação' if MODO_HOMOLOGACAO else 'Produção'}")
            st.write(f"**Modo de dados:** {'Demonstração' if MODO_DEMONSTRACAO else 'Real'}")
            active_database = DEMO_DATABASE_URL if MODO_DEMONSTRACAO else DATABASE_URL
            database_label = (
                "SQLite" if active_database.startswith("sqlite")
                else "PostgreSQL" if active_database.startswith("postgresql") else "Banco externo"
            )
            st.write(f"**Banco:** {database_label}")
            st.write(f"**Fuso horário:** {APP_TIMEZONE}")
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
    if not MODO_DEMONSTRACAO:
        st.subheader("Proteção do banco de dados")
        if engine.url.drivername.startswith("sqlite"):
            latest_backup = latest_automatic_backup(BACKUP_DIRECTORY)
            health = database_health(engine, BACKUP_DIRECTORY)
            st.write(f"**Pasta de backups:** `{BACKUP_DIRECTORY}`")
            st.write(f"**Conexão:** {'OK' if health['connected'] else 'Falha'}")
            st.write(f"**Integridade SQLite:** {health.get('integrity') or 'não verificada'}")
            if health.get("backup_age_minutes") is not None:
                st.write(f"**Backup atualizado há:** {health['backup_age_minutes']:.1f} min")
            st.write(
                "**Último backup automático:** "
                f"{latest_backup.name if latest_backup else 'Ainda não criado'}"
            )
            st.caption(
                "O SQLite recebe snapshots automáticos a cada 15 minutos de uso, "
                f"mantendo até {BACKUP_RETENTION_COUNT} cópias. O primeiro backup "
                "é criado após o banco já existir."
            )
            st.warning(
                "A pasta padrão fica neste computador. Ela não substitui uma cópia "
                "fora dele; configure BACKUP_DIRECTORY para armazenamento independente "
                "e teste a restauração periodicamente."
            )
            if st.button(
                "Preparar backup atual para download",
                key="settings.database_backup_export",
            ):
                st.session_state.pop("settings.database_backup_download", None)
                try:
                    backup_data = export_sqlite_backup(engine)
                    session.add(Audit(
                        responsible=st.session_state.get(
                            "acting_user", "SISTEMA_HOMOLOGACAO",
                        ),
                        action="Backup do banco operacional exportado",
                        details="Cópia SQLite atual preparada para download.",
                        created_at=local_now(),
                    ))
                    session.commit()
                    st.session_state["settings.database_backup_download"] = (
                        backup_data
                    )
                    st.session_state["settings.database_backup_filename"] = (
                        f"cafeteria-backup-{local_now():%Y%m%d-%H%M%S}.sqlite3"
                    )
                except (OSError, ValueError, sqlite3.Error, SQLAlchemyError) as error:
                    session.rollback()
                    st.error(f"Não foi possível preparar o backup: {error}")
            backup_data = st.session_state.get("settings.database_backup_download")
            if backup_data:
                st.download_button(
                    "Baixar backup do banco operacional",
                    data=backup_data,
                    file_name=st.session_state["settings.database_backup_filename"],
                    mime="application/vnd.sqlite3",
                    key="settings.database_backup_download_button",
                )
        else:
            health = database_health(engine, BACKUP_DIRECTORY)
            st.write(f"**Conexão:** {'OK' if health['connected'] else 'Falha'}")
            if health.get("error"):
                st.error(f"Erro ao consultar o banco: {health['error']}")
            age = health.get("external_backup_age_hours")
            if age is None:
                st.error(
                    "Nenhum backup externo criptografado foi registrado ainda. "
                    "Configure e execute o backup diário descrito no README."
                )
            else:
                st.write(
                    f"**Último backup externo:** {health['external_backup_at']:%d/%m/%Y %H:%M} "
                    f"(há {age:.1f} h)"
                )
                if age > 26:
                    st.error("O backup externo está atrasado (mais de 26 horas). Verifique a automação.")
            st.caption(
                "Mantenha também os backups nativos do provedor do banco e teste a "
                "restauração periodicamente."
            )
    if MODO_DEMONSTRACAO:
        _render_homologation(session)
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
