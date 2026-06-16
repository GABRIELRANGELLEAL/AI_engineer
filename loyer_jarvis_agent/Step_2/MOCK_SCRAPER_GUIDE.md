# Mock Scraper Guide — Test Step 2 WITHOUT Credentials

**Português**: Teste Step 2 completamente sem credenciais de eProc!

---

## 🎯 O que é o Mock Scraper?

Um **simulador de eProc** que:
- ✅ Gera filings realistas (não precisa conectar a eProc)
- ✅ Salva no banco de dados real (Step 1)
- ✅ Testa toda a pipeline
- ✅ Não precisa de credenciais
- ✅ Roda em <1 segundo

**Perfeito para**: Desenvolver, testar, validar antes de usar credenciais reais

---

## 🚀 Quick Start (2 minutos)

### 1. Setup

```bash
cd Step_2

# Certificar que Step 1 está rodando
cd ../Step_1
alembic upgrade head  # ou docker-compose up -d
cd ../Step_2

# Criar .env (mínimo)
cat > .env << EOF
DATABASE_URL=postgresql://legaluser:securepassword@localhost:5432/legal_assistant_db
EOF
```

### 2. Executar testes SEM credenciais

```bash
# Teste completo (tudo)
python test_without_credentials.py

# Resultado esperado:
# ✓ PASS: Database Connection
# ✓ PASS: Schema Exists
# ✓ PASS: Create Test User
# ✓ PASS: Create Test Case
# ✓ PASS: Mock Filing Generation
# ✓ PASS: Full Mock Pipeline
# ✓ PASS: Structured Logging
# 
# TEST RESULTS: 7 passed, 0 failed
```

### 3. Executar mock scraper

```bash
# Scrape todas as cases com dados fake
python scraper_mock.py

# Saída esperada:
# Mock browser started (no real Playwright)
# Mock scraping case: 0001234-56.2026.8.26.0100
# ✓ Saved 3 filings for 0001234-56.2026.8.26.0100
# Mock browser stopped
```

### 4. Verificar dados salvos

```bash
# Conectar ao banco
psql -U legaluser -d legal_assistant_db -h localhost

# Ver filings criados
SELECT COUNT(*) FROM filings;
SELECT filing_date, raw_content FROM filings LIMIT 3;

# Ver estrutura do filing (exemplo)
SELECT * FROM filings WHERE case_id = 1 LIMIT 1 \gx
```

---

## 📋 Arquivos do Mock

| Arquivo | Propósito |
|---------|-----------|
| **scraper_mock.py** | Mock scraper com dados realistas |
| **test_without_credentials.py** | Suite de testes completa |
| **MOCK_SCRAPER_GUIDE.md** | Este guia |

---

## 🧪 Testes Disponíveis

### `test_without_credentials.py`

Testa **sem nenhuma credencial**:

```python
test_database_connection()       # Can connect to DB?
test_schema_exists()             # All tables present?
test_create_test_user()          # Can create user?
test_create_test_case()          # Can create case?
test_raw_filing_structure()      # RawFiling data class OK?
test_filing_deduplication()      # Duplicate prevention works?
test_mock_filing_generation()    # Mock generates filings?
test_full_mock_scrape_pipeline() # Full pipeline works?
test_structured_logging()        # JSON logging works?
```

Rodando:
```bash
python test_without_credentials.py
```

---

## 📊 Como o Mock Scraper Funciona

### Fluxo

```
MockEprocScraper
    ↓
    async def get_new_filings(case)
    ├→ Gera 2-5 filings aleatórios
    ├→ Com datas nos últimos 7 dias
    ├→ Com tipos realistas (motion, order, petition, etc)
    ├→ Filtra existentes no DB
    └→ Retorna apenas novos
    
    ↓
    async def save_filings(case_id, filings)
    └→ Salva no banco (SQL real)
```

### Dados de Exemplo

**Tipos de filing:**
- MOTION — Moção de suspensão, prorrogação, etc
- ORDER — Despacho, intimação, etc
- PETITION — Petição, medida cautelar, etc
- RESPONSE — Resposta, impugnação, etc
- APPEAL — Agravo, recurso, etc

**Exemplo gerado:**
```
MOÇÃO DE prorrogação de prazo - Requerimento para mantém a decisão anterior
Data: 2026-06-10 14:32:00
```

---

## 🔄 Fluxo de Teste

### Passo 1: Criar usuário + caso

```bash
python test_without_credentials.py
```

Cria automaticamente:
- Usuário: "Mock Test User" (email: test_mock@example.com)
- Caso: "9999999-99.9999.0.00.0000"

### Passo 2: Gerar mock filings

```bash
python scraper_mock.py --case-id 1
```

Gera 2-5 filings realistas e salva no banco

### Passo 3: Verificar no banco

```bash
psql -U legaluser -d legal_assistant_db -c "SELECT COUNT(*) FROM filings;"
```

Ver filings criados

### Passo 4: Repetir testes

