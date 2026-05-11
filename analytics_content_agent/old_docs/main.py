"""
main.py - Analytics Content Agent (FastAPI)

Este arquivo e o ponto de entrada HTTP da aplicacao. Ele nao contem a logica
especializada de analise, interpretacao de skills ou execucao em sandbox; em vez
disso, ele conecta esses componentes em uma API unica consumida pelo frontend.

Responsabilidades principais:
    - inicializar o app FastAPI;
    - expor endpoints para health check, upload de CSV e execucao de skills;
    - validar e normalizar a fonte de dados escolhida pelo usuario;
    - orquestrar os subagentes de planejamento;
    - converter os objetos internos do executor para o contrato esperado pela UI;
    - servir artefatos gerados em outputs/ e runs/.

Pipeline principal (POST /skills/run):
    prompt + data_source
      -> _data_source_context     (transforma a fonte de dados em contexto textual)
      -> planner_agent            (escolhe quais skills locais devem ser usadas)
      -> skill_interpreter_agent  (transforma cada skill em um perfil estruturado)
      -> execution_planner_agent  (gera um plano executavel a partir do perfil)
      -> run_execution_plan       (executa o plano em subprocessos/sandbox)
      -> _build_execution_view    (adapta a resposta para front/index.html)

Observacao importante:
    A API devolve um formato "legado" porque o frontend ja espera campos como
    selected_skills, executions, tool_calls e artifacts. Por isso, varias
    funcoes abaixo existem mais para compatibilidade de contrato do que para
    transformar dados de dominio complexos.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# Carrega variaveis de ambiente do arquivo .env antes de importar os agentes.
# Isso e importante porque os subagentes podem ler chaves de API, modelos
# padrao ou configuracoes assim que seus modulos sao importados.
load_dotenv()

from sub_agents.planning_agent import planner_agent
from sub_agents.skill_interpreter_agent import skill_interpreter_agent
from sub_agents.execution_planner_agent import (
    ClarificationRequest,
    ExecutionPlan,
    PlanValidationError,
    execution_planner_agent,
)
from src.tools.code_executor import ExecutionResult, run_execution_plan
from src.tools.loader import project_root, resolve_project_path


# ============================================================
# Paths
# ============================================================

# Todas as rotas de arquivo partem da raiz real do projeto, nao do diretorio de
# onde o processo foi iniciado. Isso evita bugs quando a API e executada por
# uvicorn, scripts, containers ou IDEs com working directories diferentes.
PROJECT_ROOT: Path = project_root()

# Diretorios usados pela API:
# - front/: contem o index.html e possiveis assets estaticos;
# - outputs/: artefatos finais que o usuario provavelmente quer baixar/abrir;
# - runs/: logs e arquivos intermediarios de execucoes;
# - data/uploads/: CSVs enviados pelo endpoint /data-sources/csv.
FRONT_DIR = PROJECT_ROOT / "front"
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
RUNS_DIR = PROJECT_ROOT / "runs"
DATA_DIR = PROJECT_ROOT / "data"
UPLOADS_DIR = DATA_DIR / "uploads"

# A API cria os diretorios gravaveis na inicializacao para que uploads,
# execucoes e montagem de arquivos estaticos nao falhem por ausencia de pasta.
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
RUNS_DIR.mkdir(parents=True, exist_ok=True)
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# App
# ============================================================

# Instancia principal do FastAPI. O titulo aparece em documentacao automatica
# como /docs e ajuda a identificar o servico em ambientes locais.
app = FastAPI(title="Analytics Content Agent")

app.add_middleware(
    CORSMiddleware,
    # Em desenvolvimento, o frontend pode estar em qualquer origem/porta.
    # Em producao, o ideal seria restringir allow_origins para dominios
    # conhecidos, mas aqui a API e pensada como ferramenta local.
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# Request / response schemas
# ============================================================


class SkillRunRequest(BaseModel):
    """
    Corpo esperado por POST /skills/run.

    O request une tres decisoes do usuario:
        1. o que ele quer fazer (prompt);
        2. qual modelo deve orientar os agentes (model);
        3. qual fonte de dados deve ser usada (CSV importado ou banco via MCP).

    csv_path so faz sentido quando data_source == "csv". A validacao completa
    desse relacionamento acontece em _data_source_context(), porque ela precisa
    resolver caminhos no filesystem do projeto.
    """

    # Prompt minimo de 3 caracteres evita chamadas acidentais ou vazias aos
    # agentes, que normalmente custam tempo e/ou tokens.
    prompt: str = Field(..., min_length=3)

    # Formato provider:model usado pelos agentes internos. O default privilegia
    # um modelo barato/rapido para o fluxo local.
    model: str = "openai:gpt-4o-mini"

    # Literal restringe o contrato da API a valores conhecidos e permite que
    # Pydantic/FastAPI retornem erro automatico para fontes nao suportadas.
    data_source: Literal["csv", "mcp_database"]

    # Caminho relativo retornado por /data-sources/csv. A API nao aceita um
    # caminho arbitrario do usuario sem antes confirmar que ele aponta para
    # data/uploads/.
    csv_path: str | None = None


# ============================================================
# Helpers: convert internal pipeline output into the shape
# the front (front/index.html) already understands.
# ============================================================


def _artifact_kind(rel_path: str) -> str:
    """
    Classifica um artefato retornado pelo executor como arquivo ou diretorio.

    O executor devolve caminhos relativos ao projeto. O frontend precisa saber
    se cada item deve ser tratado como um arquivo clicavel ou como uma pasta.
    Caso o caminho nao exista ou nao seja diretorio, a classificacao cai para
    "file", que e o comportamento mais simples para links de download/abertura.
    """

    abs_path = PROJECT_ROOT / rel_path
    if abs_path.is_dir():
        return "dir"
    return "file"


def _build_execution_view(
    skill_name: str,
    plan: ExecutionPlan,
    result: ExecutionResult,
) -> dict[str, Any]:
    """
    Converte o resultado interno de execucao para o formato esperado pela UI.

    Internamente, o plano contem comandos planejados e o resultado contem o que
    aconteceu quando cada comando rodou. Esta funcao junta os dois mundos:
        - argumentos planejados: argv, cwd, runtime, timeout, purpose;
        - dados observados: status, exit_code, stdout, stderr, duracao, erros;
        - artefatos finais: arquivos/pastas que a UI pode exibir.

    Esse adaptador tambem preserva nomes historicos como "tool_calls". Mesmo
    que a execucao atual seja feita por subprocessos e nao por uma ferramenta
    externa, o frontend usa essa estrutura para renderizar detalhes da execucao.
    """

    # Indexa comandos planejados por id para enriquecer cada resultado com o
    # contexto original que motivou a chamada. Se algum resultado vier sem plano
    # correspondente, a resposta ainda e montada com valores seguros.
    cmd_by_id = {c.id: c for c in plan.commands}

    tool_calls: list[dict[str, Any]] = []
    for r in result.commands:
        # Recupera o comando planejado que originou este resultado. O executor
        # retorna r.id, e o plano original contem os metadados legiveis.
        c = cmd_by_id.get(r.id)
        argv = list(c.argv) if c else []
        cwd = c.cwd if c else None
        runtime = c.runtime if c else None
        timeout = c.timeout_seconds if c else None
        purpose = c.purpose if c else ""

        tool_calls.append(
            {
                # tool_name mantem compatibilidade com a UI antiga, mas inclui
                # runtime e id para facilitar depuracao visual.
                "tool_name": f"{runtime or 'run'}:{r.id}",
                "arguments": {
                    "argv": argv,
                    "cwd": cwd,
                    "runtime": runtime,
                    "timeout_seconds": timeout,
                },
                "reason": purpose,
                # result e a parte observada da execucao: o que de fato saiu do
                # subprocesso, quanto tempo levou, quais artefatos declarou e
                # qualquer erro capturado pelo executor.
                "result": {
                    "ok": r.status == "success",
                    "status": r.status,
                    "exit_code": r.exit_code,
                    "stdout": r.stdout,
                    "stderr": r.stderr,
                    "duration_seconds": r.duration_seconds,
                    "artifacts": r.artifacts,
                    "error": r.error,
                },
            }
        )

    artifacts = [
        {"path": p, "kind": _artifact_kind(p)} for p in result.artifacts_returned
    ]

    # A mensagem final e curta porque aparece em destaque no frontend. Em caso
    # parcial, ela inclui um contador para mostrar rapidamente quantos comandos
    # do plano foram concluidos com sucesso.
    if result.status == "success":
        message = plan.summary or f"Skill '{skill_name}' executed successfully."
    elif result.status == "partial":
        message = (
            plan.summary or f"Skill '{skill_name}' partially executed."
        ) + f" ({sum(1 for c in result.commands if c.status == 'success')}/{len(result.commands)} commands ok)"
    else:
        message = f"Skill '{skill_name}' failed."

    return {
        "skill": skill_name,
        # ok representa sucesso total da skill. Execucoes parciais sao uteis,
        # mas nao devem ser tratadas pela UI como sucesso completo.
        "ok": result.status == "success",
        "message": message,
        "artifacts": artifacts,
        "tool_calls": tool_calls,
        "plan_id": plan.plan_id,
        "log_path": result.log_path,
        "execution_status": result.status,
    }


def _planning_failure(skill_name: str, error: str) -> dict[str, Any]:
    """
    Cria uma resposta padronizada para falhas antes da execucao.

    Falhas de interpretacao, validacao de plano ou rejeicao de sandbox nao geram
    ExecutionResult completo. Mesmo assim, o frontend espera um item dentro de
    executions. Esta funcao garante que todos esses casos tenham a mesma forma.
    """

    return {
        "skill": skill_name,
        "ok": False,
        "message": f"Planejamento falhou: {error}",
        "artifacts": [],
        "tool_calls": [],
    }


def _clarification_view(
    skill_name: str, response: ClarificationRequest
) -> dict[str, Any]:
    """
    Adapta um pedido de esclarecimento do planner para a resposta da API.

    O execution_planner_agent pode decidir que nao ha informacao suficiente para
    montar um plano seguro. Nesse caso, em vez de executar algo possivelmente
    errado, a API devolve uma pergunta ao usuario e lista os dados faltantes.
    """

    return {
        "skill": skill_name,
        "ok": False,
        "message": response.question_for_user,
        "artifacts": [],
        "tool_calls": [],
        "needs_clarification": True,
        "missing_information": list(response.missing_information),
    }


def _safe_upload_name(filename: str) -> str:
    """
    Gera um nome seguro e unico para CSVs enviados pelo usuario.

    O nome original do arquivo nao deve ser usado diretamente no filesystem:
        - pode conter espacos, barras, acentos ou caracteres problematicos;
        - pode tentar criar caminhos fora da pasta de uploads;
        - pode colidir com outro arquivo ja enviado.

    Por isso, a funcao preserva apenas um "stem" sanitizado e adiciona um
    timestamp UTC com microssegundos. A extensao final e sempre .csv.
    """

    # Path(...).stem remove extensoes e tambem lida bem com nomes vazios. O
    # fallback "data.csv" garante que sempre exista um stem inicial.
    stem = Path(filename or "data.csv").stem or "data"

    # Mantem apenas caracteres simples e portaveis. strip("._") evita nomes que
    # fiquem escondidos ou estranhos em alguns sistemas, como ".csv" ou "_".
    safe_stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", stem).strip("._") or "data"

    # Timestamp em UTC evita ambiguidades de timezone e reduz chance de colisao
    # mesmo em varios uploads no mesmo segundo.
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    return f"{stamp}_{safe_stem}.csv"


def _data_source_context(req: SkillRunRequest) -> str:
    """
    Transforma a fonte de dados escolhida em instrucoes textuais para os agentes.

    Os agentes trabalham principalmente com prompt. Em vez de passar objetos
    Python internos para cada agente, esta funcao cria um bloco de contexto que
    explica onde os dados estao e como eles devem ser usados.

    Para CSV, a funcao tambem atua como barreira de seguranca:
        - exige csv_path;
        - resolve o caminho contra a raiz do projeto;
        - confirma que o arquivo esta dentro de data/uploads/;
        - confirma que o arquivo existe.

    Para banco via MCP, nao ha arquivo local para validar aqui; o contexto apenas
    instrui os agentes a usarem a conexao MCP configurada.
    """

    if req.data_source == "csv":
        if not req.csv_path:
            raise HTTPException(
                status_code=400,
                detail="csv_path is required when data_source is csv",
            )

        csv_file = resolve_project_path(req.csv_path)
        try:
            # Garante que o caminho resolvido pertence a pasta de uploads. Isso
            # bloqueia tentativas de apontar para arquivos arbitrarios do projeto
            # ou do sistema operacional usando caminhos relativos maliciosos.
            csv_file.relative_to(UPLOADS_DIR.resolve())
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail="csv_path must point to an imported CSV file",
            ) from exc

        if not csv_file.is_file():
            raise HTTPException(status_code=400, detail="Imported CSV file not found")

        # Os agentes recebem caminhos relativos para manter o prompt estavel e
        # legivel, independentemente da maquina onde o projeto esta rodando.
        rel_path = csv_file.relative_to(PROJECT_ROOT).as_posix()
        return (
            "Data source: imported CSV file.\n"
            f"CSV path: {rel_path}\n"
            "Use this CSV as the input data for the user request."
        )

    return (
        "Data source: database connection via MCP.\n"
        "Use the configured MCP database connection as the input data source."
    )


# ============================================================
# Endpoints
# ============================================================


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    """
    Endpoint simples de saude.

    Usado por humanos, scripts ou futuros checks de container para confirmar que
    o processo FastAPI esta respondendo, sem acionar agentes nem tocar dados.
    """

    return {"ok": True, "service": "analytics-content-agent"}


@app.post("/data-sources/csv")
async def import_csv_source(file: UploadFile = File(...)) -> dict[str, Any]:
    """
    Recebe um CSV do usuario e o salva em data/uploads/.

    Este endpoint separa upload de execucao: primeiro o frontend envia o arquivo
    e recebe um caminho relativo; depois POST /skills/run referencia esse caminho
    em csv_path. Esse desenho evita reenviar o CSV a cada execucao e permite que
    os agentes trabalhem com um arquivo local estavel.
    """

    filename = file.filename or ""

    # Validacao de extensao e propositalmente simples: este endpoint representa
    # apenas a intencao declarada do usuario. Validacoes profundas de conteudo
    # podem ficar nas skills que realmente leem o CSV.
    if not filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only .csv files are accepted")

    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="CSV file is empty")

    # O arquivo e salvo com nome gerado pela API, nao com o nome bruto enviado
    # pelo cliente, para reduzir riscos de path traversal e colisao.
    dest = UPLOADS_DIR / _safe_upload_name(filename)
    dest.write_bytes(contents)

    # Retorna caminho relativo porque esse e o formato aceito por /skills/run e
    # mais facil de exibir no frontend.
    rel_path = dest.relative_to(PROJECT_ROOT).as_posix()
    return {
        "ok": True,
        "path": rel_path,
        "filename": filename,
        "size": len(contents),
    }


@app.post("/skills/run")
def run_local_skills(req: SkillRunRequest) -> dict[str, Any]:
    """
    Executa o pipeline completo de skills locais.

    A funcao recebe uma solicitacao do usuario, adiciona o contexto da fonte de
    dados, escolhe skills, transforma cada skill em um plano executavel e roda
    esse plano no executor sandboxed.

    O retorno segue o payload legado consumido por front/index.html:

        {
          "prompt": str,
          "user_steps": [str, ...],
          "selected_skills": [str, ...],
          "executions": [
            {
              "skill": str,
              "ok": bool,
              "message": str,
              "artifacts": [{"path": str, "kind": "file"|"dir"}, ...],
              "tool_calls": [
                {"tool_name", "arguments", "reason", "result"}, ...
              ]
            },
            ...
          ]
        }

    Estrategia de erro:
        Cada skill e processada de forma independente. Se uma skill falhar no
        planejamento ou na execucao, a falha e adicionada a executions e o loop
        continua para as proximas skills. Assim, um problema localizado nao
        impede que outras skills selecionadas ainda produzam resultado.
    """

    # Enriquecemos o prompt do usuario com a fonte de dados escolhida. Desse
    # ponto em diante, todos os agentes recebem a mesma versao contextualizada,
    # reduzindo a chance de um deles ignorar onde os dados estao.
    contextual_prompt = f"{_data_source_context(req)}\n\nUser request:\n{req.prompt}"

    # Primeiro agente: decompoe a intencao do usuario em passos compreensiveis e
    # escolhe quais skills locais parecem adequadas para atender ao pedido.
    user_steps, selected_skills = planner_agent(contextual_prompt, model=req.model)

    # Se nenhuma skill for escolhida, ainda devolvemos os passos planejados para
    # que a UI consiga explicar ao usuario o que foi entendido pelo planner.
    if not selected_skills:
        return {
            "prompt": req.prompt,
            "data_source": req.data_source,
            "csv_path": req.csv_path,
            "user_steps": user_steps,
            "selected_skills": [],
            "executions": [],
        }

    executions: list[dict[str, Any]] = []

    for skill_name in selected_skills:
        try:
            # Segundo agente: converte o nome da skill em um perfil estruturado
            # com capacidades, entradas esperadas e restricoes. Isso evita que o
            # planejador de execucao dependa apenas de um nome textual.
            profile = skill_interpreter_agent(skill_name, model=req.model)
        except Exception as exc:
            executions.append(_planning_failure(skill_name, f"interpret: {exc}"))
            continue

        try:
            # Terceiro agente: cria um ExecutionPlan concreto para a skill,
            # incluindo comandos, diretorios, artefatos esperados e limites.
            response = execution_planner_agent(
                prompt=contextual_prompt,
                skill_profile=profile,
                model=req.model,
            )
        except (PlanValidationError, ValueError) as exc:
            executions.append(_planning_failure(skill_name, str(exc)))
            continue

        if isinstance(response, ClarificationRequest):
            # Quando faltam dados para executar com seguranca, a resposta do
            # planner vira uma pergunta ao usuario em vez de um plano.
            executions.append(_clarification_view(skill_name, response))
            continue

        try:
            # Execucao efetiva do plano. A validacao de sandbox tambem pode
            # acontecer aqui, por isso PlanValidationError ainda e tratado.
            result = run_execution_plan(response)
        except PlanValidationError as exc:
            executions.append(
                _planning_failure(skill_name, f"sandbox rejected plan: {exc}")
            )
            continue
        except Exception as exc:
            executions.append(_planning_failure(skill_name, f"executor crashed: {exc}"))
            continue

        # Une o plano planejado e os resultados observados no shape que a UI
        # conhece, incluindo tool_calls e lista de artefatos.
        executions.append(_build_execution_view(skill_name, response, result))

    # Resposta agregada de toda a execucao. Mesmo que algumas skills falhem,
    # executions contem a situacao individual de cada uma.
    return {
        "prompt": req.prompt,
        "data_source": req.data_source,
        "csv_path": req.csv_path,
        "user_steps": user_steps,
        "selected_skills": selected_skills,
        "executions": executions,
    }


# ============================================================
# Static / frontend
# ============================================================

# Servico de artefatos.
#
# outputs/ e runs/ sao as unicas subarvores do projeto que o executor deve
# escrever e as unicas que a UI precisa expor como links. Manter essa lista
# pequena reduz a superficie de arquivos publicados pelo servidor.
app.mount(
    "/files/outputs",
    StaticFiles(directory=str(OUTPUTS_DIR), check_dir=False),
    name="outputs",
)
app.mount(
    "/files/runs",
    StaticFiles(directory=str(RUNS_DIR), check_dir=False),
    name="runs",
)

# Assets do frontend. Mesmo que hoje o index.html concentre boa parte da UI,
# montar /front permite servir CSS/JS/imagens externas no futuro sem mudar a API.
app.mount("/front", StaticFiles(directory=str(FRONT_DIR), html=True), name="front")


@app.get("/")
def read_root() -> FileResponse:
    """
    Entrega a interface web principal.

    A API e o frontend vivem no mesmo processo para simplificar o uso local: ao
    abrir /, o usuario recebe front/index.html; as chamadas subsequentes desse
    frontend usam os endpoints definidos acima.
    """

    index = FRONT_DIR / "index.html"
    if not index.is_file():
        # Retornar JSON aqui facilita diagnostico em vez de gerar um erro 404
        # generico quando o projeto esta incompleto ou foi empacotado sem front/.
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": "front/index.html not found"},
        )
    return FileResponse(str(index))
