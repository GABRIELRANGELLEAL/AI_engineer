# Guia de Teste Manual E2E — Analytics Content Agent

> **CSV de referência:** `data/20260506181825722978_DailyDelhiClimateTest.csv`  
> **Pré-requisito:** Docker Desktop em execução; arquivo `.env` com `ANTHROPIC_API_KEY` configurada.

---

## 1. Subir o ambiente

```powershell
cd c:\Users\Leal\AI_Projects\analytics_content_agent
docker compose up --build
```
Voce tmb tem a opção de rodar localmente sem precisar subir a imagem do docker utilizando 

```powershell
conda activate ia_projeto
uvicorn app:app --host 0.0.0.0 --port 8000
```
para rodar o front local, rode em outro terminal:
```powershell
cd frontend
npm run dev
```


| Serviço  | URL                          |
|----------|------------------------------|
| Frontend | http://localhost:3000        |
| Backend  | http://localhost:8000/docs   |

---

## 2. Fluxo completo via Interface Web

### 2.1 Upload do CSV

1. Acesse `http://localhost:3000`.
2. No painel **DataSourcePicker**, clique em **Escolher arquivo**.
3. Selecione `data/20260506181825722978_DailyDelhiClimateTest.csv`.
4. Clique em **Enviar**.

**Resultado esperado:**  
- Mensagem de sucesso (ex: `"filename: 20260506181825722978_DailyDelhiClimateTest.csv"`).  
- O arquivo aparece em `workspace/` no container.

---

### 2.2 Criar sessão

Após o upload, o frontend chama `POST /session` automaticamente (ou clique em **Iniciar sessão**).

**Resultado esperado:**  
- O painel de chat fica habilitado.  
- No console do navegador (F12 → Network), confirme que a resposta de `POST /session` contém:
  ```json
  { "session_id": "<uuid>", "skills": ["analyzing-time-series"] }
  ```

---

### 2.3 Cenário A — Visualizar linhas do CSV

**Mensagem a enviar:**
```
mostre as primeiras 5 linhas do CSV
```

**Eventos SSE esperados (visíveis no DevTools → Network → EventStream):**

| Ordem | Tipo           | O que observar                                 |
|-------|----------------|------------------------------------------------|
| 1     | `text`         | Texto introdutório do agente                   |
| 2     | `tool_call`    | `name: "bash"` ou `name: "view"`; input com path do CSV |
| 3     | *(pausa)*      | Painel **Atividade** exibe botões **Aprovar** / **Negar** |

**Ação:** Clique em **Aprovar**.

| Ordem | Tipo           | O que observar                          |
|-------|----------------|-----------------------------------------|
| 4     | `tool_result`  | Primeiras 5 linhas do CSV no resultado  |
| 5     | `done`         | Chat encerra a resposta                 |

**Validação:** O texto com as linhas do CSV deve aparecer na área de chat.

---

### 2.4 Cenário B — Gerar gráfico de temperatura

**Mensagem a enviar:**
```
gere um gráfico de temperatura ao longo do tempo e salve em outputs/
```

**Eventos esperados:**

1. `tool_call` com `name: "bash"` (script Python/matplotlib) → **Aprovar**
2. `tool_result` com saída do bash
3. Possivelmente outro `tool_call` com `name: "create_file"` → **Aprovar**
4. `done`

**Validação:**  
- O painel **Resultados / Plots** atualiza e exibe o gráfico `.png`.  
- Confirme via `GET /outputs` (Swagger) que o arquivo está listado:
  ```json
  { "files": [{ "filename": "temperatura.png", "url": "/outputs/temperatura.png" }] }
  ```

---

### 2.5 Cenário C — Negar tool call

**Mensagem a enviar:**
```
liste os arquivos do workspace
```

Quando o painel **Atividade** exibir o `tool_call`:

1. Clique em **Negar**.

**Resultado esperado:**  
- Evento `tool_denied` no stream.  
- O agente responde no chat informando que a operação foi cancelada (sem travar ou lançar exceção).

---

## 3. Validação via Swagger (sem frontend)

Abra `http://localhost:8000/docs` e execute os endpoints na ordem abaixo.

### 3.1 `POST /upload-csv`

- Clique em **Try it out**.
- Selecione o arquivo CSV em **file**.
- Execute. Resposta esperada `200`:
  ```json
  { "filename": "20260506181825722978_DailyDelhiClimateTest.csv" }
  ```

### 3.2 `POST /session`

```json
{
  "csv_name": "20260506181825722978_DailyDelhiClimateTest.csv",
  "model": "claude-sonnet-4-5-20250929"
}
```

Resposta esperada `200`:
```json
{ "session_id": "<uuid>", "skills": [...] }
```

Guarde o `session_id` para os próximos passos.

### 3.3 `GET /outputs` (antes de gerar arquivos)

Resposta esperada:
```json
{ "files": [] }
```

### 3.4 `GET /session/{id}/stream`

- Parâmetro `message`: `mostre as primeiras 5 linhas do CSV`
- Execute e observe o corpo da resposta (SSE): deve conter linhas `data: {...}`.

### 3.5 `POST /session/{id}/authorize`

Logo após o stream pausar em `tool_call`:
```json
{ "approved": true }
```
Resposta esperada `200`:
```json
{ "ok": true }
```

### 3.6 `GET /outputs/{filename}`

Após gerar um plot, passe o nome do arquivo. Resposta esperada: `200` com o binário da imagem.

### 3.7 `GET /outputs/{filename}` — arquivo inexistente

Passe `inexistente.png`. Resposta esperada: `404`.

### 3.8 `POST /session/{id}/authorize` — sessão inexistente

Use `session_id = "fake-id"`. Resposta esperada: `404`.

---

## 4. Checklist de validação

Marque cada item ao concluir:

- [ ] Backend sobe sem erros em `docker compose up --build`
- [ ] Frontend carrega em `http://localhost:3000`
- [ ] Upload CSV retorna `200` com `filename`
- [ ] `POST /session` retorna `session_id` e `skills`
- [ ] Stream emite `tool_call` ao enviar mensagem sobre o CSV
- [ ] Botões Aprovar / Negar aparecem no painel Atividade
- [ ] **Aprovar** executa a tool e emite `tool_result` + `done`
- [ ] **Negar** emite `tool_denied` e o agente responde graciosamente
- [ ] Plot salvo em `outputs/` aparece no painel Resultados
- [ ] `GET /outputs` lista o plot gerado
- [ ] `GET /outputs/inexistente.png` retorna `404`
- [ ] `POST /session/fake-id/authorize` retorna `404`
- [ ] `POST /session/{id}/authorize` sem tool pendente retorna `400`

---

## 5. Troubleshooting comum

| Sintoma | Causa provável | Solução |
|---------|---------------|---------|
| `ANTHROPIC_API_KEY not set` | `.env` ausente ou vazio | Crie `.env` com `ANTHROPIC_API_KEY=sk-...` na raiz |
| Chat trava após `tool_call` | Evento `authorize` não chegou | Verifique CORS; clique **Aprovar** novamente |
| Plot não aparece no painel | `outputs/` não montado corretamente | Confirme `volumes` no `docker-compose.yml` |
| `docker: image not found: claude-sandbox` | Imagem do sandbox não foi buildada | Execute `docker build -t claude-sandbox .` na pasta do sandbox |
| Frontend em branco | Build do React falhou | Rode `docker compose logs frontend` para ver erros |
