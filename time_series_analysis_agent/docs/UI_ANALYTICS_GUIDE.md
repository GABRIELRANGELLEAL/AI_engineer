# UI Analytics Integration - Complete Guide

Sistema de visualização step-by-step para análise de séries temporais com texto narrativo + plots interativos.

## Visão Geral

Cada step analítico gera um arquivo `ui.json` estruturado que o frontend renderiza dinamicamente com:
- **Blocos de texto** — narrativa explicando os achados
- **Tabelas** — métricas e estatísticas
- **Plots interativos** — gráficos Plotly que o usuário pode explorar

---

## Fluxo Completo

```
1. User aprova plano → POST /proceed
2. User inicia execução → POST /execute/start
3. Para cada step:
   a. User clica "Execute Step N"
   b. POST /execute/step { step_number: N }
   c. Backend: executor_agent roda
   d. LLM via run_python gera ui.json
   e. API responde com paths dos arquivos
   f. Frontend busca ui.json → GET /workspace/files/...
   g. Frontend renderiza UIBlock por cada block
   h. Resultado: Div com Texto + Tabela + Gráfico Plotly
```

---

## Backend: Schema do ui.json

O executor instrui o modelo a criar:

```json
{
  "step_number": 2,
  "title": "Exploratory Analysis Results",
  "blocks": [
    {
      "type": "text",
      "content": "O dataset contém 1.000 observações com média de 152.3..."
    },
    {
      "type": "table",
      "title": "Summary Statistics",
      "columns": ["Metric", "Value"],
      "rows": [
        ["Mean", "152.3"],
        ["Std Dev", "45.6"]
      ]
    },
    {
      "type": "plot",
      "title": "Distribution",
      "library": "plotly",
      "spec": {
        "data": [
          {
            "type": "histogram",
            "x": [valores...],
            "name": "Distribution"
          }
        ],
        "layout": {
          "title": "Value Distribution",
          "xaxis": {"title": "Sales"},
          "yaxis": {"title": "Frequency"}
        }
      }
    }
  ]
}
```

### Tipos de Blocos

| Tipo | Descrição | Uso |
|------|-----------|-----|
| `text` | Narrativa em português | Explicações, insights, contexto |
| `table` | Tabela HTML | Estatísticas, métricas, comparações |
| `plot` | Gráfico Plotly | Visualizações interativas (zoom, hover, pan) |

---

## Backend: Prompt do Executor

O prompt no `prepare_step_prompt()` instrui explicitamente:

```
UI OUTPUT (REQUIRED for analytics steps):
For any step involving analysis, create:
  Filename: {output_name}_{step_number}_ui.json

Structure: {...}

PLOTLY EXAMPLES:
- Line chart: {"type": "scatter", "mode": "lines", "x": [...], "y": [...]}
- Histogram: {"type": "histogram", "x": [...]}
- Box plot: {"type": "box", "y": [...]}

HOW TO GENERATE:
Use run_python to:
1. Perform calculations
2. Build UI JSON with text + tables + plots
3. Save with write_file
```

Isso garante que o LLM saiba exatamente o formato esperado.

---

## Backend: Geração via Python

O modelo roda código como este (via `run_python`):

```python
import pandas as pd
import plotly.graph_objects as go
import json

# Load data
df = pd.read_csv("outputs/task-id/step_1/data.csv")

# Calculate stats
mean = df['value'].mean()
std = df['value'].std()

# Create plot
fig = go.Figure()
fig.add_trace(go.Scatter(
    x=df['date'], 
    y=df['value'], 
    mode='lines', 
    name='Sales'
))
fig.update_layout(
    title="Time Series",
    xaxis_title="Date",
    yaxis_title="Sales"
)

# Build UI JSON
ui = {
    "step_number": 2,
    "title": "Exploratory Analysis",
    "blocks": [
        {
            "type": "text",
            "content": f"Dataset com {len(df)} obs. Média: {mean:.2f}, Desvio: {std:.2f}"
        },
        {
            "type": "table",
            "title": "Stats",
            "columns": ["Metric", "Value"],
            "rows": [["Mean", f"{mean:.2f}"], ["Std", f"{std:.2f}"]]
        },
        {
            "type": "plot",
            "title": "Series",
            "library": "plotly",
            "spec": json.loads(fig.to_json())
        }
    ]
}

# Save
with open("analysis_results_2_ui.json", "w") as f:
    json.dump(ui, f)
```

