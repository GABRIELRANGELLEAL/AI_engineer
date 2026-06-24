# Especificação Completa — Sistema RAG para Q&A sobre PDFs

## Contexto

Construir um sistema que permite usuários fazerem upload de documentos PDF e depois fazerem perguntas sobre o conteúdo. O sistema deve extrair informações dos documentos, armazená-las para busca eficiente via embeddings, e usar um LLM para responder perguntas com precisão.

Este é um case técnico avaliado nos critérios: Functionality, Retrieval, LLM Use, Code Quality, API Design e Developer UX.

---

## Stack Tecnológica

| Componente | Tecnologia | Justificativa |
|---|---|---|
| Framework Web | FastAPI | Async nativo, tipagem Pydantic, docs Swagger automáticas, suporta multipart/form-data e JSON nativamente |
| Extração de PDF | PyMuPDF (fitz) | Implementado em C (rápido), preserva ordem de leitura, metadata por página (número, dimensões) |
| Chunking | Implementação própria | Chunking semântico: respeita fronteiras de parágrafo/seção, com fallback para quebra por tamanho + overlap |
| Embeddings | OpenAI text-embedding-3-small (primário), sentence-transformers all-MiniLM-L6-v2 (fallback local) | Interface abstrata permite trocar provedor sem mudar código |
| Vector Store | ChromaDB | Roda in-process, persiste em disco, armazena metadata junto dos vetores, sem infra externa |
| LLM | OpenAI gpt-4o-mini (primário), Anthropic Claude Sonnet (fallback) | Fallback automático em caso de erro 429/500 |
| Frontend | React + Tailwind CSS | Servido como estático pelo FastAPI, sem servidor separado |
| Infra | Docker + Docker Compose + Makefile | Setup em um comando, experiência do avaliador otimizada |

---

## Arquitetura de Módulos

```
project-root/
├── backend/
│   ├── app/
│   │   ├── main.py                  ← entry point FastAPI, monta rotas e serve frontend estático
│   │   ├── config.py                ← settings via pydantic-settings + variáveis de ambiente
│   │   ├── api/
│   │   │   ├── routes/
│   │   │   │   ├── documents.py     ← POST /documents (upload e indexação de PDFs)
│   │   │   │   ├── question.py      ← POST /question (pergunta e resposta)
│   │   │   │   ├── keys.py          ← POST /validate-keys (validação de API keys)
│   │   │   │   └── stats.py         ← GET /stats (métricas agregadas)
│   │   │   └── dependencies.py      ← injeção de dependências (providers, store)
│   │   ├── core/
│   │   │   ├── extraction.py        ← lê PDFs com PyMuPDF, retorna texto + metadata por página
│   │   │   ├── chunking.py          ← chunking semântico com fallback para tamanho + overlap
│   │   │   ├── embedding.py         ← interface abstrata + implementações OpenAI e sentence-transformers
│   │   │   ├── retrieval.py         ← busca no vector store, retorna top-k chunks rankeados
│   │   │   └── llm.py               ← interface abstrata + implementações OpenAI e Anthropic + fallback
│   │   └── store/
│   │       └── vector_store.py      ← wrapper do ChromaDB (indexação, busca, listagem)
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── App.jsx                  ← roteamento interno entre telas (estado, não React Router)
│   │   ├── pages/
│   │   │   ├── SetupPage.jsx        ← tela de configuração de API keys
│   │   │   └── MainPage.jsx         ← tela principal (upload + chat)
│   │   ├── components/
│   │   │   ├── KeyInput.jsx         ← campo de API key com botão testar e feedback visual
│   │   │   ├── FileUpload.jsx       ← área de drag-and-drop para PDFs com progresso
│   │   │   ├── DocumentList.jsx     ← lista de documentos indexados (sidebar)
│   │   │   ├── ChatWindow.jsx       ← histórico de perguntas e respostas
│   │   │   ├── ChatInput.jsx        ← campo de texto + botão enviar
│   │   │   └── References.jsx       ← cards colapsáveis com trechos de referência
│   │   └── index.css                ← Tailwind imports
│   ├── package.json
│   └── tailwind.config.js
├── Dockerfile
├── docker-compose.yml
├── Makefile
├── .env.example
├── .gitignore
└── README.md
```

---

## API Specification

### POST /validate-keys

