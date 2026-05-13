#!/usr/bin/env python3
"""
Claude Local Sandbox Agent
Filesystem local + execução em Docker + skills em markdown.
"""

# Importações necessárias para o funcionamento do agente
import os          # Para acessar variáveis de ambiente (API key)
import re          # Para limpeza de blocos de código markdown na resposta do LLM
import json        # Para serialização de dados das tool calls
import subprocess  # Para executar comandos Docker
from pathlib import Path  # Para manipulação de caminhos de arquivos
from dotenv import load_dotenv
import anthropic   # Cliente oficial da API do Claude

load_dotenv()
# ─── Paths ───────────────────────────────────────────────────────────────────
# Define os diretórios base do projeto
BASE_DIR   = Path(__file__).resolve().parent        # Diretório onde está o script
SKILLS_DIR = BASE_DIR.parent / "skills"             # skills/ na raiz do projeto (skills/*/SKILL.md)
WORKSPACE  = BASE_DIR / "workspace"                 # Workspace montado no Docker
OUTPUTS    = BASE_DIR / "outputs"                   # Pasta para salvar resultados

# Cria os diretórios/pastas se não existirem
WORKSPACE.mkdir(exist_ok=True) 
OUTPUTS.mkdir(exist_ok=True)

# Inicializa o cliente da Anthropic com a chave de API do ambiente
client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

# System padrão quando nenhuma skill é injetada (skills substituem este texto por completo).
GENERIC_SYSTEM = (
    "Você é um assistente que pode usar ferramentas de filesystem e execução de código. "
    "Em `view`, `create_file`, `str_replace` e no diretório de trabalho do `bash`, os caminhos "
    "são relativos à raiz do workspace: é onde ficam os ficheiros enviados pelo utilizador "
    "(por exemplo CSV) após upload."
)

# ─── Tools (equivalentes ao sandbox do Claude.ai) ────────────────────────────
# Define as ferramentas disponíveis para o Claude usar durante a conversa
# Cada tool é um dicionário com name, description e input_schema
TOOLS = [
    # Tool 1: Execução de comandos bash em ambiente isolado
    {
        "name": "bash",
        "description": "Executa comandos bash dentro do container Docker (sandbox isolado).",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Comando bash a executar"},
                "description": {"type": "string", "description": "Por que está rodando este comando"}
            },
            "required": ["command", "description"]
        }
    },
    # Tool 2: Criação de arquivos no workspace
    {
        "name": "create_file",
        "description": "Cria um arquivo no workspace local.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Caminho relativo dentro do workspace"},
                "content": {"type": "string", "description": "Conteúdo do arquivo"}
            },
            "required": ["path", "content"]
        }
    },
    # Tool 3: Visualização de arquivos e listagem de diretórios
    {
        "name": "view",
        "description": "Lê um arquivo ou lista um diretório no workspace.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Caminho relativo dentro do workspace"}
            },
            "required": ["path"]
        }
    },
    # Tool 4: Substituição de string em arquivo (edição pontual)
    {
        "name": "str_replace",
        "description": "Substitui um trecho único em um arquivo existente.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path":    {"type": "string"},
                "old_str": {"type": "string"},
                "new_str": {"type": "string"}
            },
            "required": ["path", "old_str", "new_str"]
        }
    }
]

# ─── Handlers das tools ───────────────────────────────────────────────────────
# Cada handler implementa a lógica de execução de uma tool

def handle_bash(command: str, **_) -> str:
    """
    Executa um comando bash dentro de um container Docker isolado.
    
    Segurança:
    - Sem acesso à rede (--network none)
    - Limite de memória (512MB)
    - Limite de CPU (1 core)
    - Timeout de 60 segundos
    """
    try:
        result = subprocess.run(
            [
                "docker", "run", "--rm",                      # Remove container após execução
                "--network", "none",                          # Sem acesso à internet (segurança)
                "--memory", "512m",                           # Limite de RAM
                "--cpus", "1",                                # Limite de CPU
                "-v", f"{WORKSPACE}:/home/sandbox/workspace", # Monta workspace local no container
                "-v", f"{OUTPUTS}:/home/sandbox/outputs",     # Monta pasta de outputs
                "-w", "/home/sandbox/workspace",              # Define diretório de trabalho
                "claude-sandbox",                             # Nome da imagem Docker
                "bash", "-c", command                         # Comando a executar
            ],
            capture_output=True,  # Captura stdout e stderr
            text=True,            # Retorna strings ao invés de bytes
            timeout=60            # Timeout de 60 segundos
        )
    except FileNotFoundError:
        return (
            "[bash tool] O executável `docker` não foi encontrado no PATH deste sistema. "
            "No Windows, instale o Docker Desktop e confirme que `docker` funciona no terminal. "
            "Para ler o CSV sem o sandbox, use a ferramenta `view` no caminho relativo do ficheiro."
        )
    # Combina stdout e stderr no resultado
    output = result.stdout
    if result.stderr:
        output += f"\n[stderr]: {result.stderr}"
    return output or "(sem output)"


