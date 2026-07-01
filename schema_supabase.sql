-- ============================================================
-- Cortex — Schema Supabase (Plaud -> Streamlit -> Postgres)
-- Fluxo:
--   1) fact_recordings        : reuniões/gravações vindas da API Plaud
--   2) dim_speakers           : participantes (id único pelo nome ajustado)
--   3) fact_recording_speakers: ponte N:N entre reunião e participantes
--
-- "Já registrado" = existência do plaud_id em fact_recordings
-- "Salvar ou atualizar" = UPSERT via ON CONFLICT nas chaves naturais
-- ============================================================

-- ------------------------------------------------------------
-- 0. Extensões e função utilitária de updated_at
-- ------------------------------------------------------------
create extension if not exists "pgcrypto";  -- gen_random_uuid()

create or replace function set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

-- ------------------------------------------------------------
-- 1. dim_speakers — participantes
--    speaker_key = nome normalizado (chave de negócio única)
-- ------------------------------------------------------------
create table if not exists dim_speakers (
  id              uuid primary key default gen_random_uuid(),

  speaker_key     text not null unique,        -- nome ajustado/normalizado (ex.: "antonyo_giannini")
  display_name    text not null,               -- nome de exibição (ex.: "Antonyo Giannini")
  raw_name        text,                         -- nome original como veio do Plaud (auditoria)

  speaker_type    text not null default 'interno'
                  check (speaker_type in ('interno','cliente','parceiro','outro')),
  email           text,
  company         text,
  diretoria       text,
  area            text,
  role            text,                          -- cargo/função
  notes           text,

  is_active       boolean not null default true,
  needs_review    boolean not null default false,  -- auto-criados do Plaud entram como true

  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create index if not exists idx_dim_speakers_display_name on dim_speakers (display_name);
create index if not exists idx_dim_speakers_type          on dim_speakers (speaker_type);
create index if not exists idx_dim_speakers_needs_review  on dim_speakers (needs_review) where needs_review;

drop trigger if exists trg_dim_speakers_updated_at on dim_speakers;
create trigger trg_dim_speakers_updated_at
  before update on dim_speakers
  for each row execute function set_updated_at();

-- ------------------------------------------------------------
-- 2. fact_recordings — reuniões/gravações
--    plaud_id = id da gravação na API Plaud (chave natural p/ upsert)
-- ------------------------------------------------------------
create table if not exists fact_recordings (
  id                uuid primary key default gen_random_uuid(),

  plaud_id          text not null unique,        -- id do recording na Plaud (controla "já registrado")

  title             text,                         -- título editável pelo usuário
  meeting_date      date,                         -- data da reunião
  started_at        timestamptz,                  -- início (timestamp da gravação)
  duration_seconds  integer,                      -- duração em segundos

  summary           text,                         -- resumo (Plaud ou editado)
  transcript        text,                         -- transcrição completa (opcional)
  transcript_url    text,                         -- link p/ arquivo, se preferir não guardar texto
  audio_url         text,

  category          text,                         -- ex.: "comercial", "interno", "cliente"
  client_name       text,                         -- cliente associado, se houver
  tags              text[] default '{}',          -- etiquetas livres
  language          text default 'pt-BR',

  -- workflow de revisão no Streamlit
  status            text not null default 'pendente'
                    check (status in ('pendente','revisado','arquivado')),
  reviewed_by       text,
  reviewed_at       timestamptz,

  -- metadados crus da API (guarde o payload original p/ reprocessar depois)
  raw_payload       jsonb,

  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);

create index if not exists idx_fact_recordings_meeting_date on fact_recordings (meeting_date desc);
create index if not exists idx_fact_recordings_status       on fact_recordings (status);
create index if not exists idx_fact_recordings_client       on fact_recordings (client_name);
create index if not exists idx_fact_recordings_tags         on fact_recordings using gin (tags);

drop trigger if exists trg_fact_recordings_updated_at on fact_recordings;
create trigger trg_fact_recordings_updated_at
  before update on fact_recordings
  for each row execute function set_updated_at();

-- ------------------------------------------------------------
-- 3. fact_recording_speakers — ponte N:N
--    quem participou de cada reunião
-- ------------------------------------------------------------
create table if not exists fact_recording_speakers (
  recording_id    uuid not null references fact_recordings (id) on delete cascade,
  speaker_id      uuid not null references dim_speakers (id)    on delete restrict,

  role_in_meeting text,                           -- ex.: "host", "convidado"
  talk_seconds    integer,                        -- tempo de fala em SEGUNDOS
  talk_words      integer,                        -- total de palavras faladas

  created_at      timestamptz not null default now(),

  primary key (recording_id, speaker_id)
);

create index if not exists idx_rec_speakers_speaker on fact_recording_speakers (speaker_id);

-- ============================================================
-- Exemplos de UPSERT (use no app Streamlit)
-- ============================================================

-- 2a) Upsert de reunião (salva ou atualiza pelo plaud_id)
-- insert into fact_recordings (plaud_id, title, meeting_date, started_at, duration_seconds, summary, raw_payload)
-- values (:plaud_id, :title, :meeting_date, :started_at, :duration_seconds, :summary, :raw_payload)
-- on conflict (plaud_id) do update set
--   title            = excluded.title,
--   meeting_date     = excluded.meeting_date,
--   started_at       = excluded.started_at,
--   duration_seconds = excluded.duration_seconds,
--   summary          = excluded.summary,
--   raw_payload      = excluded.raw_payload;

