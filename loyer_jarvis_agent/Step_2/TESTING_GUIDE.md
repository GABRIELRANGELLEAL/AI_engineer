# Step 2 Testing Guide — Complete Docker & Test Instructions

**Portuguese guide**: Como testar Step 2 com Docker

---

## Opção 1: Teste Local (Sem Docker)

### 1. Instalar dependências

```bash
cd Step_2
pip install -r requirements.txt
playwright install
```

### 2. Configurar banco de dados (Step 1)

Certifique-se que Step 1 está rodando:

```bash
cd ../Step_1
docker-compose up -d
# Ou se PostgreSQL local:
alembic upgrade head
```

### 3. Criar arquivo .env

```bash
cp .env.example .env
```

Editar `.env`:
```
DATABASE_URL=postgresql://legaluser:securepassword@localhost:5432/legal_assistant_db
EPROC_USERNAME=seu_usuario
EPROC_PASSWORD=sua_senha
```

### 4. Testar componentes

```bash
# Teste de banco de dados
python test_scraper.py --test database

# Teste de extração de filings
python test_scraper.py --test filings

# Todos os testes
python test_scraper.py --test all
```

### 5. Rodas o scraper

```bash
# Teste sem salvar no banco
python scraper_run.py --dry-run

# Scraper completo
python scraper_run.py
```

---

## Opção 2: Teste com Docker (Recomendado)

### Pré-requisitos

- Docker instalado
- Docker Compose instalado
- (Opcional) Credenciais reais de eProc

### Passo 1: Preparar variáveis de ambiente

```bash
cd Step_2

# Se tiver credenciais reais:
cat > .env.docker << EOF
EPROC_USERNAME=seu_cpf_ou_usuario
EPROC_PASSWORD=sua_senha
EOF

# Se for teste sem credenciais:
# Deixe os valores de teste no docker-compose.yml
```

### Passo 2: Construir imagens Docker

```bash
# Build da imagem do scraper
docker-compose build

# Ou pull da imagem base
docker-compose pull postgres
```

### Passo 3: Iniciar serviços

```bash
# Subir banco de dados e scraper
docker-compose up -d

# Ver logs
docker-compose logs -f postgres
docker-compose logs -f scraper
```

Espere até aparecer:
```
legal_assistant_db  | CREATE EXTENSION
legal_assistant_db  | [DONE] listening on 127.0.0.1:5432
```

### Passo 4: Verificar saúde

```bash
# Verificar se está tudo rodando
docker-compose ps

# Deve mostrar:
# legal_assistant_db   Up (healthy)
# eproc_scraper        Up
```

### Passo 5: Testar banco de dados

```bash
# Conectar ao banco dentro do Docker
docker exec -it legal_assistant_db psql -U legaluser -d legal_assistant_db

# Dentro do psql:
SELECT COUNT(*) FROM users;
SELECT COUNT(*) FROM cases;
\dt  # Listar tabelas
\q   # Sair
```

### Passo 6: Criar casos de teste

```bash
# Criar arquivo insert_test_data.sql
cat > insert_test_data.sql << 'EOF'
-- Inserir usuário de teste
INSERT INTO users (name, email) VALUES ('Advogado Teste', 'teste@example.com');

-- Inserir caso de teste
INSERT INTO cases (case_number, court, lawyer_id, active) 
SELECT '0001234-56.2026.8.26.0100', 'TJ-SP', id, true 
FROM users WHERE email = 'teste@example.com' LIMIT 1;
EOF

# Executar no banco
docker exec -i legal_assistant_db psql -U legaluser -d legal_assistant_db < insert_test_data.sql
```

### Passo 7: Ver logs do scraper

```bash
# Logs em tempo real
docker-compose logs -f scraper

# Logs com filtro
docker-compose logs scraper | grep "error"
docker-compose logs scraper | grep "case_number"
```

### Passo 8: Parar containers

```bash
# Parar sem remover
docker-compose stop

# Parar e remover
docker-compose down

# Remover também os dados
docker-compose down -v
```

---

## Passo-a-Passo Completo (Do Zero)

### Cenário: Testar tudo from scratch

```bash
# 1. Clonar/preparar Step 1 e Step 2
cd loyer_jarvis_agent/Step_1
docker-compose up -d
cd ../Step_2

# 2. Configurar Step 2
cp .env.example .env
# Editar .env se tiver credenciais reais

# 3. Construir Step 2
docker-compose build

# 4. Iniciar Step 2 (usa banco do Step 1)
docker-compose up -d postgres scraper

# 5. Esperar healthcheck
sleep 10

# 6. Inserir dados de teste
cat > test_data.sql << 'EOF'
INSERT INTO users (name, email) 
VALUES ('Advogado Maria', 'maria@court.br');

INSERT INTO cases (case_number, court, lawyer_id, active)
SELECT '1234567-89.2026.8.26.0100', 'TJ-SP', id, true
FROM users WHERE email = 'maria@court.br' LIMIT 1;
EOF

docker exec -i legal_assistant_db psql -U legaluser -d legal_assistant_db < test_data.sql

# 7. Verificar dados inseridos
docker exec legal_assistant_db psql -U legaluser -d legal_assistant_db -c "SELECT * FROM cases;"

# 8. Ver logs do scraper
docker-compose logs scraper

# 9. Parar tudo
docker-compose down -v
```

---

## Teste Sem Credenciais Reais

