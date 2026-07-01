"""Normalização de nomes -> speaker_key (chave de negócio única em dim_speakers)."""

import re
import unicodedata


def normalize_name(name: str | None) -> str:
    """Converte um nome de exibição em uma chave estável.

    "Antônio  Giannini" -> "antonio_giannini"
    "Ana S." -> "ana_s"

    Remove acentos, baixa para minúsculas, troca tudo que não for [a-z0-9]
    por "_" e colapsa repetições. Use para deduplicar speakers pelo nome.
    """
    if not name:
        return ""
    nfkd = unicodedata.normalize("NFKD", str(name))
    ascii_str = "".join(c for c in nfkd if not unicodedata.combining(c))
    ascii_str = ascii_str.lower().strip()
    ascii_str = re.sub(r"[^a-z0-9]+", "_", ascii_str)
    return ascii_str.strip("_")
