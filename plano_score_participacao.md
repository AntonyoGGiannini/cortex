# Cortex — Score de Participação (Antonyo)
### Plano completo v1 + v2 com pipeline de desenvolvimento

Documento de design. Banco: `cortex_db` (Supabase, projeto `rcjckulvccwrdpbupfws`).
Speaker alvo: `antonyo_giannini` (Gerente / Inteligência Comercial / Comercial).

---

## 1. Princípios

1. **Mede qualidade da participação, não volume de fala.** Falar 100% num alinhamento é monólogo, não engajamento.
2. **Normaliza por contexto** (nº de participantes e tipo de reunião). Share bruto não é comparável entre um 1:1 e uma weekly de 8 pessoas.
3. **Auditável e incremental.** v1 é 100% SQL determinístico; v2 adiciona um eixo qualitativo via LLM, sem reescrever a v1.
4. **Reaproveita a infra existente** (`fact_recording_speakers`, `fact_speaker_observations`).

---

## 2. Modelo de dados

**Já existe e é usado:**

| Tabela | Papel no score |
|---|---|
| `fact_recordings` | metadados da reunião: `category`, `duration_seconds`, `meeting_date`, `transcript` |
| `fact_recording_speakers` | sinal principal: `talk_words`, `talk_seconds`, par (recording, speaker) |
| `dim_speakers` | identifica o Antonyo e o tipo de cada participante (`interno`/`cliente`/...) |
| `fact_speaker_observations` | base para o eixo qualitativo da v2 (hoje com 7 linhas) |

**Falta criar (v1):** `v_participation_meeting`, `v_participation_period` (views).
**Falta criar (v2):** `fact_participation_signals` (sinais qualitativos por reunião) e `fact_participation_score` (score consolidado por reunião/período).

---

## 3. v1 — Score quantitativo (share normalizado + adequação por contexto)

### 3.1 Métricas derivadas por reunião

Usar **`talk_words`** como base (o banco marca palavras como mais robusto a erro de timestamp).

```
share_w   = ant_words / tot_words                  -- fração da fala total
eng_ratio = share_w * n_speakers                    -- 1.0 = "cota justa"; >1 acima da média
```

`eng_ratio` é a métrica central: normaliza automaticamente pelo tamanho da reunião. Num 1:1 (n=2), 50% de fala = eng_ratio 1.0. Numa weekly de 8, 12,5% = eng_ratio 1.0.

### 3.2 Bandas-alvo por categoria (`[lo, hi]` em eng_ratio)

A pontuação é **máxima dentro da banda**, e cai tanto por ausência quanto por dominância.

| Categoria | lo | hi | Racional |
|---|---|---|---|
| 1:1 (com liderado) | 0.7 | 1.2 | dar espaço, mas conduzir |
| Alinhamento | 0.8 | 1.4 | contribuição ativa |
| Weekly | 1.0 | 1.8 | puxar pontos sem ocupar tudo |
| Mensal | 0.8 | 1.6 | participação seletiva |
| Apresentação | 1.2 | 2.2 | espera-se que você conduza |
| Projeto / Itaú (externos) | 0.5 | 1.5 | presença ativa já basta |
| default | 0.8 | 1.5 | — |

> As bandas são parâmetros calibráveis (Fase 2), não verdade absoluta.

### 3.3 Função de adequação (0–100)

Função trapezoidal: platô de 100 dentro da banda, decaimento dos dois lados.

```
adeq(eng_ratio, lo, hi, n):
    if eng_ratio < lo:        # silêncio/ausência -> cai a 0
        return 100 * (eng_ratio / lo)
    if eng_ratio <= hi:       # faixa ideal
        return 100
    # acima de hi -> dominância -> decai de 100 (em hi) a 50 (em n = falar sozinho)
    return 100 - 50 * least((eng_ratio - hi) / nullif(n - hi, 0), 1)
```

Assimetria proposital: ausência zera; dominância penaliza menos (mín. 50), porque monopolizar é menos grave que sumir — mas ainda não é o ideal para um gestor.

