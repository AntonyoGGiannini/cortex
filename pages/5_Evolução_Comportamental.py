"""Tela 5 — Evolução Comportamental: como cada speaker muda ao longo do tempo.

Trajetória individual (o que foi observado em cada reunião, no tempo) + comparação
por janela móvel (últimas N reuniões vs N anteriores), detectando mudança por
dimensão. Tudo reconstruído das observações datadas — sem snapshots.

Leitura honesta: evolução exige densidade; pessoas com poucas reuniões aparecem
como 'dados insuficientes'. O recurso amadurece conforme novas reuniões entram.
"""

import streamlit as st

from lib.auth import require_login

from lib.ui import inject_css, page_header, badge, status_bar, empty_state
from lib import db, evolution

st.set_page_config(page_title="Evolução · Cortex", page_icon="📈", layout="wide")
require_login()
inject_css()
page_header(
    "📈 Evolução Comportamental",
    "Como o comportamento de cada stakeholder muda ao longo do tempo · janela móvel de reuniões",
)

DIM_LABELS = {
    "driver_decisao": "Driver de decisão",
    "estilo_processamento": "Estilo",
    "postura_conflito": "Postura em conflito",
    "peso_decisao": "Peso na decisão",
    "linguagem_gatilho": "Linguagem-gatilho",
    "padrao_objecao": "Padrão de objeção",
    "abertura": "Abertura à sua área",
}
DIM_ORDER = list(DIM_LABELS)
DIR_COLOR = {"positivo": "#16A34A", "negativo": "#DC2626", "neutro": "#5A6270"}
SHIFT_LABEL = {
    "mudou_direcao": ("mudou de direção", "warn"),
    "novo": ("novo traço", "info"),
    "sumiu": ("deixou de aparecer", "neutral"),
    "intensificou": ("intensificou", "ok"),
    "enfraqueceu": ("enfraqueceu", "warn"),
}


def d_br(date_str: str | None) -> str:
    if not date_str or len(date_str) < 10:
        return date_str or "—"
    return f"{date_str[8:10]}/{date_str[5:7]}"


# ----------------------------------------------------------------- dados base
try:
    profiles = db.get_speaker_profiles()
except Exception as e:  # noqa: BLE001
    st.error("Erro ao consultar o Supabase.")
    with st.expander("Detalhes técnicos"):
        st.code(str(e))
    st.stop()

elegiveis = sorted(
    [p for p in profiles if (p.get("n_reunioes") or 0) >= 2],
    key=lambda p: (p.get("n_reunioes") or 0),
    reverse=True,
)
nao_eleg = len(profiles) - len(elegiveis)

if not elegiveis:
    empty_state(
        "Ninguém tem reuniões suficientes para uma trajetória ainda.",
        "A evolução aparece a partir de 2 reuniões por pessoa; processe mais reuniões.",
        icon="📈",
    )
    st.stop()

# ----------------------------------------------------------------- controles
ctop = st.columns([5, 2, 3])
nomes = [f"{p['display_name']} ({p['n_reunioes']} reuniões)" for p in elegiveis]
idx = ctop[0].selectbox("Stakeholder", range(len(nomes)), format_func=lambda i: nomes[i])
n_win = ctop[1].slider("Janela (N reuniões)", 2, 5, 3)
sel = elegiveis[idx]
ctop[2].markdown(
    f"<div style='padding-top:26px;color:#5A6270;font-size:12px'>"
    f"{sel.get('role') or ''} · {sel.get('diretoria') or ''}</div>",
    unsafe_allow_html=True,
)

try:
    obs = db.get_observations_for_speaker(sel["speaker_id"])
except Exception:  # noqa: BLE001
    obs = []

if not obs:
    empty_state("Sem observações para este stakeholder.")
    st.stop()

timeline = evolution.speaker_timeline(obs)
cmp = evolution.window_compare(obs, n=n_win)

# ----------------------------------------------------------------- o que mudou
st.markdown("#### O que mudou")
if cmp["insufficient"]:
    st.info(
        f"Dados insuficientes para comparar janelas ({cmp['total_reunioes']} reunião(ões)). "
        "É preciso pelo menos 2 para uma comparação mínima."
    )
