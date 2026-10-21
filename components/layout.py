import base64
from collections.abc import Callable
from html import escape
from pathlib import Path

import streamlit as st

from config import APP_NAME


LOGO_PATH = Path(__file__).parent / "assets" / "cafe-aroma-do-sul.jpg"


def configure_page() -> None:
    st.set_page_config(page_title=APP_NAME, page_icon="☕", layout="wide")
    st.markdown("""
    <style>
    :root {
      --ink: #30251D;
      --muted: #5F5146;
      --beige: #E8DCCB;
      --line: #E5D9CA;
      --accent: #76583F;
      --green: #426B50;
      --surface: #FFFFFF;
      --canvas: #F7F4EF;
      --espresso: #4A3527;
    }
    html, body, [data-testid="stAppViewContainer"] { font-family: Inter, "Segoe UI", Arial, sans-serif; }
    .block-container { width: min(100%, 1440px); padding: 1rem clamp(1rem, 3vw, 2.5rem) 2.5rem; }
    [data-testid="stSidebar"] { display: none; }
    header[data-testid="stHeader"] { display: none !important; }
    [data-testid="stAppViewContainer"] { background: var(--canvas); color: var(--ink); }
    [data-testid="stMainBlockContainer"] { padding-top: 1rem; }
    div[class*="st-key-top_navigation"] { border-bottom: 1px solid var(--line); margin-bottom: 2.2rem; padding-bottom: .55rem; }
    div[class*="st-key-top_navigation_mobile"] { display: none; }
    div[class*="st-key-top_navigation"] [data-testid="stPopover"] > button { min-height: 2.7rem; border: 0; background: transparent !important; color: var(--muted) !important; font-weight: 600; }
    div[class*="st-key-top_navigation"] [data-testid="stPopover"] > button:hover,
    div[class*="st-key-top_navigation"] [data-testid="stPopover"] > button[aria-expanded="true"] { color: var(--espresso); background: #F2EBE2; }
    div[class*="st-key-top_navigation"] button { background-color: transparent !important; border-color: transparent !important; color: var(--muted) !important; }
    div[class*="st-key-top_navigation"] button:hover { background-color: #F2EBE2 !important; color: var(--espresso) !important; }
    div[class*="st-key-top_navigation"] .brand-lockup { min-height: 2.8rem; }
    div[class*="st-key-top_navigation"] .brand-lockup img { width: 42px; height: 42px; }
    div[class*="st-key-top_navigation"] [data-testid="stPopoverBody"] { min-width: 220px; border: 1px solid var(--line); border-radius: 10px; box-shadow: 0 12px 30px rgba(48, 37, 29, .12); }
    div[class*="st-key-top_navigation"] [data-testid="stPopoverBody"] div.stButton > button { border: 0; justify-content: flex-start; background: transparent !important; }
    div[class*="st-key-top_navigation"] [data-testid="stPopoverBody"] div.stButton > button:hover { background: #F2EBE2 !important; }
    .home-intro { padding: .5rem 0 1.5rem; }
    .home-eyebrow { color: var(--accent); font-size: .75rem; font-weight: 700; letter-spacing: .1em; text-transform: uppercase; }
    .home-title { margin: .35rem 0 .25rem; color: var(--espresso); font: 650 clamp(1.8rem, 4vw, 2.5rem)/1.15 system-ui, sans-serif; letter-spacing: -.04em; }
    .home-description { color: var(--muted); font-size: 1rem; }
    .home-status { margin-top: 2.2rem; padding-top: 1.2rem; border-top: 1px solid var(--line); }
    .home-status-label { color: var(--muted); font-size: .78rem; }
    .home-status-value { color: var(--ink); font-size: 1rem; font-weight: 650; margin-top: .25rem; }
    [data-testid="stMetric"] { background: transparent; border: 0; padding: .35rem 0; }
    [data-testid="stMetricLabel"], [data-testid="stCaption"], [data-testid="stWidgetLabel"] { color: var(--muted); }
    div.stButton > button { border-radius: 8px; min-height: 2.5rem; border-color: var(--line); background-color: var(--surface) !important; color: var(--ink) !important; transition: border-color .16s ease, background-color .16s ease; }
    div.stButton > button[kind="primary"] { background-color: var(--espresso) !important; border-color: var(--espresso); color: #FFFFFF !important; }
    div.stButton > button:hover { border-color: var(--accent); color: var(--espresso) !important; background: #F2EBE2 !important; }
    div.stButton > button[kind="primary"]:hover { background: var(--accent) !important; color: #FFFFFF !important; }
    [data-testid="stSelectbox"] [data-baseweb="select"] > div { background-color: var(--surface); border-color: var(--line); color: var(--ink); }
    [data-testid="stSelectbox"] [data-baseweb="select"] input { color: var(--ink); }
    div[data-testid="stForm"] { background: var(--surface); border: 1px solid var(--line); border-radius: 10px; padding: 1rem; }
    .eyebrow { color: var(--accent); text-transform: uppercase; font-size: .7rem; letter-spacing: .08em; font-weight: 700; }
    .brand-lockup { display: flex; align-items: center; gap: .8rem; min-height: 64px; color: var(--espresso); font: 650 1.15rem/1.2 system-ui, sans-serif; letter-spacing: -.02em; }
    .brand-lockup img { width: 58px; height: 58px; object-fit: cover; object-position: center; border: 1px solid var(--line); border-radius: 50%; background: var(--espresso); }
    .panel { background: var(--surface); border: 1px solid var(--line); border-radius: 10px; padding: 1rem 1.15rem; height: 100%; }
    .panel-kpi { min-height: 128px; display: flex; flex-direction: column; justify-content: center; }
    .panel-label { color: var(--muted); font-size: .82rem; margin-bottom: .35rem; }
    .panel-value { color: var(--ink); font-size: 1.25rem; font-weight: 650; line-height: 1.15; }
    .panel-value--hero { font-size: 3rem; font-variant-numeric: tabular-nums; line-height: 1.05; overflow-wrap: anywhere; }
    .panel-note { color: var(--muted); font-size: .78rem; margin-top: .4rem; }
    .panel-trend { color: var(--green); font-size: .78rem; font-weight: 700; margin-top: .35rem; }
    .status-pill { color: var(--ink); font-weight: 650; }
    h1, h2, h3 { font-family: system-ui, sans-serif; color: var(--espresso); letter-spacing: -.025em; }
    h1 { margin-top: .1rem; margin-bottom: .2rem; }
    [data-testid="stTabs"] button[role="tab"] { color: var(--muted); }
    [data-testid="stTabs"] button[aria-selected="true"] { color: var(--espresso); border-bottom-color: var(--accent); }
    [data-testid="stDataFrame"] *, [data-testid="stTable"] * { color: var(--ink); }
    a { color: #464FEB; text-decoration: none; }
    a:hover { text-decoration: underline; }
    :focus-visible { outline: 3px solid var(--accent); outline-offset: 2px; }
    div[class*="st-key-module_card_"] { min-height: 176px; background: var(--surface); border: 1px solid var(--line); border-radius: 10px; padding: 1rem; transition: border-color .16s ease, background-color .16s ease; }
    div[class*="st-key-module_card_"]:hover { background: #FCFAF7; border-color: var(--accent); }
    .module-icon { font-size: 1.5rem; line-height: 1; margin-bottom: .7rem; }
    .module-title { color: var(--espresso); font: 600 1.05rem system-ui, sans-serif; margin: 0 0 .35rem; }
    .module-description { color: var(--muted); min-height: 2rem; font-size: .84rem; margin-bottom: .5rem; }
    .module-indicators { display: flex; gap: .4rem; flex-wrap: wrap; color: var(--accent); font-size: .73rem; margin-bottom: .5rem; }
    .module-indicator { border: 1px solid var(--line); border-radius: 5px; padding: .18rem .4rem; }
    .product-card { min-height: 258px; border: 1px solid var(--line); border-radius: 10px; padding: .85rem; background: var(--surface); transition: border-color .16s ease, background-color .16s ease; }
    .product-card:hover { background: #FCFAF7; border-color: var(--accent); }
    .inventory-table-wrap { max-height: 540px; overflow: auto; border: 1px solid var(--line); border-radius: 8px; }
    .inventory-table { border-collapse: separate; border-spacing: 0; width: 100%; color: var(--ink); font-size: .88rem; }
    .inventory-table th { position: sticky; top: 0; background: #F2EBE2; color: var(--espresso); text-align: left; padding: .75rem; border-bottom: 1px solid var(--line); }
    .inventory-table td { padding: .65rem .75rem; border-bottom: 1px solid var(--line); }
    .inventory-table tr:nth-child(even) td { background: #FCFAF7; }
    .inventory-table tbody tr:hover td { background: #F1E8DD; }
    .stock-badge { display: inline-block; border-radius: 999px; padding: .2rem .5rem; font-size: .72rem; font-weight: 700; }
    .stock-critical { color: #8E332A; background: #FCE8E5; }
    .stock-attention { color: #7C5200; background: #FFF3D7; }
    .stock-healthy { color: #315D3B; background: #E8F3EA; }
    .insight-card { background: var(--surface); border: 1px solid var(--line); border-left: 3px solid var(--accent); border-radius: 8px; padding: .9rem 1rem; min-height: 100px; }
    [class*="st-key-order_summary_panel"] { position: sticky; top: 1rem; }
    @media (max-width: 720px) {
      .block-container { padding: .75rem .9rem 2rem; }
      div[class*="st-key-home_actions"] [data-testid="stHorizontalBlock"] { flex-wrap: wrap; gap: .6rem; }
      div[class*="st-key-home_actions"] [data-testid="column"] { flex: 1 1 calc(50% - .3rem) !important; min-width: calc(50% - .3rem) !important; }
      .panel-kpi { min-height: 110px; }
      .panel-value--hero { font-size: 2.1rem; }
      div[class*="st-key-module_card_"] { min-height: 160px; }
      .brand-lockup { font-size: .92rem; }
      .brand-lockup img { width: 38px; height: 38px; }
      div[class*="st-key-top_navigation"] { margin-bottom: 1.4rem; }
      .home-status { margin-top: 1.5rem; }
    }
    @media (max-width: 900px) {
      div[class*="st-key-top_navigation"] { display: none; }
      div[class*="st-key-top_navigation_mobile"] { display: block; border-bottom: 1px solid var(--line); margin-bottom: 1.4rem; padding-bottom: .65rem; }
      div[class*="st-key-home_summary_metrics"] [data-testid="stHorizontalBlock"] { flex-wrap: wrap; }
      div[class*="st-key-home_summary_metrics"] [data-testid="stColumn"] { flex: 1 1 calc(50% - 1rem) !important; }
    }
    </style>
    """, unsafe_allow_html=True)


