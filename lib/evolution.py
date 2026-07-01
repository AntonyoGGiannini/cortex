"""Análise histórica da evolução comportamental dos speakers.

A partir das observações datadas (fact_speaker_observations + meeting_date),
reconstrói:
  - speaker_timeline: a trajetória — o que foi observado em cada reunião, no tempo.
  - window_compare: comparação por janela móvel — as últimas N reuniões da pessoa
    versus as N anteriores, detectando mudança (shift) por dimensão.

Não depende de snapshots: como as observações são imutáveis e datadas, o histórico
é sempre reconstruível. Funções puras (recebem a lista de observações), fáceis de testar.

Limite honesto: evolução exige densidade. Com poucas reuniões por pessoa o sinal é
fraco — por isso window_compare marca 'insufficient' e cada shift carrega o suporte
(quantas reuniões sustentam) para o leitor calibrar a confiança.
"""

from __future__ import annotations

from collections import defaultdict
from statistics import mean


def _ordered_meetings(observations: list[dict]) -> list[tuple]:
    """Reuniões distintas da pessoa, ordenadas por data (asc).
    Retorna [(meeting_date, recording_id, meeting_title), ...]."""
    seen = {}
    for o in observations:
        rid = o.get("recording_id")
        if rid and rid not in seen:
            seen[rid] = (o.get("meeting_date") or "", rid, o.get("meeting_title") or "")
    return sorted(seen.values(), key=lambda m: (m[0], m[1]))


def speaker_timeline(observations: list[dict]) -> list[dict]:
    """Agrupa observações por reunião, em ordem cronológica.

    Retorna lista de {meeting_date, meeting_title, recording_id, dims}, onde dims é
    {dimension: {trait, direction, conf_obs}} (a obs de maior conf_obs por dimensão
    naquela reunião, se houver mais de uma).
    """
    by_rec: dict[str, dict] = {}
    for o in observations:
        rid = o.get("recording_id")
        if not rid:
            continue
        node = by_rec.setdefault(
            rid,
            {
                "recording_id": rid,
                "meeting_date": o.get("meeting_date"),
                "meeting_title": o.get("meeting_title"),
                "dims": {},
            },
        )
        dim = o.get("dimension")
        conf = float(o.get("conf_obs") or 0)
        cur = node["dims"].get(dim)
        if cur is None or conf > cur["conf_obs"]:
            node["dims"][dim] = {
                "trait": o.get("trait_label"),
                "direction": o.get("direction"),
                "conf_obs": conf,
            }
    return sorted(
        by_rec.values(), key=lambda n: (n.get("meeting_date") or "", n["recording_id"])
    )


def _aggregate_window(observations: list[dict], rec_ids: set[str]) -> dict:
    """Agrega observações restritas a um conjunto de reuniões, por dimensão.
    Retorna {dimension: {conf, direction, support, trait}}."""
    buckets: dict[str, list[dict]] = defaultdict(list)
    for o in observations:
        if o.get("recording_id") in rec_ids:
            buckets[o.get("dimension")].append(o)
    out = {}
    for dim, items in buckets.items():
        confs = [float(i.get("conf_obs") or 0) for i in items]
        # direção majoritária ponderada por conf_obs
        dir_score: dict[str, float] = defaultdict(float)
        for i in items:
            dir_score[i.get("direction") or "neutro"] += float(i.get("conf_obs") or 0)
        direction = max(dir_score, key=dir_score.get)
        # traço mais forte da janela
        strongest = max(items, key=lambda i: float(i.get("conf_obs") or 0))
        out[dim] = {
            "conf": round(mean(confs), 2),
            "direction": direction,
            "support": len({i.get("recording_id") for i in items}),
            "trait": strongest.get("trait_label"),
        }
    return out


def _classify_shift(base: dict | None, recent: dict | None, conf_delta_min: float = 0.15) -> str:
    """Classifica a mudança de uma dimensão entre as duas janelas."""
    if base is None and recent is None:
        return "estavel"
    if base is None:
        return "novo"          # dimensão passou a aparecer
    if recent is None:
        return "sumiu"         # deixou de aparecer
    if base["direction"] != recent["direction"]:
        return "mudou_direcao"
    d = recent["conf"] - base["conf"]
    if d >= conf_delta_min:
        return "intensificou"
    if d <= -conf_delta_min:
        return "enfraqueceu"
    return "estavel"


def window_compare(observations: list[dict], n: int = 3) -> dict:
    """Compara as últimas N reuniões (recente) com as N imediatamente anteriores (base).

    Janela por contagem de reuniões (não calendário): robusto a cadência irregular.
    Retorna {n, insufficient, recent, base, dims:{dimension:{base, recent, shift}}, changed}.
    """
    meetings = _ordered_meetings(observations)
    total = len(meetings)
    if total < 2:
        return {"n": n, "insufficient": True, "total_reunioes": total, "dims": {}, "changed": []}

    k = min(n, total // 2) if total < 2 * n else n
    k = max(k, 1)
    recent_m = meetings[-k:]
    base_m = meetings[-2 * k : -k] if total >= 2 * k else meetings[: total - k]

    recent_ids = {m[1] for m in recent_m}
    base_ids = {m[1] for m in base_m}

    agg_recent = _aggregate_window(observations, recent_ids)
    agg_base = _aggregate_window(observations, base_ids)

    dims = {}
    changed = []
    for dim in sorted(set(agg_recent) | set(agg_base)):
        b = agg_base.get(dim)
        r = agg_recent.get(dim)
        shift = _classify_shift(b, r)
        dims[dim] = {"base": b, "recent": r, "shift": shift}
        if shift not in ("estavel",):
            changed.append(dim)

    def _span(ms):
        return {"de": ms[0][0], "ate": ms[-1][0], "n": len(ms)} if ms else None

    return {
        "n": k,
        "insufficient": False,
        "total_reunioes": total,
        "recent": _span(recent_m),
        "base": _span(base_m),
        "dims": dims,
        "changed": changed,
    }
