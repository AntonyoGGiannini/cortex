# Cortex

> **Personal CRM & Hub de Projetos** — um "segundo cérebro" para Inteligência Comercial.

**Status:** 🟡 Em definição — visão & escopo. Ainda sem código.

Cortex é uma ferramenta **pessoal** para organizar o conhecimento gerado nas
interações com stakeholders e frentes de projeto. A captura já acontece no
**Plaud** (gravação → transcrição, tópicos e título por IA); o valor do Cortex
está em **cruzar** esses dados com um cadastro confiável de **pessoas** e
**projetos**, sob forte governança *human-in-the-loop*.

## Problema

O contexto se dispersa: a evolução dos projetos, os acordos de reunião e o
perfil/estilo dos stakeholders ficam presos em resumos isolados ou apenas na
memória. Falta uma base única e confiável para análises reais (alocação de
tempo, histórico de projetos, gestão de relacionamento).

## Solução

Um sistema proprietário com **alta governança de dados**. O objetivo não é
automatizar tudo, e sim manter um banco **limpo e confiável** — curado por um
humano — que sirva de base para cruzamentos e análises.

## Stack

- **Ingestão:** Plaud (via MCP) — transcrição, tópicos e título por IA.
- **Control Tower (frontend):** Streamlit — filas de entrada e validação.
- **Backend:** Supabase (PostgreSQL).
- **V2:** API do Jira para enriquecer status de projetos.

## Princípios

- **Governança > automação:** cadastro de pessoas/projetos é manual e curado.
- **Human-in-the-loop:** nada entra no banco sem revisão.
- **IA secundária na V1:** usa-se só o que o Plaud já entrega; sem LLM extra.

## Documentação

- [**Visão & Escopo**](docs/visao-e-escopo.md) — documento canônico do projeto.
