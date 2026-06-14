# Cortex — Visão & Escopo

> Documento canônico do projeto. Define **o quê** e **por quê** antes de qualquer
> código. Última atualização: 2026-06-14.

## 1. Contexto & Racional de Negócio

Como líder de Inteligência Comercial, o volume de interações com stakeholders e
frentes de projeto gera alta carga cognitiva. O **Plaud** já resolve a *captura*
da informação (grava reuniões e gera transcrição, tópicos e título por IA), mas
a inteligência está no **cruzamento** desses dados.

- **Problema — dispersão de contexto.** Evolução de projetos, acordos de reunião
  e o perfil/estilo dos stakeholders ficam perdidos em resumos isolados ou
  apenas na memória.
- **Solução — base única e governada.** Um sistema proprietário focado em **alta
  governança de dados** (*human-in-the-loop*). O objetivo não é automatizar tudo,
  e sim ter um banco **extremamente confiável** para análises reais: alocação de
  tempo, histórico de projetos e gestão de relacionamento.

## 2. Princípios de Design

1. **Governança acima de automação.** Pessoas e projetos são cadastrados e
   curados manualmente. Aceita-se o esforço manual recorrente em troca de um
   banco limpo, sem duplicidade (ex.: "Ana S." vs. "Ana Silva").
2. **Human-in-the-loop.** Nenhuma reunião é persistida sem revisão e validação
   na interface.
3. **IA secundária na V1.** Usa-se apenas o que o Plaud já entrega. Sem camada
   extra de LLM — menos custo, menos latência, mais controle.

## 3. Arquitetura & Stack

| Camada | Tecnologia | Papel |
|---|---|---|
| Ingestão | **Plaud** (via MCP) | Fonte dos dados de reunião (transcrição, tópicos, título). |
| Control Tower (frontend) | **Streamlit** | Maestro da operação: filas de entrada e validação. |
| Backend | **Supabase (PostgreSQL)** | Armazenamento das entidades e reuniões. |
| Integração futura (V2) | **API do Jira** | Enriquecimento de status de projetos. |

> **Observação operacional:** o Supabase do Cortex será um **projeto dedicado**;
> não reutilizar projetos existentes de outros sistemas.

## 4. Fontes de Dados: o que o Plaud realmente entrega

> Validado via MCP em 2026-06-14 (426 gravações na conta; 343 com summary).

O escopo inicial assumia que o Plaud retornaria "transcrição, resumo e lista de
participantes via IA". A validação mostrou que **parte disso não vem pronta** —
o que **reforça** a abordagem *human-in-the-loop*:

| Endpoint (MCP) | Retorna |
|---|---|
| `list_recordings` | `id`, `name`, `created_at`, `duration_min`, `has_summary`, `has_transcript`. |
| `get_summary(file_id)` | **Outline de tópicos**: array de `{start_time, end_time, topic}`. Não é resumo em prosa. |
| `get_recording_detail(file_id)` | Metadados + `aiContentHeader`: **`headline`** (título por IA), `category` (ex.: "Nota de reunião"), `recommend_questions`, idioma; `start_time` (epoch ms); diarização ativa. |
| `get_transcript(file_id)` | Texto `"[mm:ss] Speaker N: ..."`. Speakers **genéricos** por padrão. |

**Não entregues pelo MCP:** resumo em prosa, *to-dos*/action items e nomes de
participantes.

### Modelo operacional: curadoria na fonte

Para resolver os gaps acima sem adicionar IA, a curadoria começa **dentro do
Plaud**, antes da ingestão:

- O usuário **renomeia os speakers** e define o **título da reunião** no Plaud.
  Assim o MCP já puxa nomes reais (não "Speaker 1/2").
- Se algo vier genérico, **corrige-se no Plaud** antes de subir ao Supabase.
- No Streamlit, completa-se o ciclo: **vínculo** dos participantes às entidades
  oficiais e **curadoria** de `resumo` e `to_dos`.

## 5. Modelo de Dados (V1)

Decisão de V1: usar **arrays de UUID** para os relacionamentos, evitando tabelas
pivô neste primeiro momento (acelera o desenvolvimento).

### `pessoas` — base do Personal CRM (CRUD 100% manual)

| Campo | Tipo | Origem |
|---|---|---|
| `id` | UUID | gerado |
| `nome` | text | manual |
| `cargo` | text | manual |
| `estilo_comunicacao` | text | manual |
| `dicas_relacionamento` | text | manual |

### `projetos` — hub de demandas (CRUD manual)

| Campo | Tipo | Origem |
|---|---|---|
| `id` | UUID | gerado |
| `nome` | text | manual |
| `status` | text | manual |
| `jira_key` | text | manual (prepara V2) |

