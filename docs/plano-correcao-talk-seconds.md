# Plano de correção — `talk_seconds` (unidade) e `vw_speaker_interacao`

> Status: **proposta — não executar ainda.** Última atualização: 2026-06-28.
> Escopo: corrigir a unidade de tempo de fala na ponte `fact_recording_speakers`
> e a view que a consome. Toda análise é **por `id`/`plaud_id` da reunião** — o
> `title` é apenas rótulo e não deve ser chave de agregação.

## 1. Diagnóstico (o que já se sabe)

- A coluna `fact_recording_speakers.talk_seconds` **armazena milissegundos**, não
  segundos. Evidência: razão mediana `talk/duration` = 144 e máxima = 902 no
  dataset; só faz sentido dividindo por 1000 (≈14% do tempo por pessoa na mediana).
- A magnitude é **mista** dentro da mesma reunião (alguns vínculos ~1000× maiores
  que outros), o que aponta para dois caminhos de cálculo coexistindo.
- Consequência: `vw_speaker_interacao.fala_total_min` (que faz `sum(talk_seconds)/60`)
  está **errada por 1000×**.

### Causa-raiz provável (a confirmar no passo 2)

Em `plaud_client.summarize_speakers` o tempo de cada segmento é calculado assim:

- se o segmento tem `duration` → `seg_ms = float(duration)` (correto, em ms);
- senão → `seg_ms = (end - start) * 1000`, com normalização ms→s só quando
  `end/start > 1e10`.

Os `start/end` do Plaud são **relativos em ms** (ex.: 25 min = 1.500.000 ms),
sempre **abaixo de 1e10**. Logo não são convertidos, e `(end - start) * 1000`
multiplica um valor que já está em ms por 1000 → resultado ~1000× inflado.
Segmentos com `duration` saem corretos; os que caem no fallback saem inflados —
explicando a unidade mista.

## 2. Passos do plano

### Passo 1 — Confirmar a causa-raiz (somente leitura)

- Pegar 2–3 `plaud_id` e inspecionar os segmentos crus: quais trazem `duration` e
  quais caem no fallback `end-start`.
- Rodar `summarize_speakers` atual e comparar com o valor gravado na ponte, por
  speaker, para fechar a conta do fator de erro por segmento.
- **Gate:** confirmar que o erro vem do fallback de `(end-start)*1000`. Se houver
  outra fonte (ex.: caminho antigo de gravação), documentar antes de seguir.

### Passo 2 — Corrigir o código (`plaud_client.py`)

- Normalizar `start/end` para segundos **por valor**, não por limiar de época:
  os timestamps de segmento são relativos; tratar sempre como ms (dividir por
  1000) em vez de comparar com `1e10`.
- Calcular `seg_seconds` de forma única e consistente:
  `duration` (ms→s) quando presente; senão `max(0, end_s - start_s)`.
- Garantir que `summarize_speakers` retorne `talk_seconds` **em segundos inteiros**,
  coerente com o nome da coluna e com `fact_recordings.duration_seconds`.
- Adicionar um teste rápido (`test_speakers.py` já existe) que valide:
  `sum(talk_seconds_por_speaker) <= duration_seconds * n_speakers` e que nenhum
  speaker exceda `duration_seconds`.

### Passo 3 — Corrigir os dados existentes (101 vínculos)

Duas opções, com trade-off:

- **Opção A — re-backfill a partir da fonte (recomendada).** Rodar
  `backfill_talk_seconds.py` com o código corrigido; recalcula `talk_seconds` do
  zero a partir do Plaud, casando por `recording_id` + `speaker_key`. Idempotente
  e autoritativo. Requer que as gravações ainda existam no Plaud (existem hoje).
  Primeiro `--dry-run`.
- **Opção B — conversão cega no banco (`talk_seconds = talk_seconds / 1000`).**
  Mais rápida, mas **arriscada**: como a unidade é mista, dividir tudo por 1000
  corromperia os vínculos que já estavam corretos. Só seria aceitável se o passo 1
  provar uniformidade total — o que os dados atuais contradizem.

**Recomendação:** Opção A. Não fazer a Opção B.

### Passo 4 — Corrigir e blindar a view `vw_speaker_interacao`

- Com `talk_seconds` em segundos reais, a aritmética `/60` passa a dar minutos
  corretos — revisar e validar.
- Recriar a view como **`SECURITY INVOKER`** (hoje é `SECURITY DEFINER`, apontado
  como ERROR pelo advisor de segurança — ela ignora RLS).
- Versionar a view no `schema_supabase.sql` (hoje ela existe no banco mas não no
  arquivo — drift de schema).
- Opcional: filtrar o speaker "AI Chat" na view (decisão adiada — item marcado
  como "ignorar" por ora).

### Passo 5 — Verificação (obrigatória antes de fechar)

- **Sanidade quantitativa:** por `recording_id`, nenhum speaker com
  `talk_seconds > duration_seconds`; soma das falas coerente com a duração.
- **Spot-check qualitativo:** conferir 2–3 reuniões contra o transcript (quem
  falou mais bate com a percepção).
- Re-rodar `get_advisors` (security) e confirmar que o ERROR da view sumiu.

## 3. Decisões em aberto (preciso do seu aval)

1. **Estratégia de dados:** confirma Opção A (re-backfill) em vez da conversão
   cega? *(recomendado: sim)*
2. **Semântica da coluna:** manter o nome `talk_seconds` guardando segundos
   *(recomendado)*, ou renomear para deixar a unidade explícita?
3. **Métrica complementar:** aproveitar a correção para também gravar
   `talk_words` (contagem de palavras por speaker, mais robusta a erro de
   timestamp)? Ou manter o escopo só na unidade agora?

## 4. Premissas e riscos

- **Premissa:** as 30 gravações seguem disponíveis no Plaud para re-backfill.
- **Risco:** se o Plaud tiver mudado o formato dos segmentos desde a 1ª ingestão,
  o re-backfill pode divergir do que gerou os dados atuais — mitigado pelo
  `--dry-run` e pela verificação do passo 5.
- **Risco baixo:** a correção da view não afeta escrita; só leitura/segurança.
- **Fora de escopo:** duplicatas de título (são reuniões distintas por `id`) e o
  speaker "AI Chat" (decisão de ignorar).
