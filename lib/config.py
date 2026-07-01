"""Configuração central. Lê do .env (padrão do projeto) via python-dotenv."""

import os
from dotenv import load_dotenv

load_dotenv()


def _secret(key: str, default: str = "") -> str:
    """Lê de variáveis de ambiente (.env local) e de st.secrets (cloud).

    No Streamlit Community Cloud os segredos configurados no painel também
    ficam disponíveis como env var, mas o fallback via st.secrets garante
    funcionamento mesmo fora desse caso. Fora do runtime Streamlit (ex.:
    scripts de backfill) o acesso a st.secrets é ignorado.
    """
    v = os.environ.get(key)
    if v:
        return v
    try:
        import streamlit as st

        if key in st.secrets:
            return str(st.secrets[key])
    except Exception:  # noqa: BLE001 — sem runtime Streamlit / sem secrets.toml
        pass
    return default


# --- Acesso remoto (gate de senha; vazio => sem bloqueio, uso local) ---
APP_PASSWORD = _secret("APP_PASSWORD", "")

# --- Supabase ---
SUPABASE_URL = _secret("SUPABASE_URL", "https://rcjckulvccwrdpbupfws.supabase.co")
# IMPORTANTE: use a service_role key. O app é interno e o RLS está ativo.
SUPABASE_SERVICE_KEY = _secret("SUPABASE_SERVICE_KEY", "")

# --- Plaud ---
PLAUD_TOKEN = _secret("PLAUD_TOKEN", "")

# --- Anthropic (extração de perfil comportamental) ---
ANTHROPIC_API_KEY = _secret("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
# Tamanho máx. de transcrição enviado ao modelo (controle de custo/contexto).
PERFIL_MAX_TRANSCRIPT_CHARS = int(os.environ.get("PERFIL_MAX_CHARS", "45000"))
# Tempo mínimo de fala (segundos) para um participante ser perfilado numa reunião.
PERFIL_MIN_TALK_SECONDS = int(os.environ.get("PERFIL_MIN_TALK_SECONDS", "60"))

# --- Projetos / Temas (extração de menções por reunião) ---
# Tamanho máx. de transcrição enviado ao modelo na extração de menções.
PROJ_MAX_TRANSCRIPT_CHARS = int(os.environ.get("PROJ_MAX_CHARS", "45000"))
# Relevância mínima (0-1) para uma menção ser gravada (descarta tangenciais).
PROJ_MIN_RELEVANCE = float(os.environ.get("PROJ_MIN_RELEVANCE", "0.2"))
# Backfill com filtro híbrido: só manda ao LLM calls que contêm nome/alias.
PROJ_HYBRID_FILTER = os.environ.get("PROJ_HYBRID_FILTER", "1") == "1"

PROJECT_STATUS = ["ativo", "pausado", "concluido", "arquivado"]

# Fuso para derivar a data da reunião a partir do start_time (epoch ms, UTC).
LOCAL_TZ = os.environ.get("CORTEX_TZ", "America/Sao_Paulo")

# Identidade do dono da base (você) — usado no dashboard para separar
# "minha fala" (escuta vs. fala) e excluir do ranking de stakeholders.
ME_SPEAKER_KEY = os.environ.get("CORTEX_ME_KEY", "antonyo_giannini")

# Opções controladas (governança) para o formulário de reunião.
TIPOS_REUNIAO = [
    "1:1",
    "Alinhamento",
    "Apresentação",
    "B2B",
    "Diretoria",
    "Comercial",
    "Itaú",
    "Mensal",
    "Outro",
    "Projeto",
    "Weekly"
]

SPEAKER_TYPES = ["interno", "cliente", "parceiro", "outro"]
RECORDING_STATUS = ["pendente", "revisado", "arquivado"]

# Listas controladas para o cadastro de speakers.
# EDITE conforme a estrutura da sua organização (governança de dados).
DIRETORIAS = [
    "Comercial",
    "Compliance",
    "Financeiro",
    "Jurídico",
    "Produtos",
    "Operações",
    "Tecnologia",
    "RH",
    ""
]

AREAS = [
    "Assessoria",
    "B2B",
    "Backoffice",
    "Customer Service",
    "Dados & BI",
    "Design",
    "Engenharia",
    "FP&A",
    "Infraestrutura",
    "Inteligência Comercial",
    "Investimentos",
    "Itaú",
    "Marketing",
    "Mesa de Operações",
    "Middle B2B",
    "Middle Itaú",
    "Ops - Produtos",
    "Produtos",
    "Relacionamento Itaú",
    "",
]