-- 2b) Upsert de speaker (salva ou atualiza pelo speaker_key)
-- insert into dim_speakers (speaker_key, display_name, raw_name, speaker_type, email, company, role)
-- values (:speaker_key, :display_name, :raw_name, :speaker_type, :email, :company, :role)
-- on conflict (speaker_key) do update set
--   display_name = excluded.display_name,
--   email        = excluded.email,
--   company      = excluded.company,
--   role         = excluded.role;

-- 2c) Vincular participante à reunião
-- insert into fact_recording_speakers (recording_id, speaker_id, role_in_meeting)
-- values (:recording_id, :speaker_id, :role)
-- on conflict (recording_id, speaker_id) do nothing;

-- 1) Listar plaud_ids já registrados (p/ flag "já registrado" no Streamlit)
-- select plaud_id from fact_recordings;

-- ============================================================
-- View de interação por pessoa (ranking "com quem interajo mais")
-- ============================================================
-- security_invoker: a view respeita o RLS de quem consulta (não o do criador).
create or replace view vw_speaker_interacao
with (security_invoker = true) as
select
  s.id            as speaker_id,
  s.display_name,
  s.speaker_type,
  s.diretoria,
  s.area,
  count(distinct rs.recording_id)                    as reunioes,
  coalesce(sum(rs.talk_seconds), 0)::bigint          as fala_total_seg,
  round(coalesce(sum(rs.talk_seconds), 0)::numeric / 60.0, 1) as fala_total_min,
  coalesce(sum(rs.talk_words), 0)::bigint            as palavras_total,
  max(r.meeting_date)                                as ultima_reuniao
from dim_speakers s
left join fact_recording_speakers rs on rs.speaker_id = s.id
left join fact_recordings r          on r.id = rs.recording_id
group by s.id, s.display_name, s.speaker_type, s.diretoria, s.area;

-- ============================================================
-- View de cobertura por reunião (qualidade de captura)
--   cobertura_pct = % da duração coberto por fala atribuída.
--   < ~70% = segmentos sem timing no Plaud ou curadoria pendente.
-- ============================================================
create or replace view vw_cobertura_reuniao
with (security_invoker = true) as
select
  r.id                                                  as recording_id,
  r.title,
  r.meeting_date,
  r.duration_seconds,
  count(frs.speaker_id)                                 as n_speakers,
  coalesce(sum(frs.talk_seconds), 0)                    as fala_total_seg,
  coalesce(sum(frs.talk_words), 0)                      as palavras_total,
  round(100.0 * coalesce(sum(frs.talk_seconds),0) / nullif(r.duration_seconds,0), 0) as cobertura_pct
from fact_recordings r
left join fact_recording_speakers frs on frs.recording_id = r.id
group by r.id, r.title, r.meeting_date, r.duration_seconds;