### 3.4 Agregação no período

```
score_periodo = sum(adeq_i * w_i) / sum(w_i),   w_i = duration_seconds_i
```

Pondera por duração (reunião de 90 min pesa mais que uma de 3 min). Métricas auxiliares do período: nº de reuniões, `consistencia` = % de reuniões com adeq ≥ 70, e flag de reuniões onde share ≈ 0 (presente mas calado).

### 3.5 View SQL (esqueleto)

```sql
create or replace view v_participation_meeting as
with tot as (
  select recording_id, count(*) n_speakers,
         sum(talk_words) tot_words
  from fact_recording_speakers group by recording_id
),
ant as (
  select rs.recording_id, rs.talk_words ant_words
  from fact_recording_speakers rs
  join dim_speakers s on s.id = rs.speaker_id
  where s.speaker_key = 'antonyo_giannini'
),
base as (
  select r.id, r.title, r.meeting_date, r.category, r.duration_seconds,
         t.n_speakers, t.tot_words, a.ant_words,
         (a.ant_words::numeric / nullif(t.tot_words,0)) * t.n_speakers as eng_ratio
  from fact_recordings r
  join tot t on t.recording_id = r.id
  join ant a on a.recording_id = r.id
  where t.tot_words is not null            -- ignora reuniões não processadas
),
banded as (
  select *,
    case category
      when '1:1' then 0.7 when 'Weekly' then 1.0 when 'Mensal' then 0.8
      when 'Apresentação' then 1.2 when 'Projeto' then 0.5 when 'Itaú' then 0.5
      when 'Alinhamento' then 0.8 else 0.8 end as lo,
    case category
      when '1:1' then 1.2 when 'Weekly' then 1.8 when 'Mensal' then 1.6
      when 'Apresentação' then 2.2 when 'Projeto' then 1.5 when 'Itaú' then 1.5
      when 'Alinhamento' then 1.4 else 1.5 end as hi
  from base
)
select *,
  round(case
    when eng_ratio < lo then 100*(eng_ratio/lo)
    when eng_ratio <= hi then 100
    else 100 - 50*least((eng_ratio-hi)/nullif(n_speakers-hi,0),1)
  end, 1) as participation_score
from banded;
```

```sql
create or replace view v_participation_period as
select count(*) n_reunioes,
       round(sum(participation_score*duration_seconds)/sum(duration_seconds),1) score_periodo,
       round(100.0*avg((participation_score>=70)::int),0) consistencia_pct
from v_participation_meeting;
```

### 3.6 Pipeline de desenvolvimento — v1

| Fase | Entrega | Critério de pronto |
|---|---|---|
| 0. Higiene de dados | backfill das ~4 reuniões com `talk_words` nulo; confirmar mapeamento do speaker | 0 reuniões relevantes sem fala registrada |
| 1. Build | criar `v_participation_meeting` + `v_participation_period` via `apply_migration` | views retornam as 30 reuniões |
| 2. Calibração | revisar bandas com você em 5–10 reuniões âncora; ajustar `lo/hi` | bandas aprovadas |
| 3. Sanidade | comparar score com sua leitura manual; checar extremos (DH 100%, Itaú 2,6%) | sem falso-positivo grosseiro |
| 4. Exposição | painel (Streamlit / artifact) com score por reunião e do período | você acessa sozinho |

---

## 4. v2 — Eixo de substância / influência (LLM sobre transcript)

A v1 mede *quanto* você fala em relação ao contexto. A v2 mede *o que* você fala — usando o `transcript`, que já está no banco.

### 4.1 Sinais extraídos (por reunião, para o Antonyo)

| Sinal | O que captura |
|---|---|
| `n_perguntas` | perguntas que abriram/conduziram a discussão |
| `n_decisoes_conduzidas` | decisões em que você foi o condutor |
| `n_action_items_owned` | tarefas que você assumiu |
| `n_ideias_introduzidas` | propostas/ideias novas trazidas por você |
| `assertividade` | tom (passivo ↔ assertivo ↔ dominante), 0–1 |