```bash
python test_without_credentials.py
```

Testa deduplicação (não cria duplicatas)

---

## 💡 Casos de Uso

### Desenvolvimento Local

```bash
# Trabalhar sem credenciais eProc
python scraper_mock.py

# Testa toda a pipeline sem internet
python test_without_credentials.py

# Rápido (< 1 segundo)
```

### Validar Banco de Dados

```bash
# Criar dados de teste
python test_without_credentials.py

# Validar schema Step 1 está OK
# Validar relacionamentos funcionam
# Validar filings salvam corretamente
```

### CI/CD Pipeline

```bash
# Em GitHub Actions, GitLab CI, etc.
python test_without_credentials.py

# Não precisa de secrets/credenciais
# Rápido para feedback rápido
```

### Antes de Usar Credenciais Reais

```bash
# 1. Validar tudo com mock
python test_without_credentials.py

# 2. Se passou, então testar com credenciais
python scraper_run.py --dry-run

# 3. Se passou, então salvar
python scraper_run.py
```

---

## 🔧 Personalização

### Mudar número de filings gerados

```bash
# Gerar 10 filings em vez de padrão
python scraper_mock.py --num-filings 10
```

### Adicionar novos tipos de filing

Em `scraper_mock.py`, editar:

```python
MOCK_FILINGS = {
    "motion": "MOÇÃO...",
    "custom": "MEU TIPO CUSTOMIZADO: {description}",  # ADD THIS
}

FILING_DESCRIPTIONS = {
    "custom": ["descrição 1", "descrição 2"],  # ADD THIS
}
```

### Mudar frequência de datas

Em `scraper_mock.py`, na função `get_new_filings()`:

```python
# Antes: randint(0, 7)  # Últimos 7 dias
days_ago = randint(0, 30)  # Últimos 30 dias
```

---

## 📈 Progressão: Mock → Real

### Fase 1: Mock (agora)

```bash
python test_without_credentials.py
python scraper_mock.py
```

✓ Valida banco  
✓ Valida pipeline  
✓ Rápido  
✗ Não testa autenticação real  

### Fase 2: Credenciais Reais

```bash
python scraper_run.py --dry-run
```

✓ Testa autenticação  
✓ Testa seletores reais  
✗ Mais lento  
✗ Precisa credenciais  

### Fase 3: Produção

```bash
docker-compose build
docker-compose up -d
# Celery integration (Step 8)
```

---

## 🐛 Debugging

### Ver logs estruturados

```bash
python scraper_mock.py 2>&1 | grep "filing"
```

### Aumentar verbosidade

No `config.py`:
```python
LOG_LEVEL = "DEBUG"  # Antes: "INFO"
```

### Conectar ao banco e inspecionar

```bash
psql -U legaluser -d legal_assistant_db

-- Ver filings gerados
SELECT filing_date, raw_content, status 
FROM filings 
ORDER BY created_at DESC 
LIMIT 5;

-- Ver casos
SELECT * FROM cases;

-- Ver usuários
SELECT * FROM users;
```

---

## ✅ Checklist: Teste Completo Sem Credenciais

- [ ] Step 1 rodando (banco)
- [ ] `.env` com DATABASE_URL
- [ ] `python test_without_credentials.py` → 7/7 testes passam
- [ ] `python scraper_mock.py` → sem erros
- [ ] `psql` → filings criados no banco
- [ ] Repetir `test_without_credentials.py` → deduplicação funciona

**Se tudo passou**: Step 2 está pronto para credenciais reais! ✓

---

## 🚀 Próximos Passos

Depois que mock funcionar:

1. **Adicionar credenciais reais** (se tiver)
   ```bash
   # Editar .env
   EPROC_USERNAME=seu_usuario
   EPROC_PASSWORD=sua_senha
   ```

2. **Rodar contra eProc real**
   ```bash
   python scraper_run.py --case-id 1
   ```

3. **Integrar com Step 3** (RAG Example Bank)
   - Lê filings com `status=new`
   - Cria embeddings
   - Popula `example_bank`

4. **Integrar com Celery** (Step 8)
   - Scraper rodado periodicamente
   - Filings analisados automaticamente

---

## 📚 Referência Rápida

```bash
# Teste completo sem credenciais
python test_without_credentials.py

# Mock scraper
python scraper_mock.py

# Mock scraper + case específico
python scraper_mock.py --case-id 1

# Mock scraper + mais filings
python scraper_mock.py --num-filings 10

# Ver logs do banco
psql -U legaluser -d legal_assistant_db -c "SELECT COUNT(*) FROM filings;"

# Limpar dados de teste
psql -U legaluser -d legal_assistant_db -c "DELETE FROM filings WHERE case_id IN (SELECT id FROM cases WHERE case_number='9999999-99.9999.0.00.0000');"
```

---

**Pronto para testar?**

```bash
python test_without_credentials.py
```

Se passar: ✓ Step 2 está funcionando!

Next: Step 3 (RAG) ou credenciais reais de eProc.