def brand_lockup() -> None:
    logo_path = LOGO_PATH.with_name("cafe-aroma-do-sul-mark.jpg")
    encoded_logo = base64.b64encode(logo_path.read_bytes()).decode("ascii")
    st.markdown(
        f'<div class="brand-lockup"><img src="data:image/jpeg;base64,{encoded_logo}" '
        f'alt="{escape(APP_NAME)}"><span>{escape(APP_NAME)}</span></div>',
        unsafe_allow_html=True,
    )


def top_navigation(groups: dict[str, list[tuple[str, str]]], user_name: str,
                   on_navigate: Callable[[str], None], on_logout: Callable[[], None] | None = None) -> None:
    st.session_state.mobile_nav_select = "Menu"
    labels = ("Operação", "Gestão", "Inteligência", "Configurações")
    visible_labels = [label for label in labels if groups.get(label)]
    with st.container(key="top_navigation"):
        columns = st.columns([2.8, .8, *([1.15] * len(visible_labels)), 1.35],
                             vertical_alignment="center")
        with columns[0]:
            brand_lockup()
        with columns[1]:
            if st.button("Início", key="nav_home", width="stretch"):
                on_navigate("Início")
        for column, label in zip(columns[2:-1], visible_labels):
            items = groups.get(label, [])
            with column:
                with st.popover(label, use_container_width=True):
                    for item_label, destination in items:
                        if st.button(item_label, key=f"nav_{label}_{destination}_{item_label}", width="stretch"):
                            on_navigate(destination)
        with columns[-1]:
            with st.popover(user_name, use_container_width=True):
                st.caption("Sessão ativa")
                if on_logout and st.button("Sair", key="logout_button", width="stretch"):
                    on_logout()
    destinations = list(dict.fromkeys(
        destination for items in groups.values() for _, destination in items
    ))
    with st.container(key="top_navigation_mobile"):
        brand_column, profile_column = st.columns([3, 1], vertical_alignment="center")
        with brand_column:
            brand_lockup()
        with profile_column:
            with st.popover(user_name, use_container_width=True):
                st.caption("Sessão ativa")
                if on_logout and st.button("Sair", key="mobile_logout_button", width="stretch"):
                    on_logout()
        st.selectbox(
            "Navegar",
            ["Menu", "Início", *destinations],
            key="mobile_nav_select",
            label_visibility="collapsed",
            on_change=_mobile_navigation_changed,
        )