### 4.2 Armazenamento

Nova tabela `fact_participation_signals (recording_id, speaker_id, sinal, valor, evidence, model, conf, created_at)` — mesmo padrão de `fact_speaker_observations`. Usar `fact_recordings.behavior_processed_at` como carimbo de "já extraído" (a coluna já existe).

### 4.3 Pipeline de extração (batch / edge function)

```
para cada recording com behavior_processed_at IS NULL e transcript NOT NULL:
   1. prompt estruturado -> LLM devolve JSON dos sinais (com evidência citada)
   2. grava em fact_participation_signals
   3. seta behavior_processed_at = now()
```

`substance_score` (0–100) = combinação normalizada dos sinais por minuto de fala (densidade), para não premiar só quem fala muito.

### 4.4 Score final em 2 eixos

Manter os eixos separados é mais informativo que um número só:

```
Participação (v1)  →  você está no nível certo de fala para o contexto?
Influência   (v2)  →  o que você fala move a reunião (decisões, ideias, ownership)?
```

Composto opcional: `score_geral = 0.5*v1 + 0.5*v2`. Recomendo mostrar os dois eixos + composto, não só o composto.

### 4.5 Pipeline de desenvolvimento — v2

| Fase | Entrega | Critério de pronto |
|---|---|---|
| 5. Schema | criar `fact_participation_signals` e `fact_participation_score` | migrations aplicadas |
| 6. Prompt | prompt de extração + JSON schema; testar em 3 transcripts | extração com evidência rastreável |
| 7. Backfill | rodar nas 30 reuniões; popular `behavior_processed_at` | 100% das reuniões com transcript processadas |
| 8. Score | calcular `substance_score` e composto 2 eixos | scores plausíveis vs leitura manual |
| 9. Validação (subagente) | auditar amostra: evidência citada bate com o transcript? | precisão aceitável acordada |
| 10. Automação | rodar extração + recálculo a cada nova reunião ingerida | pipeline roda sem intervenção |

---

## 5. Roadmap consolidado

```
Fase 0  Higiene de dados            ─┐
Fase 1  Views v1                     │  v1 entregável e usável
Fase 2  Calibração de bandas         │
Fase 3  Sanidade                     │
Fase 4  Painel v1                   ─┘
Fase 5  Schema v2                   ─┐
Fase 6  Prompt de extração           │
Fase 7  Backfill transcripts         │  v2: eixo de influência
Fase 8  Score 2 eixos                │
Fase 9  Validação por subagente      │
Fase 10 Automação na ingestão       ─┘
```

Recomendação: fechar e usar a v1 antes de iniciar a v2. A v1 já responde "estou participando no nível certo?"; a v2 responde "minha participação tem peso?".

---

## 6. Riscos, premissas e qualidade de dados

- **~4 reuniões sem `talk_words`/`talk_seconds`** (não processadas): hoje a view as ignora. Tratar na Fase 0.
- **Diarização do Plaud**: se a atribuição de fala ao speaker errar, contamina o share. Amostrar para validar.
- **Bandas são opinião calibrável**, não verdade. Risco de o score refletir minha premissa, não a sua — daí a Fase 2.
- **v2 depende de LLM**: custo por transcript e risco de alucinação. Mitigar exigindo evidência citada e auditando amostra (Fase 9).

## 7. Segurança (não bloqueante)

`fact_speaker_observations` e `dim_speaker_profile` estão com **RLS desabilitado** (expostas à anon key). Ao criar `fact_participation_signals`/`fact_participation_score`, habilitar RLS com políticas desde o início.

---

## 8. Próximos passos imediatos

1. Aprovar (ou ajustar) as bandas-alvo da seção 3.2.
2. Eu aplico as migrations das views v1 e te devolvo o score das 30 reuniões.
3. Você valida 5–10 reuniões âncora; calibramos.
4. Decidimos o go para a v2.