### `reunioes` — registro transacional

| Campo | Tipo | Origem validada |
|---|---|---|
| `id` | UUID | gerado |
| `plaud_id` | text **unique** | Plaud `file_id` |
| `data_hora` | timestamptz | Plaud `start_time` (epoch ms → timestamp) |
| `titulo` | text | Plaud `headline` (definido na fonte) |
| `tipo_reuniao` | text | **manual** (dropdown — governança) |
| `resumo` | text | **curadoria manual** (Plaud não entrega prosa) |
| `topicos` | text[] | Plaud `get_summary` → lista de `topic` |
| `to_dos` | text[] | **curadoria manual** (Plaud não entrega) |
| `pessoas_ids` | uuid[] | **vínculo manual** (speakers nomeados → entidades) |
| `projetos_ids` | uuid[] | **vínculo manual** |

Notas:

- `tipo_reuniao` é controlado por **dropdown** (ex.: 1:1, Weekly, Alinhamento
  Rápido) para garantir governança analítica. O `category` do Plaud é genérico
  demais para isso.
- O campo `titulo` foi acrescentado ao escopo original por ser um ganho barato:
  o Plaud já gera um headline melhor que o nome cru do arquivo.
- **A confirmar na V1:** verificar se, com speakers/template configurados no
  Plaud, surgem `resumo`/`to_dos` estruturados. Caso não, mantém-se a curadoria
  manual.

## 6. Fluxo Operacional (o piloto no Streamlit)

### Módulo de Entidades (CRUD)

Telas dedicadas para **cadastrar, editar e documentar** pessoas e projetos — a
base curada do CRM.

### Módulo Caixa de Entrada (fila)

1. O sistema puxa o histórico do Plaud e compara com os `plaud_id` já salvos.
2. Reuniões novas caem na fila de **Pendentes**.
3. Ao abrir uma pendência, o usuário revisa o título e os tópicos, **vincula**
   participantes e projetos às entidades oficiais (via seletores) e **cura** o
   `resumo` e os `to_dos`, definindo também o `tipo_reuniao`.
4. Após a validação, a reunião é **persistida** e sai da fila.

## 7. Escopo V1 vs. V2

**Dentro da V1**

- CRUD manual de pessoas e projetos.
- Ingestão e fila de reuniões do Plaud com curadoria humana.
- Relacionamentos via arrays de UUID.
- Sem LLM extra; sem integração com Jira.

**Reservado para a V2**

- Integração com a **API do Jira** (via `jira_key`) para status de projetos.
- Eventual migração de arrays → **tabelas pivô**, se a volumetria exigir.
- Possíveis camadas analíticas/IA sobre a base já curada.

## 8. Premissas, Riscos e Trade-offs

- **Governança vs. automação.** Não automatizar a criação de pessoas/projetos
  custa esforço manual recorrente, mas garante um banco limpo e sem duplicidade
  — fundamental para cruzamentos analíticos futuros.
- **Arrays vs. tabelas pivô.** Arrays aceleram a V1 e simplificam o código do
  Streamlit; o custo é uma query SQL mais complexa no futuro (uso de
  `UNNEST()`). Migrável para pivôs na V2.
- **Controle da IA.** Eliminar a camada extra de LLM reduz custo e latência; em
  troca, `resumo`/`to_dos` dependem da curadoria visual do usuário.
- **Dependência da curadoria na fonte (Plaud).** A qualidade dos nomes de
  participantes depende de o usuário renomear os speakers no Plaud antes de
  ingerir. Mitigação: validação na fila do Streamlit antes de persistir.

## Apêndice — Formatos validados do Plaud MCP

Referência rápida (validada em 2026-06-14) para a futura implementação. O
parâmetro em todos os `get_*` é **`file_id`** (não `recording_id`).

**`list_recordings`** → array de objetos:

```json
{ "id": "…", "name": "…", "created_at": "2026-06-10 18:29",
  "duration_min": 64.2, "has_summary": true, "has_transcript": true }
```

**`get_summary(file_id)`** → array de tópicos:

```json
[ { "start_time": 12650, "end_time": 27090, "topic": "Agenda da Apresentação" } ]
```

**`get_recording_detail(file_id)`** → metadados + cabeçalho de IA:

```json
{ "file_id": "…", "start_time": 1781177720000, "duration": 3854000,
  "extra_data": { "aiContentHeader": {
    "headline": "06-11 Reunião Semanal: …", "category": "Nota de reunião",
    "language_code": "pt", "recommend_questions": [ "…" ] } } }
```

**`get_transcript(file_id)`** → string:

```text
[00:00] Speaker 1: …
[00:17] Speaker 2: …
```