O executor salva isso em `workspace/outputs/{task_id}/step_2/`.

---

## Backend: Endpoint de Arquivos

`GET /workspace/files/{path}` serve o ui.json:

```http
GET /api/workspace/files/outputs/task-123/step_2/analysis_results_2_ui.json

Response: 200 OK
Content-Type: application/json
{
  "step_number": 2,
  "title": "...",
  "blocks": [...]
}
```

Segurança:
- Valida que path não contém `..`
- Resolve path absoluto
- Confirma que está dentro de workspace

---

## Frontend: Componentes

### 1. UIBlock.tsx

Renderiza um único bloco baseado no tipo:

```tsx
<UIBlock block={block} />

// Se type === 'text' → <p>
// Se type === 'table' → <table>
// Se type === 'plot' → <Plot> (react-plotly.js)
```

### 2. StepResultPanel.tsx

Panel de um step completo:

```tsx
<StepResultPanel stepResult={result} taskId={taskId} />

// Internamente:
// - Busca ui.json via fetch()
// - Renderiza UIBlock para cada block
// - Mostra loading / error states
```

### 3. ExecutionPanel.tsx

Gerencia a execução step-by-step:

```tsx
<ExecutionPanel taskId={taskId} taskStatus={status} />

// - Botão "Start Execution"
// - Progress bar
// - Botão "Execute Step N"
// - Lista de StepResultPanel para steps completos
```

### 4. ResultsPanel.tsx

Painel principal que integra tudo:

```tsx
<ResultsPanel plan={plan} taskId={taskId} taskStatus={status} />

// - Mostra plano
// - Botão "Approve Plan"
// - Renderiza ExecutionPanel quando proceeded
```

---

## Instalação

### Backend (já feito)
```bash
# Nenhuma nova dependência — usa plotly via Python no run_python
```

### Frontend
```bash
cd frontend
npm install
# Instala plotly.js e react-plotly.js (já adicionado ao package.json)
```

---

## Uso na Prática

### 1. Usuario faz upload de CSV

```
POST /uploads/csv
```

### 2. Planner cria plano

```
POST /tasks
POST /tasks/{id}/messages (refinar)
```

### 3. Aprovar plano

```
POST /tasks/{id}/proceed
```

### 4. Iniciar execução

Frontend chama:
```typescript
await startExecution(taskId, 'analysis_results');
```

Backend:
- Chama helper_contet_agent (enriquece steps com skills)
- Salva execution_state
- Status → `executing`

### 5. Executar cada step

Frontend loop:
```typescript
for (let step = 1; step <= totalSteps; step++) {
  // User clica "Execute Step"
  const result = await executeStep(taskId, step);
  
  // result.execution_result contém:
  // - summary (texto rápido)
  // - generated_files: ["analysis_results_2_ui.json"]
  
  // StepResultPanel automaticamente:
  // 1. Detecta ui.json em generated_files
  // 2. Faz GET /workspace/files/...
  // 3. Renderiza blocks
}
```

### 6. Resultado visual

