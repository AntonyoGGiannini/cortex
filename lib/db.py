"""Camada Supabase. Todas as leituras/escritas das tabelas do Cortex.

Tabelas:
  - fact_recordings        (plaud_id unique)
  - dim_speakers           (speaker_key unique)
  - fact_recording_speakers (ponte recording_id x speaker_id)

Usa a service_role key -> ignora o RLS (app interno).
"""

from __future__ import annotations

import streamlit as st
from supabase import create_client, Client

from lib.config import SUPABASE_URL, SUPABASE_SERVICE_KEY


@st.cache_resource
def get_client() -> Client:
    if not SUPABASE_SERVICE_KEY:
        raise RuntimeError(
            "SUPABASE_SERVICE_KEY não configurada. Adicione no arquivo .env "
            "(use a service_role key do projeto cortex_db)."
        )
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


# ---------------------------------------------------------------- recordings
def get_registered_plaud_ids() -> set[str]:
    """IDs já salvos -> usado para a flag 'já registrado'."""
    res = get_client().table("fact_recordings").select("plaud_id").execute()
    return {r["plaud_id"] for r in res.data}


def get_recording_meta() -> dict[str, dict]:
    """Mapa plaud_id -> {title, meeting_date} salvos (lista reflete o curado)."""
    res = (
        get_client()
        .table("fact_recordings")
        .select("plaud_id,title,meeting_date")
        .execute()
    )
    return {
        r["plaud_id"]: {
            "title": (r.get("title") or ""),
            "meeting_date": r.get("meeting_date"),
        }
        for r in res.data
    }


