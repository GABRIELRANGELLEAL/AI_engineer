# Especificação técnica — Assistente Jurídico com IA

## 1. Visão geral

Sistema que monitora processos jurídicos em portais externos (eProc, PJe etc.), identifica publicações novas, usa IA para determinar se uma ação é necessária, organiza prazos e tarefas na agenda do advogado, e gera esboços de peças com base em exemplos passados. O advogado mantém controle total via dois checkpoints de confirmação.

Desenvolvedor: solo. Prioridade: equilíbrio entre velocidade de desenvolvimento e controle do código.

---

## 2. Stack tecnológica

| Camada | Tecnologia | Motivo |
| --- | --- | --- |
| Backend | Python + FastAPI | Ecossistema maduro para LLM, async nativo |
| Fila de tarefas | Celery + Redis | Scraping e chamadas de IA são assíncronos por natureza, precisam de retry |
| Banco de dados | PostgreSQL + pgvector | Relacional para dados estruturados, vetorial no mesmo banco para RAG |
| ORM / migrations | SQLAlchemy + Alembic | Padrão de mercado, integra bem com FastAPI |
| LLM | API Anthropic (Claude) | Chamadas diretas via SDK, sem abstração |
| RAG | LangChain (apenas para indexação/busca) | Resolve chunking e embeddings sem reinventar a roda |
| Scraping | Playwright | Lida com portais autenticados, JS pesado, certificado digital |
| Agenda | Google Calendar API | Integração direta via OAuth |
| Frontend | Next.js | Interface de validação e acompanhamento |

Decisão central: o pipeline de orquestração e os prompts são escritos em Python puro, sem frameworks de agentes. LangChain é usado apenas como utilitário isolado para o RAG (chunking, embeddings, busca por similaridade).

---

## 3. Modelo de dados (PostgreSQL)

### Tabelas principais

**processos**

- id, numero_processo, tribunal, advogado_id, ativo, created_at

**publicacoes**

- id, processo_id, conteudo_raw, data_publicacao, status (nova / analisada / confirmada / descartada), created_at

**analises**

- id, publicacao_id, requer_acao (bool), justificativa, exemplos_rag_usados (jsonb), confirmado_advogado (bool), created_at

**tarefas**

- id, analise_id, descricao, prazo_tipo (solicitação / fup / revisão / protocolo), data_limite, evento_google_calendar_id, confirmado_advogado (bool)

**esbocos**

- id, tarefa_id, conteudo, versao (1/2/3), escolhido (bool), editado_pelo_advogado (bool)

**banco_exemplos** (com coluna vetorial via pgvector)

- id, tipo (analise / peca), conteudo, embedding (vector), metadata (jsonb), origem_esboco_id (nullable, para feedback loop)

### Relação de feedback

Toda peça protocolada (confirmada pelo advogado) deve gerar uma nova entrada em `banco_exemplos`, alimentando o RAG automaticamente. Esse é o mecanismo que faz o sistema melhorar com o uso.

---

## 4. Pipeline de processamento

### Etapa 1 — Captura

Job periódico (Celery beat) por advogado/processo: Playwright acessa o portal, autentica, verifica publicações novas, salva em `publicacoes` com status `nova`.

### Etapa 2 — Análise de necessidade de ação

- Busca no `banco_exemplos` (tipo `analise`) por publicações similares via embeddings
- Prompt ao Claude: conteúdo da publicação + exemplos recuperados → decide `requer_acao` e justificativa
- Salva em `analises`, status muda para `analisada`
- Notifica advogado (Checkpoint 1)

### Etapa 3 — Checkpoint 1 (confirmação do advogado)

- Advogado confirma ou descarta via notificação/app
- Se confirmado → avança; se descartado → publicação arquivada, opcionalmente vira exemplo negativo no RAG

### Etapa 4 — Extração de prazos e tarefas

- Novo prompt ao Claude usando a análise confirmada
- Gera lista de tarefas com tipo de prazo (solicitação, fup, revisão, protocolo) e datas
- Salva em `tarefas`

### Etapa 5 — Checkpoint 2 (validação de prazos)

- Advogado revisa e ajusta datas/descrições
- Após confirmação → cria eventos no Google Calendar via API

### Etapa 6 — Geração de esboços

- Busca no `banco_exemplos` (tipo `peca`) por peças similares
- Prompt ao Claude gera três versões de esboço
- Salva em `esbocos`, advogado escolhe/edita uma
- Esboço final, se protocolado, retorna ao `banco_exemplos` como novo exemplo

---

## 5. Ordem de implementação recomendada

### Fase 1 — Fundação

1. Schema do banco (modelos SQLAlchemy + migrations Alembic)
2. Scraper Playwright para um portal (eProc), salvando publicações reais

### Fase 2 — RAG

1. Script de indexação inicial do `banco_exemplos` (peças e análises existentes)
2. Função de busca por similaridade, testável isoladamente

### Fase 3 — Prompts de IA

1. Prompt de análise (requer ação?)
2. Prompt de extração de prazos/tarefas
3. Prompt de geração de esboços

Cada prompt deve ser testado com publicações reais do banco antes de seguir.

### Fase 4 — Orquestração

1. Configuração Celery + Redis, conectando as etapas 1-6
2. Lógica dos checkpoints (pausa/retomada aguardando resposta)
3. Integração Google Calendar

### Fase 5 — Interface

1. API REST (FastAPI) expondo publicações pendentes, análises, esboços
2. Frontend Next.js para os dois checkpoints e edição de esboços

---

## 6. Riscos e pontos de atenção

**Scraping de portais jurídicos**: layouts mudam com frequência, exigem certificado digital e podem ter CAPTCHA. Esperar manutenção recorrente; isolar essa camada para que mudanças não afetem o resto do sistema.

**Erros em prazos**: o Checkpoint 2 é o ponto crítico do sistema. Nenhum evento deve ir para a agenda sem confirmação explícita.

**Rastreabilidade**: cada decisão de IA deve registrar quais exemplos do RAG foram usados e qual prompt/versão gerou o resultado, para depuração e auditoria.

**Qualidade do banco de exemplos**: a precisão do sistema depende diretamente da qualidade e volume de exemplos indexados. Priorizar a indexação inicial com casos reais e variados.