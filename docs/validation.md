# Validação ponta a ponta

Validação realizada em **14/10/2026**. Esta página registra o escopo; ela não
contém tokens, IDs de chat, enunciados, nomes de alunos ou entregas pessoais.

| Fluxo | Verificação | Resultado |
|---|---|---|
| MCP stdio → Canvas autenticado | Inicialização, lista de ferramentas, cursos, atividades, prazos, módulos e páginas | Passou; conteúdo completo nas ferramentas de detalhe |
| GitHub Actions → Canvas → Telegram | Execução manual do mesmo workflow diário habilitado às 08h | Passou; Telegram confirmou o envio e o usuário recebeu o resumo |
| Telegram → Codex → MCP → Canvas → Telegram | Mensagem real do usuário solicitando apenas consulta dos próximos sete dias | Passou; chamada MCP concluída e resposta final do agente |
| Escopo e datas | Consulta `all_courses=true`, `period=next_7_days` | O agente e o lembrete retornaram a mesma quantidade de atividades |
| Setup | Provedor/conta, cancelamento, salvar sem iniciar, troca e modo | Testes simulados passam; login só abre após a escolha |
| Escritas Canvas e automático | HTTP/modelos simulados, verificação de entrega e ledger | Testes passam; nenhuma entrega real usada como teste |
| Claude Telegram | Implementação oficial Channels e testes simulados | Não validado ao vivo: política Team bloqueou Channels |
| Imagem MCP e distribuições | Versão, protocolo stdio, catálogo offline e ausência de arquivos privados | Passou em amd64 e arm64 pelo workflow de release |
| MCP Docker → Canvas real | Mesmas leituras da instalação local, com o `.env` privado | Passou; prazos de todas as matérias coincidiram com o agente/lembrete |
| Publicação GHCR | Consulta anônima ao manifest da imagem | Passou; download público sem autenticação |
| Pacotes publicados 0.5.2 | Download do wheel/imagem, SHA256SUMS e consultas reais no Canvas | Passou; handshake anuncia 0.5.2 e os dois retornaram os mesmos prazos |

Execução de lembrete validada:
[Daily Canvas reminder](https://github.com/arthurcuri/mcp-instructure-canvas/actions/runs/38508719491).
Release e testes dos pacotes:
[Release and GitHub Packages 0.5.2](https://github.com/arthurcuri/mcp-instructure-canvas/actions/runs/38560983173).
O workflow permanece diário, em `America/Sao_Paulo`; o semanal está desativado
nesta instalação. O agendador pode atrasar, conforme as regras do GitHub Actions.

No teste da conversa, o Codex foi autenticado com ChatGPT. O histórico persistido
registrou uma chamada `get_due_assignments` concluída, com os argumentos acima,
e um turno concluído com resposta final, cuja chegada foi confirmada pelo usuário. A inspeção mostrou apenas status,
nomes de ferramentas e contagens; não publicou conteúdo da matéria.

## Reproduzir na sua instalação

```sh
uv sync --locked
uv run canvas-mcp-server --test
uv run python scripts/verify_mcp.py
uv run canvas-agent status
```

Para verificar também o Canvas através da imagem, com seu `.env` local e Docker
ativo, use `uv run python scripts/verify_mcp.py --container ghcr.io/arthurcuri/mcp-instructure-canvas:v0.5.2`.

O teste MCP ao vivo é de leitura. Para a entrada real do Telegram, o próprio
dono do chat envia um pedido de consulta ao bot; a Bot API não permite ao servidor
enviar uma mensagem em nome do usuário. Não rode dois consumidores `getUpdates`.

Para o lembrete, execute **Daily Canvas reminder → Run workflow** no seu GitHub
e confira o resumo recebido no Telegram. Isso envia uma mensagem real ao chat
configurado; não chama um modelo.

## O que esta validação não afirma

- Não demonstra permissão para cada endpoint de professor/administrador: a conta
  continua limitada pelas permissões que o Canvas concede.
- Não demonstra entregas reais automáticas: a validação não modifica notas,
  atividades ou submissões, e não ativa `CANVAS_AGENT_AUTO` na instalação pessoal.
- Não demonstra Claude Channels liberado pelo Team: o administrador precisa
  habilitar a política para testar esse receptor na instituição.
- Não garante execução local com o Mac dormindo/desligado. O lembrete na nuvem
  continua independente do agente local.