Valida as API keys informadas pelo usuário. Tenta uma chamada mínima a cada API (listar modelos ou chamada de teste).

**Request:**
```json
{
  "openai_key": "sk-...",
  "anthropic_key": "sk-ant-..."
}
```
- `openai_key`: obrigatória (usada para embeddings + LLM primário)
- `anthropic_key`: opcional (usada como fallback de LLM)

**Response:**
```json
{
  "openai": { "valid": true, "message": "Conectado com sucesso" },
  "anthropic": { "valid": true, "message": "Conectado com sucesso" }
}
```

Em caso de falha:
```json
{
  "openai": { "valid": false, "message": "API key inválida ou sem permissão" },
  "anthropic": { "valid": false, "message": "Não fornecida" }
}
```

### POST /documents

Upload e indexação de PDFs.

**Request:**
- Content-Type: multipart/form-data
- Body: um ou mais PDFs no campo `files`
- Headers: `X-OpenAI-Key: sk-...`

**Response:**
```json
{
  "message": "Documents processed successfully",
  "documents_indexed": 2,
  "total_chunks": 128,
  "details": [
    {
      "filename": "manual_motor.pdf",
      "pages": 15,
      "chunks": 72,
      "processing_time_ms": 3400
    },
    {
      "filename": "especificacoes.pdf",
      "pages": 8,
      "chunks": 56,
      "processing_time_ms": 2100
    }
  ]
}
```

### POST /question

Faz uma pergunta sobre os documentos indexados.

**Request:**
```json
{
  "question": "What is the power consumption of the motor?"
}
```
- Headers: `X-OpenAI-Key: sk-...`, `X-Anthropic-Key: sk-ant-...` (opcional)

**Response:**
```json
{
  "answer": "The motor's power consumption is 2.3 kW.",
  "references": [
    {
      "text": "the motor xxx has requires 2.3kw to operate at a 60hz line frequency",
      "document": "manual_motor.pdf",
      "page": 3,
      "similarity_score": 0.92
    }
  ],
  "metadata": {
    "provider_used": "openai",
    "model": "gpt-4o-mini",
    "retrieval_time_ms": 45,
    "llm_time_ms": 1230,
    "total_time_ms": 1320,
    "confidence": "high"
  }
}
```

### GET /stats

Métricas agregadas do sistema.

**Response:**
```json
{
  "documents_indexed": 5,
  "total_chunks": 312,
  "questions_answered": 23,
  "average_latency_ms": 1450,
  "provider_usage": {
    "openai": 21,
    "anthropic": 2
  }
}
```

### GET /health

Healthcheck para Docker.

**Response:**
```json
{
  "status": "healthy"
}
```

---

## Implementação Detalhada por Módulo

### extraction.py

- Usar PyMuPDF (fitz) para extrair texto de cada página do PDF
- Retornar uma lista de objetos com: `page_number`, `text`, `filename`
- Limpar o texto: normalizar espaços, remover headers/footers repetidos se detectados
- Tratar PDFs sem texto extraível (escaneados) retornando aviso ao usuário

### chunking.py

- Implementar chunking semântico com a seguinte hierarquia de separação:
  1. Primeiro tentar quebrar por `\n\n` (parágrafos/seções)
  2. Depois por `\n` (quebras de linha)
  3. Depois por `. ` (sentenças)
  4. Por último por caractere (último recurso)
- Parâmetros configuráveis via config: `CHUNK_SIZE=512` tokens, `CHUNK_OVERLAP=50` tokens
- Se um parágrafo for menor que um mínimo (ex: 50 tokens), agrupar com o próximo
- Cada chunk deve carregar metadata: `filename`, `page_number`, `chunk_index`, `text`
- Implementar sem dependência do LangChain — código próprio mostra mais entendimento

### embedding.py

- Interface abstrata `EmbeddingProvider` com método `embed(texts: list[str]) -> list[list[float]]`
- Implementação `OpenAIEmbeddingProvider`: usa `text-embedding-3-small`, vetores de 1536 dimensões
- Implementação `LocalEmbeddingProvider`: usa `sentence-transformers/all-MiniLM-L6-v2`, vetores de 384 dimensões
- O provider é escolhido com base na disponibilidade de API key
- Processar embeddings em batch para eficiência (a API da OpenAI aceita listas de textos)

### vector_store.py

