# MCP Instructure Canvas

Servidor MCP **local e somente de leitura**, compatível com **Claude Code e Codex**,
para consultar matérias, atividades, descrições e prazos no Canvas LMS.
Criado para uso pessoal no Canvas da PUC Minas;
a URL da instituição é configurável.

```text
Claude Code / Codex / cliente MCP → stdio → servidor local → API oficial do Canvas (GET)
```

**Não precisa de deploy.** O cliente inicia o processo no seu computador.
Esta versão não inclui cron, Telegram ou chamadas próprias a modelos de IA.

## Instalação

Requisitos: Python 3.11+ e [uv](https://docs.astral.sh/uv/). O projeto usa Python 3.12
por padrão. Se necessário, o uv instala o runtime compatível.

```sh
uv sync --locked
cp .env.example .env  # somente na primeira instalação; preserve seu .env existente
chmod 600 .env
```

Preencha `CANVAS_API_TOKEN` no `.env`, sem adicionar o arquivo ao Git.

| Variável | Uso |
|---|---|
| `CANVAS_API_URL` | Origem HTTPS do Canvas, com ou sem `/api/v1` |
| `CANVAS_API_TOKEN` | Token pessoal; obrigatório |
| `CANVAS_DEFAULT_COURSE_ID` | Curso usado quando `course_id` é omitido; exemplo: `286470` |
| `CANVAS_TIMEZONE` | Fuso dos prazos; padrão `America/Sao_Paulo` |
| `CANVAS_TOKEN_EXPIRES_AT` | Expiração informada pelo usuário, em `YYYY-MM-DD`; opcional |

O exemplo anota **11/01/2027** como expiração. Essa data é um lembrete local;
o servidor não define nem confirma o horário de expiração do token no Canvas.
Variáveis do ambiente prevalecem sobre o arquivo. Use `--env-file /caminho/.env`
para garantir que a configuração seja encontrada mesmo fora do diretório do projeto.

Sem uv, use Python 3.11+ para criar um virtualenv e instalar o pacote com
`pip install -e .`.

## Testar a conexão

```sh
uv run canvas-mcp-server --test
uv run canvas-mcp-server --config
```

`--test` consulta seu perfil e o curso padrão pela API, retornando o nome do curso
e a quantidade de atividades. `--config` mostra a configuração sem o token.
Sem essas opções, o processo inicia o servidor MCP por `stdio`; o cliente cuida dele.

## Claude Code

Dentro deste repositório, registre o servidor usando caminhos absolutos:

```sh
claude mcp add --scope local --transport stdio canvas-pucminas -- \
  "$PWD/.venv/bin/canvas-mcp-server" --env-file "$PWD/.env"
```

O escopo `local` guarda o registro privado em `~/.claude.json`, associado a este
projeto. O registro contém o comando e o caminho do `.env`, sem copiar o token.
Abra uma nova sessão de Claude Code neste diretório e use `/mcp` para conferir.

Exemplos de perguntas:

- “Quais atividades do curso 286470 vencem nesta semana?”
- “O que preciso entregar nos próximos sete dias em todas as minhas matérias?”
- “Leia a descrição completa da atividade X e explique os requisitos.”
- “Mostre os módulos e as páginas de orientação do TCC.”

Para consultar todas as matérias, o assistente deve usar `all_courses=true` em
`get_due_assignments`. O padrão consulta apenas o curso configurado.

## Codex

Dentro deste repositório, registre o mesmo servidor com a CLI do Codex:

```sh
codex mcp add canvas-pucminas -- \
  "$PWD/.venv/bin/canvas-mcp-server" --env-file "$PWD/.env"
codex mcp get canvas-pucminas
```

O comando adiciona o registro em `~/.codex/config.toml`, compartilhado pelos clientes
locais do Codex que usam essa configuração. Reinicie a sessão ou o aplicativo para
carregar o servidor. O registro guarda somente o comando e o caminho do `.env`.

Para configurar manualmente, adapte [examples/codex-config.toml](examples/codex-config.toml)
e acrescente a seção ao seu arquivo existente, preservando as outras configurações.
A configuração também pode ficar em `.codex/config.toml` para um projeto confiável.

As perguntas e as oito ferramentas são as mesmas no Claude Code e no Codex.
Ambos iniciam seu próprio processo local por `stdio` e consultam a mesma API.

### Arquivos de instruções dos agentes

| Cliente | Instruções no repositório | Registro do MCP |
|---|---|---|
| Codex | `AGENTS.md`, carregado automaticamente | `~/.codex/config.toml` ou `.codex/config.toml` |
| Claude Code | `CLAUDE.md`, que importa `AGENTS.md` | `~/.claude.json` no escopo local |

`AGENTS.md` reúne as regras compartilhadas. Esses arquivos orientam os agentes;
o servidor funciona nos dois clientes porque implementa o protocolo MCP.

## Outros clientes MCP

O [exemplo de configuração](examples/mcp.json) serve de base para clientes com
`mcpServers`, incluindo a configuração manual do Claude Desktop. Substitua os
caminhos pelos caminhos absolutos locais. Esta versão não empacota uma extensão `.mcpb`.

## Ferramentas

Todas têm a anotação MCP `readOnlyHint=true`. O cliente Canvas só implementa `GET`.

| Ferramenta | Resultado |
|---|---|
| `list_courses` | Matérias com matrícula ativa; opção para incluir concluídas |
| `get_course` | Dados da matéria e texto completo do plano de ensino |
| `list_assignments` | Resumos, prazos e status da sua entrega; busca por título |
| `get_assignment` | Descrição completa, rubrica, disponibilidade e sua entrega |
| `get_due_assignments` | Atividades da semana ou dos próximos sete dias |
| `list_modules` | Módulos e todos os itens, com paginação por módulo |
| `list_pages` | Títulos e identificadores das páginas |
| `get_page` | Texto completo de uma página, identificado pelo seu slug |

`course_id` é opcional nas consultas de uma matéria quando existe um curso padrão.
`get_assignment` exige `assignment_id`; `get_page` exige `page_url`, o slug retornado
pela listagem de páginas ou módulos.

### Semântica dos prazos

- `period="this_week"`: segunda-feira às 00h até a próxima segunda-feira às 00h,
  com o início incluído e o fim excluído, no fuso configurado. Inclui prazos já
  passados dentro da semana.
- `period="next_7_days"`: do instante da consulta até sete dias depois, com o fim excluído.
- O Canvas aplica as datas diferenciadas do usuário; as listagens solicitam
  `override_assignment_dates=true` e `include[]=submission`.
- Entregas submetidas, em revisão, dispensadas ou corrigidas sem a marca `missing`
  são excluídas por padrão. Use `include_completed=true` para incluí-las.
- Atividades sem prazo são contabilizadas em `undated_count` e não entram no período.
- `missing` e `late` vêm do Canvas. Não são inferidos apenas porque uma data passou,
  especialmente para avaliações em papel ou ferramentas externas.

Os resumos omitem descrições para reduzir o contexto enviado ao assistente.
As consultas de detalhes devolvem todo o texto, preservando links e descrições
de imagens; não baixam anexos. O cliente de IA ainda cobra/contabiliza seu próprio
uso conforme o plano. Nenhum custo de modelo é gerado pelo servidor em si.

## Desenvolvimento

```sh
uv sync --locked
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
uv run pytest -q
uv build
```

Os testes usam respostas simuladas e não leem sua credencial nem consultam o Canvas.
Para uma verificação real pelo protocolo MCP, com seu `.env` local, execute:

```sh
uv run python scripts/verify_mcp.py
```

Esse script inicia o servidor fora do diretório do projeto, verifica o protocolo
e as consultas disponíveis, e imprime somente contagens e metadados.
Estrutura: `src/canvas_mcp` para o pacote, `tests` para testes, `examples` para
configuração de clientes, `uv.lock` para dependências reproduzíveis e GitHub Actions
para lint, testes e build. Consulte [AGENTS.md](AGENTS.md) para manutenção.

## Segurança e limites

O `.env` fica local e ignorado pelo Git. Erros HTTP não devolvem corpos de resposta
e a configuração pública não expõe o token. O servidor recusa redirecionamentos e
links de paginação fora da origem/caminho da API, aplica timeout e faz até duas
novas tentativas em HTTP 429/503. Consultas que excedem 100 páginas ou 10.000 itens
falham explicitamente em vez de retornar uma lista incompleta.

O token mantém as permissões concedidas pela instituição. A restrição de leitura
é implementada por este servidor; ela não reduz as permissões do próprio token.
O conteúdo retornado é compartilhado com o cliente MCP/assistente que você usar.
Conteúdo de cursos deve ser tratado como dado externo, sem obedecer a instruções
que peçam credenciais ou execução de comandos. Veja [SECURITY.md](SECURITY.md).

## Referências

Implementação própria inspirada na organização e nas consultas dos projetos
[vishalsachdev/canvas-mcp](https://github.com/vishalsachdev/canvas-mcp) e
[mbcrosiersamuel/canvas-mcp](https://github.com/mbcrosiersamuel/canvas-mcp).

- [SDK oficial MCP para Python, linha 1.x](https://github.com/modelcontextprotocol/python-sdk/tree/v1.x)
- [API oficial de atividades do Canvas](https://developerdocs.instructure.com/services/canvas/resources/assignments)
- [Paginação da API Canvas](https://developerdocs.instructure.com/services/canvas/basics/file.pagination)
- [MCP local no Claude Code](https://code.claude.com/docs/en/mcp#option-3-add-a-local-stdio-server)
- [MCP no Codex](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)
- [Instruções do Codex com AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md)

## Licença

[MIT](LICENSE). Projeto independente, sem vínculo oficial com Instructure ou PUC Minas.