def handle_create_file(path: str, content: str, **_) -> str:
    """
    Cria um novo arquivo no workspace com o conteúdo especificado.
    Cria automaticamente diretórios intermediários se necessário.
    """
    target = WORKSPACE / path  # Constrói o caminho completo
    target.parent.mkdir(parents=True, exist_ok=True)  # Cria diretórios pais se não existirem
    target.write_text(content, encoding="utf-8")      # Escreve o conteúdo no arquivo
    return f"Arquivo criado: {target}"


def handle_view(path: str, **_) -> str:
    """
    Visualiza o conteúdo de um arquivo ou lista os itens de um diretório.
    
    Comportamento:
    - Se o path não existe: retorna mensagem de erro
    - Se é diretório: lista todos os itens dentro dele
    - Se é arquivo: retorna o conteúdo completo
    """
    target = WORKSPACE / path
    # Verifica se o caminho existe
    if not target.exists():
        return f"Não encontrado: {target}"
    # Se for diretório, lista os itens
    if target.is_dir():
        items = sorted(target.iterdir())
        return "\n".join(str(i.relative_to(WORKSPACE)) for i in items)
    # Se for arquivo, retorna o conteúdo
    return target.read_text(encoding="utf-8")


def handle_str_replace(path: str, old_str: str, new_str: str, **_) -> str:
    """
    Substitui uma string específica em um arquivo existente.
    
    Validação de segurança:
    - A string antiga (old_str) deve aparecer EXATAMENTE 1 vez no arquivo
    - Isso previne substituições acidentais em múltiplos lugares
    - Se aparecer 0 ou 2+ vezes, retorna erro
    """
    target = WORKSPACE / path
    content = target.read_text(encoding="utf-8")
    
    # Valida que old_str aparece exatamente uma vez (segurança)
    if content.count(old_str) != 1:
        return f"Erro: old_str aparece {content.count(old_str)} vez(es). Deve aparecer exatamente 1."
    
    # Faz a substituição e salva o arquivo
    target.write_text(content.replace(old_str, new_str, 1), encoding="utf-8")
    return "Substituição feita."


# Mapeamento de nomes de tools para suas funções handler
# Usado no loop principal para executar as tools que o Claude solicita
TOOL_HANDLERS = {
    "bash":        handle_bash,
    "create_file": handle_create_file,
    "view":        handle_view,
    "str_replace": handle_str_replace,
}

# ─── Skills: descoberta, seleção e carregamento ───────────────────────────────

def _parse_yaml_header(markdown: str) -> dict[str, str] | None:
    """
    Extrai o cabeçalho YAML do topo de um arquivo markdown.

    Suporta apenas o formato simples `key: value` usado nos SKILL.md do projeto.
    Evita dependência externa de um parser YAML completo.

    Retorna None se o arquivo não tiver cabeçalho no formato esperado.
    """
    lines = markdown.splitlines()
    # Cabeçalho YAML começa e termina com '---'
    if not lines or lines[0].strip() != "---":
        return None

    header_lines: list[str] = []
    for line in lines[1:]:
        if line.strip() == "---":
            break
        header_lines.append(line)
    else:
        # O bloco '---' de fechamento nunca foi encontrado
        return None

    header: dict[str, str] = {}
    for line in header_lines:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key   = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            header[key] = value

    return header or None


def _build_skills_catalog() -> dict[str, list[str]]:
    """
    Varre skills/*/SKILL.md e lê APENAS os cabeçalhos YAML de cada skill.

    Retorna um catálogo no formato:
        { "nome-da-skill": ["descrição curta", "/caminho/absoluto/SKILL.md"] }

    Vantagem: nenhum conteúdo completo das skills é lido nesta etapa,
    mantendo o custo de tokens mínimo para a fase de seleção.
    """
    catalog: dict[str, list[str]] = {}
    seen: set[Path] = set()

    for skill_file in sorted(SKILLS_DIR.glob("*/SKILL.md")):
        resolved = skill_file.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)

        try:
            markdown = skill_file.read_text(encoding="utf-8")
        except OSError:
            continue

        header = _parse_yaml_header(markdown)
        if not header:
            continue

        name        = header.get("name", "").strip()
        description = header.get("description", "").strip()
        if name and description:
            catalog[name] = [description, skill_file.as_posix()]

    return catalog