- Wrapper sobre ChromaDB com métodos:
  - `add_documents(chunks: list[Chunk], embeddings: list[list[float]])` — indexa chunks com metadata
  - `search(query_embedding: list[float], top_k: int = 5) -> list[SearchResult]` — busca por similaridade coseno
  - `list_documents() -> list[str]` — lista documentos indexados
  - `get_stats() -> dict` — retorna contagens e métricas
- Persistir dados em disco (diretório configurável, default `/app/data/chromadb`)
- Armazenar junto de cada embedding: texto do chunk, filename, page_number, chunk_index

### retrieval.py

- Recebe a pergunta em texto, gera o embedding usando o provider configurado
- Consulta o vector store pedindo top-k resultados (k configurável, default 5)
- Retorna lista de chunks rankeados por score de similaridade, incluindo metadata
- Logar: tempo de geração do embedding, tempo de busca, scores dos top-k

### llm.py

- Interface abstrata `LLMProvider` com método `generate(system_prompt: str, user_prompt: str) -> str`
- Implementação `OpenAILLMProvider`: usa `gpt-4o-mini`
- Implementação `AnthropicLLMProvider`: usa Claude Sonnet
- Classe `LLMWithFallback`: tenta o provider primário (OpenAI), se falhar com erro 429/500/timeout, tenta o secundário (Anthropic). Loga qual provider foi usado.
- System prompt para o LLM:

```
Você é um assistente que responde perguntas baseado exclusivamente nos trechos de documentos fornecidos abaixo.

Regras:
- Responda APENAS com informações presentes nos trechos fornecidos
- Ao final da resposta, liste os números dos trechos que você utilizou
- Se a informação não estiver nos trechos, diga explicitamente que não encontrou informação suficiente nos documentos disponíveis
- Seja direto e preciso
- Responda no mesmo idioma da pergunta

Trechos:
{chunks numerados com fonte e página}

Pergunta: {question}
```

- Parsear a resposta do LLM para extrair quais trechos foram referenciados e montar o array `references`

---

## Frontend — Duas Telas

### Tela 1: Setup (SetupPage)

**Layout:** centralizado na tela, card com formulário

**Elementos:**
- Título: nome do projeto e breve descrição ("Sistema de Q&A sobre documentos PDF")
- Campo de input para OpenAI API Key, com label "OpenAI API Key (obrigatória)" e ícone de cadeado
  - Tipo password (oculta o valor)
  - Botão "Testar" ao lado
  - Feedback visual: spinner enquanto testa, check verde se válida, X vermelho com mensagem se inválida
  - Abaixo do campo, texto discreto: "Usada para embeddings (text-embedding-3-small) e respostas (gpt-4o-mini)"
- Campo de input para Anthropic API Key, com label "Anthropic API Key (opcional — fallback)"
  - Mesmo padrão de teste e feedback
  - Texto discreto: "Usada como fallback para respostas (Claude Sonnet)"
- Botão "Começar" no final
  - Desabilitado até que a OpenAI key esteja validada com sucesso
  - Habilitado assim que a OpenAI key for validada (Anthropic é opcional)

**Comportamento:**
- As keys são armazenadas apenas no estado do React (memória do browser, não localStorage)
- Enviadas via headers em cada request subsequente
- Nunca persistidas no backend

### Tela 2: Principal (MainPage)

**Layout:** sidebar esquerda (largura fixa ~300px) + área principal à direita

**Sidebar esquerda:**
- Área de upload de PDFs no topo
  - Drag-and-drop ou clique para selecionar
  - Aceita múltiplos arquivos
  - Ao fazer upload, mostra progresso por etapa: "Extraindo texto... Gerando chunks... Criando embeddings... Pronto!"
  - Após indexação, mostra resumo: "manual.pdf — 15 páginas, 72 chunks"
- Lista de documentos indexados abaixo
  - Cada documento com nome, número de páginas, número de chunks
  - Indicador visual de que está indexado

**Área principal (chat):**
- Histórico de perguntas e respostas, estilo chat
- Cada resposta do sistema contém:
  - Texto da resposta (destaque principal)
  - Indicador de confiança baseado no similarity score: "Alta confiança" (score > 0.8), "Média confiança" (0.6-0.8), "Baixa confiança" (< 0.6)
  - Indicação de qual provider/modelo gerou a resposta
  - Cards colapsáveis de referências, cada um mostrando: trecho do texto, nome do documento, número da página, score de similaridade
  - Tempo de resposta discreto (ex: "1.3s")