-- ============================================================
-- MÓDULO PROJETOS / TEMAS
-- Objetivo: ter o CONTEXTO COMPLETO de um tema, juntando tudo que foi
-- falado sobre ele em QUALQUER reunião.
--
-- Desenho:
--   dim_projects          : cadastro curado do projeto/tema (CRUD manual)
--   fact_project_mentions : 1 linha por (projeto × reunião) COM sinal
--                           (update, trechos-evidência, decisões, to-dos)
--   fact_project_scan     : livro-razão de cobertura — registra todo par
--                           (projeto × reunião) já avaliado, COM ou SEM menção.
--                           É o que permite, ao cadastrar um projeto novo,
--                           varrer retroativamente todas as reuniões antigas
--                           sem reprocessar o que já foi visto.
-- ============================================================

-- ------------------------------------------------------------
-- 4. dim_projects — cadastro do projeto/tema (CRUD manual)
-- ------------------------------------------------------------
create table if not exists dim_projects (
  id                   uuid primary key default gen_random_uuid(),

  project_key          text not null unique,        -- nome normalizado (chave de negócio)
  name                 text not null,               -- nome de exibição
  description          text,                         -- o que é o tema (ajuda a IA a casar)
  aliases              text[] default '{}',          -- termos como aparecem nas calls (recall)

  status               text not null default 'ativo'
                       check (status in ('ativo','pausado','concluido','arquivado')),
  area                 text,
  owner                text,                          -- responsável
  jira_key             text,                          -- prepara V2 (Jira)

  -- resumo vivo consolidado (gerado pela IA a partir das menções)
  consolidated_summary text,
  open_todos           jsonb default '[]'::jsonb,     -- to-dos abertos agregados (cache p/ leitura)
  summary_updated_at   timestamptz,

  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now()
);

create index if not exists idx_dim_projects_status  on dim_projects (status);
create index if not exists idx_dim_projects_aliases  on dim_projects using gin (aliases);

drop trigger if exists trg_dim_projects_updated_at on dim_projects;
create trigger trg_dim_projects_updated_at
  before update on dim_projects
  for each row execute function set_updated_at();

-- ------------------------------------------------------------
-- 5. fact_project_mentions — o que cada reunião trouxe sobre o projeto
--    unique (project_id, recording_id) -> upsert idempotente
-- ------------------------------------------------------------
create table if not exists fact_project_mentions (
  id            uuid primary key default gen_random_uuid(),

  project_id    uuid not null references dim_projects   (id) on delete cascade,
  recording_id  uuid not null references fact_recordings (id) on delete cascade,

  relevance     numeric,                              -- 0-1: quão central o tema foi nesta call
  update_text   text,                                 -- 1-2 linhas: o que andou/mudou
  excerpts      text[] default '{}',                   -- trechos-evidência citáveis
  decisions     text[] default '{}',                   -- decisões tomadas nesta call
  todos         jsonb  default '[]'::jsonb,             -- [{descricao, responsavel?}]
  speaker_ids   uuid[] default '{}',                   -- quem falou do tema (opcional)

  model         text,
  created_at    timestamptz not null default now(),

  unique (project_id, recording_id)
);

create index if not exists idx_proj_mentions_project on fact_project_mentions (project_id);
create index if not exists idx_proj_mentions_rec     on fact_project_mentions (recording_id);

-- ------------------------------------------------------------
-- 6. fact_project_scan — livro-razão de cobertura (projeto × reunião)
--    Pendente para um projeto = reuniões com transcript ainda NÃO presentes
--    aqui para esse project_id. Resolve forward (call nova) e backfill
--    (projeto novo olhando o passado) com a mesma lógica.
-- ------------------------------------------------------------
create table if not exists fact_project_scan (
  project_id    uuid not null references dim_projects   (id) on delete cascade,
  recording_id  uuid not null references fact_recordings (id) on delete cascade,

  scanned_at    timestamptz not null default now(),
  had_mention   boolean not null default false,

  primary key (project_id, recording_id)
);

create index if not exists idx_proj_scan_project on fact_project_scan (project_id);

-- ============================================================
-- View: timeline de menções com título/data da reunião
-- ============================================================
create or replace view vw_project_timeline
with (security_invoker = true) as
select
  m.id,
  m.project_id,
  m.recording_id,
  r.title          as meeting_title,
  r.meeting_date,
  m.relevance,
  m.update_text,
  m.excerpts,
  m.decisions,
  m.todos,
  m.speaker_ids,
  m.created_at
from fact_project_mentions m
join fact_recordings r on r.id = m.recording_id;