def _select_skills(prompt: str, catalog: dict[str, list[str]], model_name: str = "claude-haiku-4-5-20251001") -> list[str]:
    """
    Usa um modelo leve para escolher quais skills são relevantes para o prompt.

    Envia apenas o catálogo de resumos (não o conteúdo completo das skills),
    o que mantém o custo desta chamada muito baixo.

    Retorna lista de nomes de skills validados contra o catálogo.
    """
    if not catalog:
        return []

    # Monta o catálogo como lista de "- nome: descrição"
    catalog_text = "\n".join(
        f"- {name}: {info[0]}" for name, info in catalog.items()
    )

    response = client.messages.create(
        # Mesmo modelo do agente principal — garante compatibilidade com a conta
        model=model_name,
        max_tokens=256,
        messages=[{
            "role": "user",
            "content": (
                f"Given this user request:\n{prompt}\n\n"
                f"And these available skills:\n{catalog_text}\n\n"
                "Return ONLY a JSON array with the names of relevant skills. "
                "Return [] if none apply. Example: [\"skill-a\", \"skill-b\"]"
            )
        }]
    )

    raw = response.content[0].text.strip()
    # Remove blocos de código markdown caso o modelo os inclua (```json ... ```)
    raw = re.sub(r"^```[a-zA-Z]*\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw).strip()

    try:
        selected = json.loads(raw)
        # Valida: aceita apenas nomes que existem no catálogo
        return [name for name in selected if name in catalog]
    except (json.JSONDecodeError, TypeError):
        return []


def load_skills(names: list[str]) -> str:
    """
    Carrega o conteúdo COMPLETO apenas das skills selecionadas.

    Deve ser chamado após _select_skills, recebendo somente as skills
    escolhidas — evitando enviar conteúdo irrelevante ao LLM principal.

    Retorna string formatada com cada skill em uma tag XML <skill>.
    """
    catalog = _build_skills_catalog()

    parts = []
    for name in names:
        if name not in catalog:
            continue
        _, path = catalog[name]
        content = Path(path).read_text(encoding="utf-8")
        parts.append(f"<skill name='{name}'>\n{content}\n</skill>")

    return "\n\n".join(parts)

# ─── Turno único (para integração com Streamlit) ─────────────────────────────
def agent_turn(
    messages: list,
    system: str = "",
    model_name: str = "claude-sonnet-4-5-20250929",
) -> tuple[list, list]:
    """
    Executa um único turno: envia messages para a API e retorna
    (text_blocks, tool_blocks) sem executar as tools nem entrar em loop.

    O chamador é responsável por:
    - Executar (ou não) as tools retornadas em tool_blocks
    - Montar o tool_result e chamar agent_turn novamente se necessário
    - Controlar o loop e a autorização de cada tool call

    Args:
        messages:   Histórico completo no formato da API (role/content)
        system:     System prompt (conteúdo de skills já formatado, ou string vazia)
        model_name: Modelo a usar na chamada

    Returns:
        (text_blocks, tool_blocks) — listas de blocos do tipo `text` e `tool_use`
    """
    response = client.messages.create(
        model=model_name,                  # Modelo recebido como parâmetro
        max_tokens=8096,                   # Limite de tokens na resposta
        system=system or GENERIC_SYSTEM,
        tools=TOOLS,                       # Lista de tools disponíveis
        messages=messages,                 # Histórico completo da conversa
    )
    text_blocks = [b for b in response.content if b.type == "text"]
    tool_blocks = [b for b in response.content if b.type == "tool_use"]
    return text_blocks, tool_blocks


# ─── Loop do agente ───────────────────────────────────────────────────────────
def run_agent(prompt: str, skills: list[str] | None = None, verbose: bool = False, model_name: str = "claude-sonnet-4-5-20250929"):
    """
    Loop principal do agente: envia mensagens para o Claude e executa tools.

    Args:
        prompt:     A tarefa que o agente deve executar
        skills:     Lista de nomes de skills a forçar (sem extensão). Se None, a seleção automática é feita via LLM leve.
        verbose:    Se True, mostra detalhes das tool calls e resultados
        model_name: Modelo usado na execução principal (ex: "claude-sonnet-4-5-20250929")

    Fluxo:
    1. Etapa de seleção (leve):
       - Lê apenas os cabeçalhos YAML de todas as skills
       - Chama um LLM leve para escolher quais skills são relevantes
    2. Etapa de execução (principal):
       - Carrega o conteúdo completo APENAS das skills selecionadas
       - Envia ao Claude junto com as tools
       - Loop de tool calls até end_turn
    """
    # ── Etapa 1: seleção de skills ────────────────────────────────────────────
    if skills is None:
        print("selecting the ideal skill to execute resolve your task")
        # Seleção automática: lê só os cabeçalhos e deixa o LLM leve decidir
        catalog = _build_skills_catalog()
        skills  = _select_skills(prompt, catalog, model_name=model_name)
        if verbose:
            print(f"\n[Skills selecionadas automaticamente: {skills or 'nenhuma'}]\n")
    elif verbose:
        print(f"\n[Skills forçadas pelo usuário: {skills}]\n")

    # ── Etapa 2: carrega conteúdo completo apenas das skills escolhidas ───────
    print("loading the content of the selected skills")
    system = load_skills(skills) if skills else ""
    if verbose and system:
        print(f"\n[Conteúdo carregado para: {skills}]\n")

    # Inicializa o histórico de mensagens com o prompt do usuário
    messages = [{"role": "user", "content": prompt}]

    # Loop principal: continua até o Claude não solicitar mais tools
    while True:
        print("sending the message to the Claude")
        # Envia mensagem para o Claude com todo o contexto
        response = client.messages.create(
            model=model_name,                  # Modelo recebido como parâmetro
            max_tokens=8096,                   # Limite de tokens na resposta
            system=system or GENERIC_SYSTEM,
            tools=TOOLS,                       # Lista de tools disponíveis
            messages=messages,                 # Histórico completo da conversa
        )

        if verbose:
            print(f"[stop_reason: {response.stop_reason}]")

        # Separa a resposta em blocos de texto e blocos de tool_use
        text_blocks = [b for b in response.content if b.type == "text"]
        tool_blocks = [b for b in response.content if b.type == "tool_use"]

        # Imprime o texto da resposta do Claude
        for tb in text_blocks:
            print(tb.text)

        # Se o Claude terminou ou não solicitou tools, encerra o loop
        if response.stop_reason == "end_turn" or not tool_blocks:
            break

        # Executa cada tool solicitada pelo Claude
        tool_results = []
        for block in tool_blocks:
            # Se verbose, mostra qual tool está sendo chamada e com quais parâmetros
            if verbose:
                print(f"\n[Tool: {block.name}] {json.dumps(block.input, ensure_ascii=False)[:120]}")

            # Busca o handler correspondente e executa com os parâmetros
            handler = TOOL_HANDLERS.get(block.name)
            result  = handler(**block.input) if handler else f"Tool desconhecida: {block.name}"

            # Se verbose, mostra o resultado (limitado a 200 caracteres)
            if verbose:
                print(f"[Resultado]: {str(result)[:200]}")

            # Monta o resultado no formato esperado pela API
            tool_results.append({
                "type":        "tool_result",
                "tool_use_id": block.id,        # ID único da tool_use
                "content":     str(result),     # Resultado da execução
            })

        # Atualiza o histórico de mensagens para a próxima iteração
        # 1. Adiciona a resposta do assistant (incluindo as tool_use)
        messages.append({"role": "assistant", "content": response.content})
        # 2. Adiciona os resultados das tools como mensagem do user
        messages.append({"role": "user",      "content": tool_results})

# ─── CLI ──────────────────────────────────────────────────────────────────────
# Executa o agente pela linha de comando se o script for chamado diretamente
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Claude Local Sandbox",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Exemplos:\n"
            "  python agent.py 'analise a série temporal'           # seleção automática de skills\n"
            "  python agent.py 'gere um docx' --skills docx         # força skill específica\n"
            "  python agent.py 'gere um docx' --verbose             # mostra seleção e tool calls\n"
        )
    )

    # Argumento obrigatório: o prompt/tarefa para o agente
    parser.add_argument("prompt", help="O que o agente deve fazer")

    # Argumento opcional: força skills específicas, ignorando a seleção automática
    parser.add_argument(
        "--skills", nargs="*",
        help=(
            "Força skills específicas (sem extensão). "
            "Se omitido, o agente seleciona automaticamente. "
            "Ex: --skills docx crm-omnichannel-analysis"
        )
    )

    # Flag opcional: modo verbose para debug
    parser.add_argument("--verbose", action="store_true", help="Mostra seleção de skills, tool calls e resultados")

    args = parser.parse_args()

    # Se --skills não for passado, skills=None → seleção automática
    # Se --skills for passado sem valores (--skills), skills=[] → nenhuma skill
    run_agent(args.prompt, skills=args.skills, verbose=args.verbose)