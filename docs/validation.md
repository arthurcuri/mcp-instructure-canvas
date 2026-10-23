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

## Aprovações e contexto — 23/10/2026

A versão 0.5.3 foi verificada com testes simulados para respostas Sim/Não,
formulários com campos, expiração, múltiplas solicitações, outro usuário,
correções no turno ativo e preservação da referência à atividade. O relay usa
os contratos de elicitação e `turn/steer` do
[Codex App Server](https://learn.chatgpt.com/docs/app-server).

O protocolo MCP 0.5.3 passou na consulta autenticada somente de leitura, mantendo
18 ferramentas e o conteúdo completo nos detalhes. A consulta dos próximos sete
dias incluiu todas as matérias. Wheel e arquivo fonte passaram na auditoria de
versões, catálogo e exclusão de arquivos privados.

O runtime pessoal foi atualizado e reiniciado com conversa/arquivos preservados,
Telegram conectado e modo automático desativado. A inspeção do histórico mostrou
que os turnos anteriores continuavam salvos; o lembrete enviado na nuvem não é
uma mensagem de entrada para o agente. O teste humano de uma nova aprovação pelo
Telegram é separado dos testes simulados; nenhuma entrega Canvas é usada para
validar a correção.

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

## Pontualidade do agendamento

Em **14/10/2026**, o workflow configurado para as 08h de São Paulo foi criado
às **12h43min55s**, e o Telegram confirmou o envio às **12h44min17s**. O evento
registrado foi `schedule`, não `workflow_dispatch`. A criação tardia do run
mostra que o disparo chegou depois do horário solicitado; depois de criado,
o job iniciou em dois segundos e terminou com sucesso.

Evidência: [execução automática atrasada](https://github.com/arthurcuri/mcp-instructure-canvas/actions/runs/38591893378).
O log registrou somente contagens e a confirmação de uma mensagem; não houve
falha registrada de autenticação Canvas ou Telegram nessa execução.

O teste manual anterior comprovou consulta/envio, não pontualidade do cron.
A execução automática confirmou o envio diário, com atraso; essa evidência
não garante entrega pontual às 08h nas próximas execuções.
O GitHub documenta que `schedule` pode atrasar ou perder disparos sob carga,
especialmente no início da hora; o motivo específico deste atraso não aparece
no histórico disponível. Veja [schedule](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).

Para inspecionar o disparo:

```sh
gh run list --workflow daily-canvas.yml --limit 10 \
  --json databaseId,event,createdAt,startedAt,conclusion,url
```

Os timestamps da API estão em UTC; converta para o fuso escolhido no workflow.
Um `workflow_dispatch` bem-sucedido não comprova que um `schedule` disparou no horário.

## O que esta validação não afirma

- Não demonstra permissão para cada endpoint de professor/administrador: a conta
  continua limitada pelas permissões que o Canvas concede.
- Não demonstra entregas reais automáticas: a validação não modifica notas,
  atividades ou submissões, e não ativa `CANVAS_AGENT_AUTO` na instalação pessoal.
- Não demonstra Claude Channels liberado pelo Team: o administrador precisa
  habilitar a política para testar esse receptor na instituição.
- Não garante execução local com o Mac dormindo/desligado. O lembrete na nuvem
  continua independente do agente local.