- Campo de input na parte inferior com botão de enviar
- Loading state enquanto processa (spinner ou skeleton)
- Se nenhum documento estiver indexado, mostrar mensagem orientando o upload

---

## Infraestrutura

### .env.example (commitado no repo)
```
OPENAI_API_KEY=sk-your-key-here
ANTHROPIC_API_KEY=sk-ant-your-key-here
EMBEDDING_MODEL=text-embedding-3-small
LLM_MODEL=gpt-4o-mini
CHUNK_SIZE=512
CHUNK_OVERLAP=50
TOP_K=5
LOG_LEVEL=INFO
```

### Dockerfile
- Base: `python:3.12-slim`
- Instalar dependências de sistema para PyMuPDF em camada separada
- Copiar `requirements.txt` primeiro, rodar `pip install` (cache de dependências)
- Copiar frontend buildado para pasta `static/`
- Copiar código backend
- Criar usuário não-root para rodar a aplicação
- Expor porta 8000
- CMD: `uvicorn app.main:app --host 0.0.0.0 --port 8000`

### docker-compose.yml
```yaml
services:
  api:
    build: .
    ports:
      - "8000:8000"
    volumes:
      - chroma_data:/app/data
    env_file:
      - .env
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3

volumes:
  chroma_data:
```

### Makefile
```makefile
setup:          copia .env.example para .env
build-frontend: builda o React para static/
run:            docker-compose up --build
dev:            roda backend e frontend em modo dev
test:           roda testes com pytest
down:           docker-compose down
clean:          remove volumes e dados persistidos
```

---

## Logging

- Usar `structlog` ou `logging` padrão com formato estruturado
- Logar cada etapa do pipeline com tempo:
  - Upload: `INFO | action=extract | file=manual.pdf | pages=15 | time_ms=450`
  - Chunking: `INFO | action=chunk | file=manual.pdf | chunks=72 | time_ms=120`
  - Embedding: `INFO | action=embed | chunks=72 | time_ms=800`
  - Retrieval: `INFO | action=retrieve | question="consumo do motor" | top_score=0.92 | time_ms=45`
  - LLM: `INFO | action=llm_call | provider=openai | model=gpt-4o-mini | tokens=580 | time_ms=1230`
  - Total: `INFO | action=question_answered | total_ms=1320`

---

## Testes

- Testes unitários para:
  - `chunking.py`: verificar que respeita fronteiras de parágrafo, que overlap funciona, que chunks pequenos são agrupados
  - `extraction.py`: verificar extração de PDF simples, PDF com múltiplas páginas
  - `retrieval.py`: com mocks do vector store e embedding provider
  - Endpoints da API: com TestClient do FastAPI, mocks dos providers
- Não testar chamadas reais a APIs externas nos testes unitários — usar mocks

---

## README.md

Deve conter:
1. **Título e descrição** breve do projeto
2. **Diagrama de arquitetura** (Mermaid ou ASCII) mostrando o fluxo: PDF → Extração → Chunking → Embedding → ChromaDB → Retrieval → LLM → Resposta
3. **Setup rápido** em 3 passos: clone, configure `.env`, `make run`
4. **Exemplos de uso** com curl mostrando: upload de documento, pergunta com resposta existente, pergunta sem resposta nos documentos
5. **Decisões técnicas** explicando a escolha de cada componente e por quê
6. **Limitações e próximos passos**: o que faria com mais tempo (re-ranking, OCR para PDFs escaneados, cache de respostas, autenticação, rate limiting)

---

## Fluxo Completo do Usuário

1. Abre `localhost:8000` no browser
2. Tela de setup aparece → cola OpenAI key → clica "Testar" → check verde aparece
3. Opcionalmente cola Anthropic key → clica "Testar" → check verde
4. Botão "Começar" fica habilitado → clica → transição para tela principal
5. Na sidebar, arrasta 2 PDFs → vê progresso etapa por etapa → "128 chunks indexados"
6. No chat, digita "Qual o consumo de energia do motor?"
7. Vê loading → resposta aparece com texto, indicador de confiança alta, referências colapsáveis mostrando trecho, documento e página
8. Continua fazendo perguntas
9. Faz pergunta sobre algo que não está nos documentos → sistema responde que não encontrou informação suficiente
