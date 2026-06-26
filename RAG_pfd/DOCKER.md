# Rodando com Docker

## Pré-requisitos

- [Docker](https://docs.docker.com/get-docker/) instalado
- Chave de API da OpenAI

## 1. Configure o `.env`

Copie o arquivo de exemplo e preencha com sua chave:

```bash
.env
```

Edite o `.env` e substitua `sk-...` pela sua chave:

```env
OPENAI_API_KEY=sk-sua-chave-aqui
```

## 2. Suba o container

```bash
docker compose up --build
```

O build compila o frontend React e empacota tudo em uma única imagem Python. Na primeira vez leva alguns minutos.

## 3. Acesse

Abra no navegador: [http://localhost:8000]

## Comandos úteis

| Comando | Descrição |
|---|---|
| `docker compose up --build` | Sobe e reconstrói a imagem |
| `docker compose up` | Sobe sem reconstruir |
| `docker compose down` | Para e remove os containers |
| `docker compose down -v` | Para e apaga os volumes (limpa os dados) |
| `docker compose logs -f` | Acompanha os logs em tempo real |
