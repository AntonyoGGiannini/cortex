"""Componentes e estilo compartilhados (design system advisor-ui).

Princípio: instrumento de trabalho, não página de marketing. Densidade,
hierarquia clara, leitura rápida e consistência entre as telas.
"""

from __future__ import annotations

import streamlit as st

# --------------------------------------------------------------------------- tokens
# Paleta semântica restrita — espelha references do advisor-ui.
BG_BASE = "#F7F8FA"
BG_SURFACE = "#FFFFFF"
SIDEBAR = "#1A1F2E"
TEXT_PRIMARY = "#0F1117"
TEXT_SECONDARY = "#5A6270"
TEXT_MUTED = "#9BA3AF"
POSITIVE = "#16A34A"
NEGATIVE = "#DC2626"
WARNING = "#D97706"
INFO = "#2563EB"
ACCENT = "#0057B8"
ACCENT_LIGHT = "#EFF6FF"
BORDER = "#E5E7EB"
BORDER_STRONG = "#CBD5E1"


def inject_css() -> None:
    st.markdown(
        """
        <style>
        /* ---------- tipografia base (escala de 4 tamanhos) ---------- */
        html, body, [class*="css"] {
            font-family: 'DM Sans', 'IBM Plex Sans', system-ui, sans-serif;
            font-size: 13px;
        }
        [data-testid="stMetricValue"], [data-testid="stDataFrame"] td,
        .stDataFrame td {
            font-variant-numeric: tabular-nums; font-feature-settings: "tnum";
        }

        /* ---------- KPIs ---------- */
        [data-testid="stMetric"] {
            background: #FFFFFF; border: 1px solid #E5E7EB;
            border-radius: 8px; padding: 12px 16px;
        }
        [data-testid="stMetricLabel"] {
            font-size: 11px; color: #5A6270; font-weight: 600;
            text-transform: uppercase; letter-spacing: .5px;
        }
        [data-testid="stMetricValue"] {
            font-size: 22px; font-weight: 700; color: #0F1117;
        }

        /* ---------- sidebar escura ---------- */
        [data-testid="stSidebar"] { background-color: #1A1F2E; }
        [data-testid="stSidebar"] * { color: #E8EAF0 !important; }
        [data-testid="stSidebar"] .stSelectbox > div > div,
        [data-testid="stSidebar"] .stTextInput input {
            background: #252C3F; border-color: #374151;
        }
        .filter-head {
            font-size: 12px; font-weight: 700; letter-spacing: .4px;
            text-transform: uppercase; color: #E8EAF0;
            margin: 4px 0 8px;
        }
        .filter-head .count { color: #7FB0F0; font-weight: 600; }

        /* ---------- tabelas ---------- */
        [data-testid="stDataFrame"] thead th {
            background: #F1F5F9; font-size: 11px; font-weight: 600;
            text-transform: uppercase; letter-spacing: .4px; color: #5A6270;
            border-bottom: 2px solid #CBD5E1;
        }
        [data-testid="stDataFrame"] tbody tr:hover td { background: #EFF6FF; }

        .main .block-container { padding-top: 1.25rem; max-width: 1200px; }

        /* ---------- status bar ---------- */
        .status-bar {
            font-size: 11px; color: #9BA3AF; border-top: 1px solid #E5E7EB;
            padding: 6px 0; margin-top: 16px;
        }

        /* ---------- botões ---------- */
        .stButton > button {
            border-radius: 8px; font-size: 12.5px; font-weight: 600;
            padding: 4px 12px; border: 1px solid #D9DEE6;
        }
        .stButton > button:hover { border-color: #0057B8; color: #0057B8; }
        .stButton > button[kind="primary"] { border: none; }

        /* ---------- linhas como cartões ---------- */
        div[data-testid="stVerticalBlockBorderWrapper"] {
            border-radius: 10px; transition: border-color .12s, box-shadow .12s;
        }
        div[data-testid="stVerticalBlockBorderWrapper"]:hover {
            border-color: #BBD0EC; box-shadow: 0 1px 4px rgba(15,17,23,.05);
        }
        /* destaque para linhas que exigem ação: marcador invisível .mk-action
           dentro do cartão ativa a borda esquerda (CSS :has). */
        div[data-testid="stVerticalBlockBorderWrapper"]:has(.mk-action) {
            border-left: 3px solid #D97706;
        }
        .mk-action { display: none; }

        /* ---------- microtipos de lista ---------- */
        .col-head {
            font-size: 11px; color: #8A93A2; font-weight: 700;
            text-transform: uppercase; letter-spacing: .4px;
        }
        .row-name { font-size: 14px; font-weight: 600; color: #0F1117; }
        .row-meta { font-size: 12px; color: #8A93A2; }

        /* ---------- pílula de status (conexões) ---------- */
        .pill {
            display: inline-flex; align-items: center; gap: 6px;
            font-size: 12px; font-weight: 600; padding: 4px 10px;
            border-radius: 999px; border: 1px solid #E5E7EB; background: #FFFFFF;
        }
        .pill .dot { width: 8px; height: 8px; border-radius: 50%; }
        .pill-label { font-size: 11px; color: #8A93A2; font-weight: 600;
            text-transform: uppercase; letter-spacing: .4px; display: block;
            margin-bottom: 4px; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def badge(text: str, kind: str = "neutral") -> str:
    """Span estilizado para status (HTML). kind: ok | new | info | neutral | warn."""
    palette = {
        "ok": ("#DCFCE7", "#166534"),
        "new": ("#FEF3C7", "#92400E"),
        "info": ("#DBEAFE", "#1E40AF"),
        "warn": ("#FEE2E2", "#991B1B"),
        "neutral": ("#F1F5F9", "#475569"),
    }
    bg, fg = palette.get(kind, palette["neutral"])
    return (
        f"<span style='background:{bg};color:{fg};padding:2px 9px;border-radius:999px;"
        f"font-size:11px;font-weight:700;white-space:nowrap'>{text}</span>"
    )


def page_header(title: str, caption: str = "", last_updated: str = "") -> None:
    if last_updated:
        c1, c2 = st.columns([4, 1])
        c1.markdown(f"### {title}")
        if caption:
            c1.caption(caption)
        c2.markdown(
            f"<div style='text-align:right;color:#9BA3AF;font-size:11px;"
            f"padding-top:14px'>🕐 {last_updated}</div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(f"### {title}")
        if caption:
            st.caption(caption)
    st.divider()


def status_bar(text: str) -> None:
    st.markdown(f'<div class="status-bar">{text}</div>', unsafe_allow_html=True)


def status_pill(label: str, ok: bool, ok_text: str, off_text: str) -> str:
    """Indicador de conexão: rótulo + bolinha colorida + texto. Retorna HTML."""
    color = POSITIVE if ok else NEGATIVE
    txt = ok_text if ok else off_text
    return (
        f"<span class='pill-label'>{label}</span>"
        f"<span class='pill'><span class='dot' style='background:{color}'></span>{txt}</span>"
    )


def filter_header(active: int) -> None:
    """Cabeçalho 'Filtros' com contador de filtros ativos (sidebar)."""
    suffix = (
        f" <span class='count'>({active} ativo{'s' if active != 1 else ''})</span>"
        if active
        else ""
    )
    st.markdown(f"<div class='filter-head'>Filtros{suffix}</div>", unsafe_allow_html=True)


def empty_state(message: str, suggestion: str = "", icon: str = "📭") -> None:
    sug = (
        f"<div style='font-size:12px;margin-top:4px;color:#9BA3AF'>{suggestion}</div>"
        if suggestion
        else ""
    )
    st.markdown(
        f"<div style='text-align:center;padding:40px 24px;color:#9BA3AF'>"
        f"<div style='font-size:30px;margin-bottom:8px'>{icon}</div>"
        f"<div style='font-size:14px;font-weight:600;color:#5A6270'>{message}</div>"
        f"{sug}</div>",
        unsafe_allow_html=True,
    )


def fmt_duration(seconds: int | None) -> str:
    if not seconds:
        return "—"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h}h{m:02d}" if h else f"{m}min"