def get_recording(plaud_id: str) -> dict | None:
    res = (
        get_client()
        .table("fact_recordings")
        .select("*")
        .eq("plaud_id", plaud_id)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def upsert_recording(payload: dict) -> dict:
    """Salva ou atualiza pelo plaud_id."""
    res = (
        get_client()
        .table("fact_recordings")
        .upsert(payload, on_conflict="plaud_id")
        .execute()
    )
    return res.data[0] if res.data else {}


def count_recordings() -> int:
    res = (
        get_client()
        .table("fact_recordings")
        .select("id", count="exact")
        .execute()
    )
    return res.count or 0


# ------------------------------------------------------------------ speakers
def get_speakers() -> list[dict]:
    res = (
        get_client()
        .table("dim_speakers")
        .select("*")
        .order("display_name")
        .execute()
    )
    return res.data


def get_speaker_keys() -> set[str]:
    res = get_client().table("dim_speakers").select("speaker_key").execute()
    return {r["speaker_key"] for r in res.data}


def get_speaker_by_key(speaker_key: str) -> dict | None:
    res = (
        get_client()
        .table("dim_speakers")
        .select("*")
        .eq("speaker_key", speaker_key)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def get_speaker_by_id(speaker_id: str) -> dict | None:
    res = (
        get_client()
        .table("dim_speakers")
        .select("*")
        .eq("id", speaker_id)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def upsert_speaker(payload: dict) -> dict:
    """Salva ou atualiza pelo speaker_key (usado para novos / auto-criados)."""
    res = (
        get_client()
        .table("dim_speakers")
        .upsert(payload, on_conflict="speaker_key")
        .execute()
    )
    return res.data[0] if res.data else {}


def update_speaker(speaker_id: str, payload: dict) -> dict:
    """Atualiza um registro existente pelo id (permite renomear: muda speaker_key)."""
    res = (
        get_client()
        .table("dim_speakers")
        .update(payload)
        .eq("id", speaker_id)
        .execute()
    )
    return res.data[0] if res.data else {}


def count_speakers() -> int:
    res = get_client().table("dim_speakers").select("id", count="exact").execute()
    return res.count or 0


def count_speakers_needing_review() -> int:
    res = (
        get_client()
        .table("dim_speakers")
        .select("id", count="exact")
        .eq("needs_review", True)
        .execute()
    )
    return res.count or 0


# ------------------------------------------------------- ponte reunião x speaker
def get_speaker_ids_for_recording(recording_id: str) -> set[str]:
    res = (
        get_client()
        .table("fact_recording_speakers")
        .select("speaker_id")
        .eq("recording_id", recording_id)
        .execute()
    )
    return {r["speaker_id"] for r in res.data}


# --------------------------------------------------------------- dashboard
def get_recordings_min() -> list[dict]:
    """Reuniões com campos usados no dashboard (sem transcript/payload pesados)."""
    res = (
        get_client()
        .table("fact_recordings")
        .select("id,title,meeting_date,duration_seconds,category,status")
        .execute()
    )
    return res.data


def get_bridge_all() -> list[dict]:
    """Todos os vínculos reunião×speaker (talk_seconds em s, talk_words)."""
    res = (
        get_client()
        .table("fact_recording_speakers")
        .select("recording_id,speaker_id,talk_seconds,talk_words")
        .execute()
    )
    return res.data


def get_cobertura() -> list[dict]:
    """View vw_cobertura_reuniao (qualidade de captura por reunião)."""
    res = (
        get_client()
        .table("vw_cobertura_reuniao")
        .select("*")
        .order("cobertura_pct")
        .execute()
    )
    return res.data


def set_recording_speakers(recording_id: str, speakers: list[dict]) -> None:
    """Sincroniza os participantes de uma reunião (remove e regrava o vínculo).

    speakers: lista de {'speaker_id', 'talk_seconds', 'talk_words'}
    (talk_seconds e talk_words opcionais).
    """
    client = get_client()
    client.table("fact_recording_speakers").delete().eq(
        "recording_id", recording_id
    ).execute()
    if speakers:
        rows = [
            {
                "recording_id": recording_id,
                "speaker_id": s["speaker_id"],
                "talk_seconds": s.get("talk_seconds"),
                "talk_words": s.get("talk_words"),
            }
            for s in speakers
        ]
        client.table("fact_recording_speakers").insert(rows).execute()


# ------------------------------------------------- perfil comportamental
def get_speaker_profiles() -> list[dict]:
    """Perfis comportamentais agregados, com dados do speaker (join manual)."""
    client = get_client()
    profs = client.table("dim_speaker_profile").select("*").execute().data
    if not profs:
        return []
    spk = {s["id"]: s for s in get_speakers()}
    out = []
    for p in profs:
        s = spk.get(p["speaker_id"], {})
        out.append(
            {
                **p,
                "display_name": s.get("display_name", "—"),
                "speaker_type": s.get("speaker_type"),
                "diretoria": s.get("diretoria"),
                "area": s.get("area"),
                "role": s.get("role"),
            }
        )
    out.sort(key=lambda r: (r.get("conf_overall") or 0), reverse=True)
    return out


def get_observations_for_speaker(speaker_id: str) -> list[dict]:
    """Observações por reunião de um speaker, com título/data da reunião."""
    client = get_client()
    obs = (
        client.table("fact_speaker_observations")
        .select("*")
        .eq("speaker_id", speaker_id)
        .execute()
        .data
    )
    if not obs:
        return []
    rec_ids = list({o["recording_id"] for o in obs})
    recs = (
        client.table("fact_recordings")
        .select("id,title,meeting_date")
        .in_("id", rec_ids)
        .execute()
        .data
    )
    rmap = {r["id"]: r for r in recs}
    for o in obs:
        r = rmap.get(o["recording_id"], {})
        o["meeting_title"] = r.get("title")
        o["meeting_date"] = r.get("meeting_date")
    obs.sort(key=lambda o: (o.get("meeting_date") or "", o.get("dimension") or ""))
    return obs


# ------------------------------------------ pipeline incremental de perfil
def get_pending_recordings(limit: int | None = None) -> list[dict]:
    """Reuniões ainda não processadas para perfil (behavior_processed_at null),
    com transcrição utilizável. Ordena da mais antiga para a mais recente."""
    q = (
        get_client()
        .table("fact_recordings")
        .select("id,title,meeting_date,transcript")
        .is_("behavior_processed_at", "null")
        .order("meeting_date")
    )
    if limit:
        q = q.limit(limit)
    rows = q.execute().data
    return [r for r in rows if (r.get("transcript") or "").strip()]


def get_participants_for_recording(recording_id: str) -> list[dict]:
    """Participantes de uma reunião com display_name e talk_seconds (para filtrar
    quem fala pouco). Junta a ponte com dim_speakers."""
    client = get_client()
    bridge = (
        client.table("fact_recording_speakers")
        .select("speaker_id,talk_seconds")
        .eq("recording_id", recording_id)
        .execute()
        .data
    )
    if not bridge:
        return []
    spk = {s["id"]: s for s in get_speakers()}
    out = []
    for b in bridge:
        s = spk.get(b["speaker_id"])
        if not s:
            continue
        name = s["display_name"] or ""
        low = name.lower()
        generico = (
            low.startswith("speaker")
            or "ai chat" in low
            or (name[:1].isdigit() if name else True)
        )
        out.append(
            {
                "speaker_id": s["id"],
                "display_name": name,
                "talk_seconds": b.get("talk_seconds") or 0,
                "needs_review": bool(s.get("needs_review")),
                "generico": generico,
            }
        )
    return out


def insert_observations(rows: list[dict]) -> int:
    """Insere observações em lote. rows: lista de dicts com as colunas da tabela."""
    if not rows:
        return 0
    res = get_client().table("fact_speaker_observations").insert(rows).execute()
    return len(res.data or [])


def mark_recording_processed(recording_id: str) -> None:
    """Marca a reunião como processada para perfil (timestamp agora)."""
    from datetime import datetime, timezone

    get_client().table("fact_recordings").update(
        {"behavior_processed_at": datetime.now(timezone.utc).isoformat()}
    ).eq("id", recording_id).execute()


def recompute_profiles() -> int:
    """Recalcula todos os perfis agregados (RPC). Retorna nº de perfis."""
    res = get_client().rpc("recompute_speaker_profiles").execute()
    return res.data if isinstance(res.data, int) else 0


def count_pending_recordings() -> int:
    """Quantas reuniões aguardam processamento de perfil (contagem leve)."""
    res = (
        get_client()
        .table("fact_recordings")
        .select("id", count="exact")
        .is_("behavior_processed_at", "null")
        .execute()
    )
    return res.count or 0


# ------------------------------------------ v2: feedback de participação (você)
def get_talk_context(recording_id: str, speaker_id: str) -> dict:
    """Contexto de fala de um speaker numa reunião: share e '× cota justa'."""
    rows = (
        get_client()
        .table("fact_recording_speakers")
        .select("speaker_id,talk_words")
        .eq("recording_id", recording_id)
        .execute()
        .data
    )
    tot = sum((r.get("talk_words") or 0) for r in rows)
    n = len({r["speaker_id"] for r in rows})
    mine = sum((r.get("talk_words") or 0) for r in rows if r["speaker_id"] == speaker_id)
    share = (100.0 * mine / tot) if tot else 0.0
    cota = (mine / tot * n) if tot else 0.0
    return {"n_speakers": n, "tot_words": tot, "my_words": mine,
            "share_pct": round(share, 1), "cota": round(cota, 2)}


def get_feedback_pending(speaker_id: str, limit: int | None = None) -> list[dict]:
    """Reuniões em que o speaker participou (com fala), têm transcript e ainda
    NÃO têm feedback. Da mais antiga para a mais recente. Idempotente."""
    client = get_client()
    done = (
        client.table("fact_participation_feedback")
        .select("recording_id")
        .eq("speaker_id", speaker_id)
        .execute()
        .data
    )
    done_ids = {r["recording_id"] for r in done}
    bridge = (
        client.table("fact_recording_speakers")
        .select("recording_id,talk_words")
        .eq("speaker_id", speaker_id)
        .execute()
        .data
    )
    cand = {b["recording_id"] for b in bridge if (b.get("talk_words") or 0) > 0} - done_ids
    if not cand:
        return []
    recs = (
        client.table("fact_recordings")
        .select("id,title,category,meeting_date,transcript")
        .in_("id", list(cand))
        .order("meeting_date")
        .execute()
        .data
    )
    recs = [r for r in recs if (r.get("transcript") or "").strip()]
    return recs[:limit] if limit else recs


def upsert_feedback(row: dict) -> None:
    """Grava (ou regrava) o feedback de uma reunião para um speaker."""
    get_client().table("fact_participation_feedback").upsert(
        row, on_conflict="recording_id,speaker_id"
    ).execute()


def get_participation_feedback(speaker_id: str) -> list[dict]:
    """Todos os feedbacks de participação de um speaker (para a tela)."""
    return (
        get_client()
        .table("fact_participation_feedback")
        .select("*")
        .eq("speaker_id", speaker_id)
        .execute()
        .data
    )


def count_feedback_pending(speaker_id: str) -> int:
    """Quantas reuniões da pessoa-alvo ainda não têm feedback (contagem leve)."""
    return len(get_feedback_pending(speaker_id))


# ============================================================
# MÓDULO PROJETOS / TEMAS
#   dim_projects          : cadastro curado (CRUD manual)
#   fact_project_mentions : 1 linha por (projeto × reunião) COM sinal
#   fact_project_scan     : livro-razão de cobertura (com/sem menção)
# ============================================================

# ----------------------------------------------------------------- CRUD projetos
def get_projects(only_active: bool = False) -> list[dict]:
    q = get_client().table("dim_projects").select("*").order("name")
    if only_active:
        q = q.eq("status", "ativo")
    return q.execute().data


def get_project(project_id: str) -> dict | None:
    res = (
        get_client()
        .table("dim_projects")
        .select("*")
        .eq("id", project_id)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def upsert_project(payload: dict) -> dict:
    """Salva ou atualiza pelo project_key (chave de negócio)."""
    res = (
        get_client()
        .table("dim_projects")
        .upsert(payload, on_conflict="project_key")
        .execute()
    )
    return res.data[0] if res.data else {}


def update_project(project_id: str, payload: dict) -> dict:
    res = (
        get_client()
        .table("dim_projects")
        .update(payload)
        .eq("id", project_id)
        .execute()
    )
    return res.data[0] if res.data else {}


def delete_project(project_id: str) -> None:
    """Remove o projeto (cascata apaga menções e scan)."""
    get_client().table("dim_projects").delete().eq("id", project_id).execute()


def count_projects() -> int:
    res = get_client().table("dim_projects").select("id", count="exact").execute()
    return res.count or 0


# ----------------------------------------------------------------- ledger de scan
def get_unscanned_recordings(project_id: str) -> list[dict]:
    """Reuniões com transcript ainda NÃO avaliadas para este projeto.
    (Pendentes = têm transcript e não estão no fact_project_scan deste projeto.)
    Ordena da mais antiga para a mais recente."""
    client = get_client()
    scanned = (
        client.table("fact_project_scan")
        .select("recording_id")
        .eq("project_id", project_id)
        .execute()
        .data
    )
    done = {r["recording_id"] for r in scanned}
    recs = (
        client.table("fact_recordings")
        .select("id,title,meeting_date,transcript")
        .order("meeting_date")
        .execute()
        .data
    )
    out = [
        r
        for r in recs
        if r["id"] not in done and (r.get("transcript") or "").strip()
    ]
    return out


def count_unscanned_recordings(project_id: str) -> int:
    return len(get_unscanned_recordings(project_id))


def mark_project_scanned(project_id: str, recording_id: str, had_mention: bool) -> None:
    """Registra que o par (projeto × reunião) foi avaliado (com ou sem menção)."""
    get_client().table("fact_project_scan").upsert(
        {
            "project_id": project_id,
            "recording_id": recording_id,
            "had_mention": had_mention,
        },
        on_conflict="project_id,recording_id",
    ).execute()


# ----------------------------------------------------------------- menções
def upsert_project_mention(row: dict) -> None:
    """Grava (ou regrava) a menção de um projeto numa reunião. Idempotente."""
    get_client().table("fact_project_mentions").upsert(
        row, on_conflict="project_id,recording_id"
    ).execute()


def get_project_mentions(project_id: str) -> list[dict]:
    """Timeline de menções de um projeto (via view, já com título/data da reunião).
    Da mais recente para a mais antiga."""
    res = (
        get_client()
        .table("vw_project_timeline")
        .select("*")
        .eq("project_id", project_id)
        .order("meeting_date", desc=True)
        .execute()
    )
    return res.data


def count_project_mentions(project_id: str) -> int:
    res = (
        get_client()
        .table("fact_project_mentions")
        .select("id", count="exact")
        .eq("project_id", project_id)
        .execute()
    )
    return res.count or 0


def update_project_summary(project_id: str, summary: str, open_todos: list) -> None:
    """Grava o resumo vivo consolidado + cache de to-dos abertos."""
    from datetime import datetime, timezone

    get_client().table("dim_projects").update(
        {
            "consolidated_summary": summary,
            "open_todos": open_todos,
            "summary_updated_at": datetime.now(timezone.utc).isoformat(),
        }
    ).eq("id", project_id).execute()


def get_speakers_map() -> dict[str, dict]:
    """Mapa id -> speaker (para resolver nomes nas menções)."""
    return {s["id"]: s for s in get_speakers()}
