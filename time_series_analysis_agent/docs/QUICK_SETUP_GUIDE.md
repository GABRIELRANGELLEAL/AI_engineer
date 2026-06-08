# Quick Setup & Testing Guide

Guia rápido para rodar a aplicação com o novo sistema de analytics UI.

## Setup

### 1. Backend

```bash
cd time_series_analysis_agent

# Instalar dependências (se ainda não instalou)
pip install -r requirements.txt

# Verificar variáveis de ambiente
cat .env
# Deve conter:
# ANTHROPIC_API_KEY=your_key
# DATABASE_URL=postgresql://...

# Rodar servidor
python main.py
# Server em http://localhost:8000
```

### 2. Frontend

```bash
cd frontend

# Instalar dependências (inclui plotly.js agora)
npm install

# Rodar dev server
npm run dev
# Frontend em http://localhost:3000
```

---

## Teste Completo (End-to-End)

### 1. Upload CSV

1. Abrir http://localhost:3000
2. Escolher "CSV Upload"
3. Fazer upload de um CSV com colunas `date` e `value`
4. Ex: `sales_data.csv`:
   ```csv
   date,value
   2023-01-01,150
   2023-01-02,155
   2023-01-03,148
   ...
   ```

### 2. Planning

1. Digitar prompt:
   ```
   Analyze this sales time series data. I want to understand trends, 
   seasonality, and create forecasts for the next 30 days.
   ```
2. Planner vai:
   - Explorar o CSV (view_file)
   - Criar plano de 5-7 steps
3. Revisar plano no painel direito
4. Clicar **"Approve Plan"**

### 3. Execution

1. Após aprovar, aparece botão **"Start Execution"** → clicar
2. Backend chama helper_contet_agent (enriquece com skills)
3. Aparece **"Execute Step 1"** → clicar
4. Step 1 executa:
   - LLM roda Python
   - Gera `analysis_results_1_ui.json`
   - API responde
5. Frontend:
   - Busca ui.json
   - Renderiza div com texto + tabela + plot
6. Clicar **"Execute Step 2"**
7. Repetir até completar todos os steps

### 4. Verificar Resultados

Cada step deve mostrar:
- ✅ Status completed
- 📝 Texto narrativo (em português)
- 📊 Tabela com métricas
- 📈 Gráfico Plotly interativo

---

## Exemplo de Step 2 (Expected Output)

**Step 2: Exploratory Analysis**

**Texto:**
> A série temporal possui 365 observações diárias de 2023-01-01 a 2023-12-31. 
> A média é 152.3 com desvio padrão de 45.6, indicando variabilidade moderada.

**Tabela:**
| Métrica | Valor |
|---------|-------|
| Observações | 365 |
| Média | 152.3 |
| Desvio Padrão | 45.6 |

**Plot:**
- Gráfico de linha interativo (Plotly)
- Hover mostra valores
- Zoom/pan funcionando

---

## Verificar Arquivos Gerados

```bash
# Backend workspace
ls workspace/outputs/{task_id}/step_1/
# Deve ter: analysis_results_1_ui.json

cat workspace/outputs/{task_id}/step_1/analysis_results_1_ui.json
# JSON estruturado com blocks
```

---

## Debugging

### Backend não gera ui.json

**Check:**
```python
# Ver logs do executor
# Deve aparecer: "UI OUTPUT (REQUIRED for analytics steps)"
```

**Solução:**
- Verificar que step tem `skill_needed: true`
- Ver prompt no terminal (deve incluir instrução UI)

### Frontend não mostra plot

**Check console do browser:**
```
Failed to load UI payload: ...
```

**Solução:**
- Verificar que endpoint `/api/workspace/files/...` responde 200
- Ver Network tab → GET request deve retornar JSON válido

### Plot Plotly com erro

**Erro comum:**
```
Error: Invalid data format
```

**Solução:**
- Verificar que `spec.data` é array
- Verificar que `spec.layout` é objeto
- No Python: usar `json.loads(fig.to_json())`

---

## Test Checklist

- [ ] CSV upload funcionando
- [ ] Planner cria plano com 5+ steps
- [ ] Botão "Approve Plan" muda status para `proceeded`
- [ ] Botão "Start Execution" aparece
- [ ] Backend chama helper_contet_agent (ver logs)
- [ ] Botão "Execute Step 1" aparece
- [ ] Step 1 completa e gera ui.json
- [ ] Frontend busca ui.json via GET /workspace/files/...
- [ ] Div Step 1 renderiza com texto + tabela + plot
- [ ] Botão "Execute Step 2" aparece
- [ ] Todos os steps completam
- [ ] Status final = `completed`

---

## Performance Notes

| Operação | Tempo esperado |
|----------|----------------|
| Upload CSV | < 1s |
| Planning (primeira rodada) | 5-15s |
| Start execution | 2-5s (helper_contet_agent) |
| Execute step (simples) | 10-30s |
| Execute step (com análise) | 30-60s |
| Fetch ui.json | < 1s |
| Render Plotly | < 2s |

---

## Next Steps (After Testing)

1. **Melhorar prompts** dos steps para gerar plots mais úteis
2. **Adicionar mais skills** (forecasting, anomaly detection)
3. **Implementar regeneração de step** (botão "Regenerate")
4. **Download de plots** individuais (PNG export)
5. **Comparação de steps** side-by-side

---

## Troubleshooting Rápido

| Problema | Solução |
|----------|---------|
| 500 error no /execute/step | Ver logs backend, verificar SKILL.md existe |
| Plot não interativo | Verificar versão plotly.js >= 2.27 |
| Tabela vazia | Verificar que rows é array de arrays |
| Texto muito grande | LLM pode truncar — limitar a ~500 chars |
| Step demora muito | Timeout 60s — simplificar análise |

---

## Support

Se encontrar problemas:
1. Ver logs do backend (terminal Python)
2. Ver console do browser (F12)
3. Ver Network tab → requisições falhando
4. Ver PostgreSQL logs (llm_interactions table)

**Happy analyzing! 📊🚀**