else:
    rb, rr = cmp.get("base"), cmp.get("recent")
    st.caption(
        f"Comparando as últimas {cmp['n']} reuniões "
        f"({d_br(rr['de'])}–{d_br(rr['ate'])}) com as {rb['n']} anteriores "
        f"({d_br(rb['de'])}–{d_br(rb['ate'])})."
        if rb else f"Janela de {cmp['n']} reuniões."
    )
    if not cmp["changed"]:
        st.success("Comportamento estável entre as duas janelas — sem mudanças relevantes.")
    else:
        for dim in cmp["changed"]:
            info = cmp["dims"][dim]
            lbl, kind = SHIFT_LABEL.get(info["shift"], (info["shift"], "neutral"))
            b, r = info.get("base"), info.get("recent")

            def _fmt(side):
                if not side:
                    return "<span style='color:#9BA3AF'>—</span>"
                c = DIR_COLOR.get(side["direction"], "#5A6270")
                return (
                    f"<span style='color:{c};font-weight:700'>{side['direction']}</span> "
                    f"<span style='color:#9BA3AF'>({side['conf']} · {side['support']}r)</span>"
                )

            with st.container(border=True):
                cc = st.columns([3, 5])
                cc[0].markdown(
                    f"**{DIM_LABELS.get(dim, dim)}** {badge(lbl, kind)}",
                    unsafe_allow_html=True,
                )
                cc[1].markdown(
                    f"<div style='font-size:12.5px;padding-top:2px'>"
                    f"{_fmt(b)} &nbsp;→&nbsp; {_fmt(r)}"
                    f"<br><span style='color:#5A6270'>{(r or b or {}).get('trait','')}</span></div>",
                    unsafe_allow_html=True,
                )

st.write("")

# ----------------------------------------------------------------- trajetória
st.markdown("#### Trajetória por dimensão")
st.caption("Cada marcador é uma reunião onde a dimensão apareceu · cor = valência · passe o mouse para o traço.")

# índice de dimensões presentes na trajetória
present = {}
for node in timeline:
    for dim, v in node["dims"].items():
        present.setdefault(dim, []).append((node["meeting_date"], node["meeting_title"], v))

for dim in DIM_ORDER:
    pts = present.get(dim)
    if not pts:
        continue
    chips = []
    for date, title, v in pts:
        c = DIR_COLOR.get(v["direction"], "#5A6270")
        tip = f"{title} · {v['trait']} · {v['direction']} ({v['conf_obs']})"
        chips.append(
            f"<span title='{tip}' style='display:inline-flex;align-items:center;gap:4px;"
            f"margin:2px 8px 2px 0;font-size:11.5px;color:#5A6270'>"
            f"<span style='width:10px;height:10px;border-radius:50%;background:{c};"
            f"display:inline-block'></span>{d_br(date)}</span>"
        )
    st.markdown(
        f"<div style='margin:6px 0;display:flex;align-items:center;flex-wrap:wrap'>"
        f"<span style='display:inline-block;width:160px;font-size:12px;font-weight:600;"
        f"color:#0F1117'>{DIM_LABELS[dim]}</span>{''.join(chips)}</div>",
        unsafe_allow_html=True,
    )

with st.expander("Detalhe cronológico (reunião a reunião)"):
    for node in reversed(timeline):
        st.markdown(
            f"**{node['meeting_title'] or 'Reunião'}** "
            f"<span class='row-meta'>· {node['meeting_date'] or ''}</span>",
            unsafe_allow_html=True,
        )
        for dim in DIM_ORDER:
            v = node["dims"].get(dim)
            if not v:
                continue
            c = DIR_COLOR.get(v["direction"], "#5A6270")
            st.markdown(
                f"<div style='font-size:12px;margin:1px 0 1px 10px'>"
                f"<span style='color:{c};font-weight:700'>{DIM_LABELS[dim]}</span> — "
                f"{v['trait']} <span style='color:#9BA3AF'>({v['conf_obs']})</span></div>",
                unsafe_allow_html=True,
            )

extra = f" · {nao_eleg} pessoa(s) com 1 reunião ficaram de fora (sem trajetória)" if nao_eleg else ""
status_bar(
    "Trajetória reconstruída de observações datadas e imutáveis. "
    "Janela móvel por contagem de reuniões, robusta a cadência irregular." + extra
)
