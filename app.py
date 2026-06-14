import streamlit as st
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed

import plaud_client as pc

st.set_page_config(
    page_title="Gravações",
    page_icon="🎙️",
    layout="wide",
)

st.title("🎙️ Gravações")
st.caption("Reuniões e gravações do Plaud")


def _load_all(limit: int = 30) -> tuple[list[dict], dict[str, list[str]]]:
    recordings = pc.list_recordings(limit)

    transcribed = [r["id"] for r in recordings if r.get("has_transcript")]
    speakers_map: dict[str, list[str]] = {}

    if transcribed:
        def _fetch(fid):
            transcript = pc.get_transcript(fid)
            return fid, pc.extract_speakers(transcript)

        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = {pool.submit(_fetch, fid): fid for fid in transcribed}
            for future in as_completed(futures):
                try:
                    fid, speakers = future.result()
                    speakers_map[fid] = speakers
                except Exception:
                    speakers_map[futures[future]] = []

    return recordings, speakers_map


# Controles
col_btn, col_info = st.columns([1, 6])
with col_btn:
    refresh = st.button("🔄 Buscar novamente", use_container_width=True)

# Carrega dados (primeira vez ou ao clicar no botão)
if refresh or "recordings" not in st.session_state:
    with st.spinner("Buscando gravações e carregando speakers..."):
        try:
            recordings, speakers_map = _load_all()
            st.session_state.recordings = recordings
            st.session_state.speakers_map = speakers_map
        except Exception as e:
            st.error(f"Erro ao buscar gravações: {e}")
            st.stop()

recordings: list[dict] = st.session_state.recordings
speakers_map: dict[str, list[str]] = st.session_state.speakers_map

# Métricas rápidas
total = len(recordings)
com_transcript = sum(1 for r in recordings if r.get("has_transcript"))
total_horas = sum(r.get("duration_min", 0) for r in recordings) / 60

m1, m2, m3 = st.columns(3)
m1.metric("Total de gravações", total)
m2.metric("Com transcrição", com_transcript)
m3.metric("Total gravado", f"{total_horas:.1f} h")

st.divider()

# Monta tabela
rows = []
for r in recordings:
    fid = r["id"]
    speakers = speakers_map.get(fid, [])
    rows.append(
        {
            "Nome": r.get("name") or fid,
            "Data": r.get("created_at", "—"),
            "Duração (min)": round(r.get("duration_min", 0), 1),
            "Speakers": ", ".join(speakers) if speakers else "—",
            "ID": fid,
            "Transcrição": "✅" if r.get("has_transcript") else "—",
        }
    )

df = pd.DataFrame(rows)

# Campo de busca
search = st.text_input("🔍 Filtrar por nome ou speaker", placeholder="Digite para filtrar...")
if search:
    mask = (
        df["Nome"].str.contains(search, case=False, na=False)
        | df["Speakers"].str.contains(search, case=False, na=False)
    )
    df = df[mask]

st.dataframe(
    df,
    use_container_width=True,
    hide_index=True,
    column_config={
        "Nome": st.column_config.TextColumn("Nome", width="large"),
        "Data": st.column_config.TextColumn("Data", width="medium"),
        "Duração (min)": st.column_config.NumberColumn("Duração (min)", format="%.1f"),
        "Speakers": st.column_config.TextColumn("Speakers", width="large"),
        "ID": st.column_config.TextColumn("ID", width="medium"),
        "Transcrição": st.column_config.TextColumn("Transcrição", width="small"),
    },
)

st.caption(f"Exibindo {len(df)} de {total} gravações")