def _mobile_navigation_changed() -> None:
    destination = st.session_state.mobile_nav_select
    if destination == "Início":
        st.session_state.active_page = "Início"
        st.query_params.clear()
    elif destination != "Menu":
        st.session_state.active_page = destination
        st.query_params["pagina"] = destination


def metric_card(label: str, value: str, note: str = "", trend: str = "", prominent: bool = False) -> None:
    value_class = "panel-value panel-value--hero" if prominent else "panel-value"
    trend_markup = f'<div class="panel-trend">{escape(trend)}</div>' if trend else ""
    st.markdown(
        f'<div class="panel panel-kpi"><div class="panel-label">{escape(label)}</div>'
        f'<div class="{value_class}">{escape(value)}</div>{trend_markup}'
        f'<div class="panel-note">{escape(note)}</div></div>',
        unsafe_allow_html=True,
    )


def section_heading(title: str, description: str = "") -> None:
    st.markdown(f'<div class="eyebrow">{escape(APP_NAME)} · Gestão</div>', unsafe_allow_html=True)
    st.title(title)
    if description:
        st.caption(description)


def module_card(icon: str, title: str, description: str, key: str, indicators: list[str] | None = None,
                selected: bool = False, button_label: str = "Entrar →",
                button_key: str | None = None) -> bool:
    with st.container(key=f"module_card_{key}"):
        indicators_markup = "".join(f'<span class="module-indicator">{escape(item)}</span>' for item in indicators or [])
        st.markdown(
            f'<div class="module-icon">{escape(icon)}</div><div class="module-title">{escape(title)}</div>'
            f'<div class="module-description">{escape(description)}</div>'
            f'<div class="module-indicators">{indicators_markup}</div>',
            unsafe_allow_html=True,
        )
        return st.button(button_label, key=button_key or f"open_module_{key}", width="stretch",
                         type="primary" if selected else "secondary")