Div do Step 2:
```
┌─────────────────────────────────────┐
│ Step 2 ✓                            │
│ Exploratory Analysis                │
├─────────────────────────────────────┤
│ O dataset contém 1.000 observações  │
│ com média de 152.3 e desvio...      │
│                                     │
│ Summary Statistics                  │
│ ┌─────────┬────────┐                │
│ │ Metric  │ Value  │                │
│ ├─────────┼────────┤                │
│ │ Mean    │ 152.3  │                │
│ │ Std Dev │ 45.6   │                │
│ └─────────┴────────┘                │
│                                     │
│ Distribution                        │
│ [Gráfico Plotly interativo]         │
│                                     │
└─────────────────────────────────────┘
```

---

## Benefícios

| Antes | Depois |
|-------|--------|
| Summary text genérico | Narrativa estruturada por bloco |
| PNG estático | Plotly interativo (zoom, hover, download) |
| Dados separados do texto | Tudo integrado em uma div |
| User download manual | Visualização in-app automática |

---

## Exemplo de Step Completo

**Step 2: Exploratory Analysis**

LLM gera via `run_python`:
```json
{
  "step_number": 2,
  "title": "Análise Exploratória",
  "blocks": [
    {
      "type": "text",
      "content": "A série temporal possui 365 observações diárias de 2023-01-01 a 2023-12-31. A média é 152.3 com desvio padrão de 45.6, indicando variabilidade moderada."
    },
    {
      "type": "table",
      "title": "Estatísticas Descritivas",
      "columns": ["Métrica", "Valor"],
      "rows": [
        ["Observações", "365"],
        ["Média", "152.3"],
        ["Mediana", "148.7"],
        ["Desvio Padrão", "45.6"],
        ["Mínimo", "45.2"],
        ["Máximo", "289.1"]
      ]
    },
    {
      "type": "plot",
      "title": "Série Temporal",
      "library": "plotly",
      "spec": {
        "data": [{
          "type": "scatter",
          "mode": "lines",
          "x": ["2023-01-01", "2023-01-02", "..."],
          "y": [150, 155, 148, "..."],
          "name": "Sales"
        }],
        "layout": {
          "title": "Vendas ao Longo do Tempo",
          "xaxis": {"title": "Data"},
          "yaxis": {"title": "Vendas (R$)"}
        }
      }
    },
    {
      "type": "plot",
      "title": "Distribuição dos Valores",
      "library": "plotly",
      "spec": {
        "data": [{
          "type": "histogram",
          "x": [150, 155, 148, "..."],
          "nbinsx": 30
        }],
        "layout": {
          "title": "Histograma",
          "xaxis": {"title": "Vendas (R$)"},
          "yaxis": {"title": "Frequência"}
        }
      }
    }
  ]
}
```

Frontend renderiza automaticamente:
- Parágrafo narrativo
- Tabela 6x2
- 2 gráficos Plotly interativos

---

## Troubleshooting

### LLM não gera ui.json

**Causa:** Prompt não claro ou step sem skill
**Solução:** Verificar que step tem `skill_needed: true` e prompt do executor está atualizado

### Plot não renderiza

**Causa:** Spec Plotly inválido
**Solução:** No Python, usar `json.loads(fig.to_json())` garante formato válido

### Arquivo não encontrado

**Causa:** Path incorreto ou arquivo não salvo
**Solução:** Verificar que `write_file` salvou em `{output_name}_{n}_ui.json`

### Erro CORS

**Causa:** Frontend não proxy correto
**Solução:** Vite config já tem `/api` → backend proxy

---

## Próximos Passos

- [ ] Testar com dados reais
- [ ] Adicionar mais tipos de plot (heatmap, scatter matrix)
- [ ] Suporte a múltiplos plots por bloco
- [ ] Download de plots individuais
- [ ] Comparação side-by-side de steps

---

## Status

✅ Backend endpoint `/workspace/files` implementado
✅ Prompt executor atualizado com instrução ui.json
✅ Componentes React criados (UIBlock, StepResultPanel, ExecutionPanel)
✅ API functions adicionadas (startExecution, executeStep)
✅ Plotly.js instalado no package.json
✅ Integração completa no ResultsPanel

**Pronto para uso!** 🚀
