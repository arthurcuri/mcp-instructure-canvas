# Canvas MCP

**Conecte seu assistente de IA ao Canvas LMS. Consulte matérias, atividades e prazos, use a API e receba lembretes opcionais no Telegram.**

[English](README.md) · [Instalação detalhada](docs/setup.md) · [API](docs/api.md) · [Como contribuir](CONTRIBUTING.md)

Projeto independente com licença MIT, compatível com instituições que usam Canvas. Configure a URL HTTPS da sua instituição e seu próprio token. O servidor funciona localmente por stdio, com clientes como Claude Code, Codex, Claude Desktop, Gemini CLI, Cursor e Kiro.

A documentação principal e o idioma padrão do programa são em inglês. As notificações podem usar português com `CANVAS_NOTIFICATION_LANGUAGE=pt-BR`. Conteúdos consultados no Canvas mantêm o idioma original, e o agente responde no idioma do usuário. Respostas de aprovação em português e o marcador de anexos `[[arquivo: ...]]` continuam aceitos.

## Funcionalidades

| Componente | O que faz | Onde executa |
|---|---|---|
| MCP do Canvas | Consulta cursos, atividades, rubricas, módulos e páginas; usa REST, GraphQL e arquivos | Processo iniciado pelo cliente MCP |
| Lembretes opcionais | Envia prazos e novidades da semana: anúncios, fóruns, páginas, arquivos e outras publicações, sem chamadas a modelos | GitHub Actions ou agendador local |
| Agente opcional | Ajuda por Telegram, prepara arquivos e envia atividades quando autorizado | Seu computador, com Codex ou Claude Code |

São **18 ferramentas**, ou **14 no modo somente leitura**, e um catálogo de **1.118 operações REST em 144 grupos**, capturado em 13/10/2026. A conta mantém as permissões da instituição. Cobertura do catálogo não significa teste real de todos os endpoints.

A instalação não ativa agendamentos, agentes ou entregas automáticas. O MCP não chama modelos; o assistente que usa suas ferramentas pode consumir a própria quota.

## Instalação rápida

Requisitos: Git, Python 3.11+ e [uv](https://docs.astral.sh/uv/getting-started/installation/). Os comandos abaixo são para macOS/Linux. O checkout solicita Python 3.12, que o uv pode instalar.

```sh
git clone https://github.com/arthurcuri/mcp-instructure-canvas.git
cd mcp-instructure-canvas
uv sync --locked
if [ ! -f .env ]; then cp .env.example .env; fi
chmod 600 .env
```

Edite seu `.env` privado:

```dotenv
CANVAS_API_URL=https://canvas.example.edu/api/v1
CANVAS_API_TOKEN=seu-token-pessoal
CANVAS_TIMEZONE=America/Sao_Paulo
CANVAS_READ_ONLY=true
```

Substitua a URL pela instituição. Gere o token em **Canvas → Conta → Configurações → Integrações aprovadas → Novo token de acesso**, quando permitido. Se a opção não existir, consulte o administrador. Não coloque o token em configurações de clientes nem em comandos de registro.

```sh
uv run canvas-mcp-server --test
```

Na raiz do projeto, escolha o comando do seu cliente:

```sh
# Claude Code
claude mcp add --scope local --transport stdio canvas -- \
  "$PWD/.venv/bin/canvas-mcp-server" --env-file "$PWD/.env"
```

```sh
# Codex
codex mcp add canvas -- \
  "$PWD/.venv/bin/canvas-mcp-server" --env-file "$PWD/.env"
```

Reinicie o cliente e confira `/mcp`. Se sua instalação já usa `canvas-pucminas`, preserve esse registro para evitar duplicação. O nome é apenas um identificador local; a instituição vem de `CANVAS_API_URL`.

Sem `CANVAS_DEFAULT_COURSE_ID`, informe `course_id` nas ferramentas ou `all_courses=true` na consulta de prazos. Para escrita, habilite deliberadamente `CANVAS_READ_ONLY=false`, reconecte o MCP e peça a ação. Upload de arquivo e entrega de atividade são operações separadas. Após falha de escrita, confira o Canvas antes de repetir.

## Guias

- [Configuração e outros clientes](docs/setup.md)
- [Ferramentas e API](docs/api.md)
- [Telegram e agendamento](automation/README.md)
- [Agentes, aprovações e modo automático](docs/agents.md)
- [Pacotes e Docker](docs/packages.md)
- [Registro de validação e limites](docs/validation.md)
- [Segurança](SECURITY.md)

## Contribua

Correções, testes, documentação e traduções são bem-vindos. **Não é preciso ter conta Canvas, bot ou assinatura de IA para executar os testes.** Consulte [CONTRIBUTING.md](CONTRIBUTING.md), o [roadmap](ROADMAP.md) e o [Código de Conduta](CODE_OF_CONDUCT.md). Relatos em português também são aceitos.

[Licença MIT](LICENSE). Sem vínculo oficial com Instructure ou instituições de ensino.
