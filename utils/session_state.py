import streamlit as st


PERSISTENT_WIDGETS = "_persistent_widget_values"


def initialize_app_state() -> None:
    if PERSISTENT_WIDGETS not in st.session_state:
        st.session_state[PERSISTENT_WIDGETS] = {}
    defaults = {
        "active_page": "Início",
        "report_section": "Vendas",
        "orders_page": 1,
        "orders.page": 1,
        "settings.audit_page": 1,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def persistent_widget(key: str, default, options=None) -> dict:
    durable = st.session_state.setdefault(PERSISTENT_WIDGETS, {})
    if key not in st.session_state:
        st.session_state[key] = durable.get(key, default)
    if options is not None and st.session_state[key] not in options:
        st.session_state[key] = default
        durable.pop(key, None)
    return {"key": key, "on_change": persist_widget, "args": (key,)}


def persistent_text_input(label: str, key: str, default: str = "", **kwargs):
    _prepare_widget(key, default)
    return st.text_input(label, key=key, on_change=persist_widget, args=(key,), **kwargs)


def persistent_number_input(label: str, key: str, default=0, **kwargs):
    _prepare_widget(key, default)
    return st.number_input(label, key=key, on_change=persist_widget, args=(key,), **kwargs)


def persistent_selectbox(label: str, options, key: str, default=None, **kwargs):
    options = list(options)
    if default is None:
        default = options[0] if options else None
    _prepare_widget(key, default, options)
    return st.selectbox(label, options, key=key, on_change=persist_widget, args=(key,), **kwargs)


def persistent_date_input(label: str, key: str, default, **kwargs):
    _prepare_widget(key, default)
    return st.date_input(label, key=key, on_change=persist_widget, args=(key,), **kwargs)


def persistent_select_slider(label: str, options, key: str, default=None, **kwargs):
    options = list(options)
    if default is None:
        default = options[0] if options else None
    _prepare_widget(key, default, options)
    return st.select_slider(label, options=options, key=key, on_change=persist_widget, args=(key,), **kwargs)


def persistent_toggle(label: str, key: str, default: bool = False, **kwargs):
    _prepare_widget(key, default)
    return st.toggle(label, key=key, on_change=persist_widget, args=(key,), **kwargs)


def persistent_checkbox(label: str, key: str, default: bool = False, **kwargs):
    _prepare_widget(key, default)
    return st.checkbox(label, key=key, on_change=persist_widget, args=(key,), **kwargs)


def _prepare_widget(key: str, default, options=None) -> None:
    durable = st.session_state.setdefault(PERSISTENT_WIDGETS, {})
    if key not in st.session_state:
        st.session_state[key] = durable.get(key, default)
    if options is not None and st.session_state[key] not in options:
        st.session_state[key] = default
        durable.pop(key, None)


def persist_widget(key: str) -> None:
    st.session_state.setdefault(PERSISTENT_WIDGETS, {})[key] = st.session_state[key]


def persist_value(key: str, value) -> None:
    st.session_state.setdefault(PERSISTENT_WIDGETS, {})[key] = value
