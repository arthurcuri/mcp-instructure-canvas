# Changelog

Este projeto usa versionamento semântico. Até a versão 1.0, interfaces podem mudar
entre versões menores; as instruções de migração aparecem nas notas da release.

## 0.5.2 — 2026-10-14

- O handshake MCP anuncia a versão do projeto, em vez da versão do SDK.
- Publicação OCI preserva descrição, licença e origem no índice multiarch do GHCR;
  o workflow verifica esses metadados antes de criar a release.
- Validação do wheel/imagem baixados e confirmação da resposta final pelo usuário.
- Documentação de visibilidade ajustada após confirmar download público sem login.

## 0.5.1 — 2026-10-14

- Distribuição do MCP pelo GitHub Container Registry para Linux amd64/arm64,
  com imagens base fixadas por digest e teste do protocolo antes da publicação.
- Releases com wheel, pacote fonte e SHA256SUMS, verificando versões e ausência
  de arquivos privados antes do upload.
- Metadados Python e GitHub atualizados para apresentar as três funcionalidades:
  MCP Canvas, lembretes Telegram e agente local Codex/Claude.
- Guia de instalação dos pacotes e relatório de validação ponta a ponta.

## 0.5.0 — 2026-10-14

- `canvas-agent setup`: escolha explícita de provedor/conta, login oficial,
  modo manual/automático e revisão antes de salvar ou iniciar.
- Preferência `CANVAS_AGENT_PROVIDER` no `.env`, sem provedor implícito em `start`.
- Status dos dois receptores, saída `--json` para scripts e login separado do início.
- Cancelamento e opção de salvar sem alterar serviços existentes.

## 0.4.0 — 2026-10-14

- Trabalhador diário local com `CANVAS_AGENT_AUTO=true`, registro de tentativas,
  verificação independente da submissão e ausência de reexecução automática.
- Recuperação de conversas Codex provisórias sem histórico; preservação de
  conversas reais e operações com resultado incerto.
- README visual com arquitetura, instalação e três fluxos independentes.

## 0.3.0 — 2026-10-13

- Receptor privado Telegram/Codex usando login ChatGPT e Codex App Server.
- Suporte ao plugin Telegram oficial do Claude Code, sujeito à política de Channels.
- LaunchAgent no macOS, conversa persistente, aprovações e anexos de trabalhos.

## 0.2.0 — 2026-10-13

- Official bundled REST catalog: 1,118 operations across 144 groups, with offline discovery.
- Generic GET/POST/PUT/PATCH/DELETE execution, JSON/forms/multipart/raw/binary bodies.
- 18 MCP tools, including GraphQL queries/mutations, file transfers and assignment submission.
- Optional read-only mode hides four mutation tools and blocks HTTP writes.
- Token-free storage transfer clients; writes never retry automatically.
- Optional Telegram deadline reminders, private chat-ID discovery and a gated weekly Actions workflow.
- Mocked coverage of the entire method/route inventory and functional write/transfer/GraphQL tests.
- Detailed API, Telegram and free standard-runner scheduling guides.
- Telegram replies and LLM integration remain pending; no scheduler is activated by installation.

- Contributor guidance and MCP templates for Claude Code, Codex, Gemini CLI, Cursor and Kiro.
- Detailed token generation, installation, client setup and local-runtime documentation.
- Personal expiration annotations removed from public examples; private configs/reports ignored.
- Optional weekly deadline snapshots and launchd/cron examples in the same repository.

## 0.1.0 — 2026-10-13

- Local stdio MCP with eight read-only course, assignment, deadline and content tools.
- Canvas GET client with pagination, same-origin checks, bounded retries and sanitized errors.
- Compact deadline summaries and complete assignment/page text with retained links.
- São Paulo weekly windows, effective student dates and own submission status.
- Explicit `.env` configuration, declared token-expiry reminder and safe CLI diagnostics.
- Mocked unit/protocol tests, optional live MCP verification, client examples and CI.
- Claude Code and Codex setup guides, shared AGENTS.md instructions and a Codex TOML example.