Se não tiver credenciais de eProc, teste assim:

### 1. Teste unitário (sem eProc)

```bash
# Teste banco de dados
docker-compose run --rm scraper python test_scraper.py --test database

# Teste de filings (mock)
docker-compose run --rm scraper python test_scraper.py --test filings
```

### 2. Teste dry-run

```bash
# Tenta conectar a eProc mas não salva
docker-compose run --rm -e EPROC_USERNAME=fake -e EPROC_PASSWORD=fake scraper \
  python scraper_run.py --dry-run
```

**Resultado esperado**: Erro de autenticação (o que é esperado sem credenciais).

### 3. Teste apenas DB

```bash
# Conectar e verificar schema
docker exec legal_assistant_db psql -U legaluser -d legal_assistant_db -c "
  SELECT table_name FROM information_schema.tables WHERE table_schema='public';
"
```

---

## Debugging

### Ver logs estruturados

```bash
# Logs do container
docker-compose logs scraper

# Buscar por case_number específico
docker-compose logs scraper | grep "0001234"

# Buscar por erros
docker-compose logs scraper | grep "ERROR"

# Último 50 linhas
docker-compose logs scraper --tail=50
```

### Acessar terminal do container

```bash
# Entrar no container scraper
docker-compose exec scraper bash

# Dentro do container:
ls -la
cat logs/scraper.log
python -c "from scraper import EprocScraper; print('OK')"
```

### Verificar conectividade

```bash
# Teste de rede entre containers
docker-compose exec scraper ping postgres

# Teste de conexão PostgreSQL
docker-compose exec scraper psql -h postgres -U legaluser -d legal_assistant_db -c "SELECT 1;"
```

### Limpar tudo e recomeçar

```bash
# Parar tudo
docker-compose down

# Remover volumes (dados)
docker volume prune -f

# Remover imagens
docker image prune -f

# Reconstruir
docker-compose build --no-cache
docker-compose up -d
```

---

## Checklist de Testes

### ✓ Setup
- [ ] Docker e Docker Compose instalados
- [ ] `cd Step_2`
- [ ] `cp .env.example .env`
- [ ] `.env` preenchido com DATABASE_URL

### ✓ Build & Start
- [ ] `docker-compose build` sem erros
- [ ] `docker-compose up -d` containers rodando
- [ ] `docker-compose ps` mostra healthy

### ✓ Database
- [ ] Conectar ao PostgreSQL: `docker exec -it legal_assistant_db psql ...`
- [ ] Ver tabelas: `\dt`
- [ ] Contar usuarios: `SELECT COUNT(*) FROM users;`
- [ ] Inserir caso de teste
- [ ] Verificar caso inserido

### ✓ Scraper
- [ ] Logs rodando: `docker-compose logs -f scraper`
- [ ] Sem erro de importação de models
- [ ] Sem erro de DATABASE_URL
- [ ] Tentou conectar a eProc (ou erro de auth é esperado)

### ✓ Cleanup
- [ ] `docker-compose logs scraper` sem erros críticos
- [ ] `docker-compose down` parou tudo
- [ ] `docker volume ls` mostra dados persistidos

---

## Problemas Comuns & Soluções

### ❌ "Connection refused" ao PostgreSQL

```bash
# Problema: Container não está saudável

# Solução:
docker-compose logs postgres  # Ver logs
docker-compose down -v        # Remover e recomeçar
docker-compose up -d
docker-compose ps             # Verificar status
```

### ❌ "ModuleNotFoundError: No module named 'models'"

```bash
# Problema: Step 1 não está no caminho

# Solução: Editar scraper.py linha 14
# Antes:
# sys.path.insert(0, str(Path(__file__).parent.parent / "Step_1"))

# Depois (se Step 1 está em outro lugar):
import sys; sys.path.insert(0, '/path/to/Step_1')
```

### ❌ "Timeout waiting for browser launch"

```bash
# Problema: Playwright não conseguiu iniciar

# Solução:
docker-compose down
docker-compose build --no-cache
docker-compose up -d
```

### ❌ "Authentication failed"

```bash
# Problema: Credenciais incorretas (esperado se usar fake)

# Solução:
# 1. Verificar credenciais no .env
# 2. Tentar com --dry-run
# 3. Verificar se eProc está acessível
```

### ❌ "Disk space: layer download failed"

```bash
# Problema: Docker sem espaço

# Solução:
docker system prune -a
docker image prune
docker volume prune
```

---

## Scripts Úteis

### `run_tests.sh`

```bash
#!/bin/bash
set -e

echo "Building Docker image..."
docker-compose build

echo "Starting services..."
docker-compose up -d

echo "Waiting for database..."
sleep 10

echo "Testing database connection..."
docker-compose run --rm scraper python test_scraper.py --test database

echo "Testing filing extraction..."
docker-compose run --rm scraper python test_scraper.py --test filings

echo "All tests passed!"
docker-compose logs scraper
```

Use assim:
```bash
chmod +x run_tests.sh
./run_tests.sh
```

---

## Resumo Rápido

```bash
# Setup
cd Step_2
cp .env.example .env
# Editar .env

# Start
docker-compose up -d

# Verify
docker-compose ps
docker-compose logs scraper

# Test
docker-compose run --rm scraper python test_scraper.py --test all

# Stop
docker-compose down
```

---

**Próximo**: Quando tudo funcionar, integrar com Step 3 (RAG Example Bank)
