# Automação semanal

Esta pasta pertence ao mesmo repositório do MCP. Um agendamento pode chamar um
comando local sem precisar de outro repo; versionar o script aqui facilita sua manutenção.

## Estado atual

| Parte | Estado |
|---|---|
| Consultar prazos e status da própria entrega | Implementado |
| Gerar um relatório JSON privado | Implementado em `canvas-weekly-check` |
| Executar a checagem pelo shell | Implementado em `run_weekly.sh` |
| Modelo semanal de launchd ou cron | Disponível, não ativado automaticamente |
| Enviar mensagem ao Telegram | Implementado, opt-in com `--telegram` |
| Workflow semanal no GitHub Actions | Disponível, schedule condicionado a variável explícita |
| Receber a resposta do usuário no Telegram | Pendente |
| Chamar Claude Code para ajudar com a atividade | Pendente |

Nenhum job é instalado durante `uv sync`, o registro do MCP ou os testes. Os
modelos locais executam a checagem; acrescentar `--telegram` habilita o envio ao
chat configurado. Nenhum caminho inicia IA automaticamente.

## 1. Testar antes de agendar

Conclua a instalação, o preenchimento do `.env` e `canvas-mcp-server --test` conforme
o [README principal](../README.md). Na raiz do projeto:

```sh
uv run canvas-weekly-check --output .local/weekly-report.json
bash automation/run_weekly.sh
```

O padrão verifica o curso do `.env` e os próximos sete dias. Para todas as matérias:

```sh
bash automation/run_weekly.sh --all-courses
```

Outras opções: `--course-id 12345`, `--period this_week` e `--include-completed`.
Escolha entre `--course-id` e `--all-courses`. O relatório inclui o instante da
consulta, o período, os cursos verificados e os resumos das atividades.

O JSON fica em `.local/weekly-report.json`, ignorado pelo Git e com permissão `600`.
Se o Canvas falhar, o comando retorna erro e preserva o relatório anterior;
confira `checked_at` antes de usar um relatório existente.

O launcher encontra o uv no PATH ou nos locais usuais de instalação. Se necessário,
defina `CANVAS_UV_BIN` com o caminho absoluto do executável, também no ambiente do job.
Ele encontra a raiz do repositório mesmo se o agendador iniciar em outro diretório.

## 2. Agendamento no macOS com launchd

O modelo executa às **segundas-feiras, 09h, no fuso do macOS**. O fuso do agendamento
é o do sistema; `CANVAS_TIMEZONE` controla a interpretação dos prazos do relatório.
A Apple documenta [jobs temporizados com launchd](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/CreatingLaunchdJobs.html).

### Preparar um arquivo local

Na raiz do repo, prepare os diretórios:

```sh
mkdir -p .local "$HOME/Library/LaunchAgents"
chmod 700 .local
```

Crie uma cópia do modelo, substituindo os caminhos e mantendo as notas pessoais
fora do Git. Este comando **apenas prepara o arquivo**, sem ativar o agendamento:

```sh
uv run python automation/prepare_launchd.py
plutil -lint .local/com.canvas-mcp.weekly.plist
```

Edite `StartCalendarInterval` nessa cópia para mudar dia/hora. Para preparar o
modelo com todas as matérias, use `prepare_launchd.py --all-courses`.
O `Weekday` usa `1` para segunda-feira e `0` ou `7` para domingo.

### Ativar quando estiver pronto

Os comandos abaixo ativam **a geração de relatórios locais**:

```sh
cp .local/com.canvas-mcp.weekly.plist "$HOME/Library/LaunchAgents/com.canvas-mcp.weekly.plist"
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.canvas-mcp.weekly.plist"
launchctl print "gui/$(id -u)/com.canvas-mcp.weekly"
```

Para executar uma vez sem esperar segunda-feira:

```sh
launchctl kickstart "gui/$(id -u)/com.canvas-mcp.weekly"
```

Confira o JSON e os logs locais. Se modificar a cópia instalada, descarregue o
job com `bootout`, copie a versão atualizada e repita `bootstrap`.

### Desativar

```sh
launchctl bootout "gui/$(id -u)/com.canvas-mcp.weekly"
rm "$HOME/Library/LaunchAgents/com.canvas-mcp.weekly.plist"
```

Como LaunchAgent, o job depende da sessão do usuário. O Mac desligado não executa
o job. O `launchd` reúne eventos de calendário perdidos durante o sono e executa
ao acordar; a consulta ao Canvas precisa de internet. Não há servidor hospedado.

## 3. Alternativa com cron

Teste o launcher manualmente, execute `crontab -e` e acrescente a linha de
[crontab.example](crontab.example), substituindo o caminho absoluto. Preserve as
outras entradas: não use um comando que sobrescreva o crontab completo.

```sh
crontab -e
crontab -l
```

Para desativar, remova apenas essa linha com `crontab -e`. Use cron **ou** launchd
para evitar execuções duplicadas. Cron pode perder o horário enquanto o Mac dorme;
por isso, o modelo launchd é a opção indicada aqui para macOS.

## 4. Opção pelo Claude Code Desktop

O [Claude Code Desktop permite tarefas persistentes](https://code.claude.com/docs/en/desktop-scheduled-tasks).
Uma tarefa pode usar o MCP local ou executar `canvas-weekly-check --telegram`.
Pelo `/loop` da CLI, a sessão precisa continuar em execução; veja a
[comparação de agendamentos](https://code.claude.com/docs/en/scheduled-tasks).

Para lembretes, a checagem atual não chama modelos e não consome tokens de IA.
Se acrescentarmos Claude Code, a execução terá o consumo do cliente/modelo.

## Telegram: configurar o bot

1. No Telegram, abra o bot oficial [@BotFather](https://t.me/BotFather).
2. Envie `/newbot`, escolha o nome e o username e copie o token fornecido.
3. No editor do seu `.env` privado, preencha `TELEGRAM_BOT_TOKEN`. Não coloque o
   token em um comando, URL de navegador, arquivo público ou screenshot.
4. Abra a conversa com o bot recém-criado e envie `/start`.
5. Na raiz do projeto, obtenha somente os IDs dos chats privados que escreveram ao bot:

   ```sh
   uv run canvas-telegram-chats --env-file .env
   ```

6. Copie o ID da sua conversa para `TELEGRAM_CHAT_ID` no mesmo `.env`. Se houver
   vários IDs, confirme qual é o seu; não configure o chat de outra pessoa.
7. Faça um teste de envio explícito:

   ```sh
   bash automation/run_weekly.sh --all-courses --telegram
   ```

A mensagem mostra nomes, prazos locais e links. Pergunta se você quer ajuda;
receber/tratar a resposta e executar Claude Code ainda não estão implementados.
Sem `--telegram`, nenhuma mensagem é enviada, mesmo com os secrets preenchidos.
O comando `canvas-telegram-chats` consulta `getUpdates` sem consumir updates por
offset nem enviar mensagens. Use um bot dedicado, sem webhook ou outro consumidor
de updates durante a configuração. Depois que os updates expirarem, envie `/start` novamente.

O envio usa texto simples e desativa previews de links. Relatórios extensos
são divididos em mensagens. Não há retry automático: uma falha de rede pode
ocorrer depois da entrega; confira o chat antes de repetir. Se várias mensagens
forem necessárias, uma falha pode deixar um envio parcial.

Para incluir Telegram no launchd, edite **a cópia privada** do plist e acrescente
`--telegram` no array `ProgramArguments`, depois faça `bootout`/`bootstrap`.
No cron, acrescente `--telegram` ao final dos argumentos do launcher. Evite
manter o job local e o do GitHub habilitados juntos para não duplicar lembretes.

Referências: [criação de bots](https://core.telegram.org/bots/tutorial),
[getUpdates](https://core.telegram.org/bots/api#getupdates) e
[sendMessage](https://core.telegram.org/bots/api#sendmessage).

## 5. GitHub Actions sem o Mac ligado

O [workflow](../.github/workflows/weekly-canvas.yml) faz a consulta diretamente
à API, sem depender de Claude Code aberto, processo MCP permanente ou deploy.
Ele roda **segunda-feira, 09h17, America/Sao_Paulo**, em um runner temporário.
A instalação e o push não preenchem secrets nem habilitam o schedule.

### Configurar e testar

1. No repositório GitHub, abra **Settings → Secrets and variables → Actions**.
2. Na aba **Secrets**, clique **New repository secret** e cadastre:

   | Nome | Valor |
   |---|---|
   | `CANVAS_API_TOKEN` | Seu token do Canvas |
   | `TELEGRAM_BOT_TOKEN` | Token do BotFather, se quiser mensagens |
   | `TELEGRAM_CHAT_ID` | ID da sua conversa com o bot, se quiser mensagens |

3. Na aba **Variables**, você pode configurar `CANVAS_API_URL` e
   `CANVAS_TIMEZONE`. Os padrões são a PUC Minas e `America/Sao_Paulo`.
4. Em **Actions**, escolha **Weekly Canvas reminder → Run workflow**, usando
   a branch padrão. Essa execução manual funciona antes de habilitar o schedule.
5. Verifique o job e o Telegram. Sem os dois secrets do Telegram, o job apenas
   gera o relatório se ambos estiverem vazios. Se só um estiver preenchido, ele
   falha antes da consulta, indicando a configuração faltante.
6. Quando estiver pronto, crie **em Variables** `CANVAS_WEEKLY_ENABLED` com
   valor exatamente `true`. Isso habilita as execuções semanais.

O token passa a ficar também sob os controles de secrets do GitHub, além da sua
máquina. Cadastre apenas os valores necessários: não faça upload do `.env`.
Não foram cadastrados secrets nem ativada a variável por este projeto.

O workflow verifica todas as matérias ativas nos próximos sete dias e força
`CANVAS_READ_ONLY=true`. Gera um JSON privado no runner e registra somente
contagens. Não faz upload de artifacts, não persiste dados do curso em cache e
não faz commit de relatórios. O relatório desaparece ao fim do runner.
Se configurar os secrets do bot, o envio é automático nesse job: não exige IA.

### Custo

Runners **padrão**, como o `ubuntu-latest` utilizado, são gratuitos em repositórios
públicos. Este repositório é público. Repositórios privados usam a cota do plano
(GitHub Free inclui 2.000 minutos/mês); excedentes e runners maiores podem gerar
cobrança. Não há chamadas a provedores de IA nem cobrança de tokens neste fluxo.
Adicionar Claude/API de IA exige avaliar os custos e a autenticação desse serviço
separadamente. Confira a [política oficial](https://docs.github.com/en/billing/concepts/product-billing/github-actions).

### Horário, limites e desativação

O horário usa o campo `timezone` do schedule. Mudar `CANVAS_TIMEZONE` altera as
datas do relatório, sem alterar o fuso definido no YAML. Para mudar dia/hora,
edite `cron` no workflow. O minuto 17 evita o início da hora, período de maior carga.
GitHub Actions pode atrasar ou descartar uma execução sob carga; não é um alarme
com horário garantido. Schedules usam a branch padrão e repositórios públicos
podem ter o agendamento desativado após **60 dias sem atividade**.
Veja a [documentação oficial](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).

Para desativar as consultas automáticas, remova a variável ou defina
`CANVAS_WEEKLY_ENABLED=false`. Para desativar o workflow inteiro, inclusive
execuções manuais, use **Actions → Weekly Canvas reminder → menu → Disable workflow**.
Se o GitHub o desativar por inatividade, use **Enable workflow** no mesmo menu
e mantenha a variável habilitada. Reexecuções manuais podem enviar o mesmo
relatório de novo; não há controle persistente de deduplicação nesta versão.

## Próxima etapa: respostas e Claude Code

O bot recebe mensagens no Telegram, mas este projeto ainda não processa respostas,
não executa atividades por conta própria e não inicia Claude Code quando alguém
responde. Essa integração poderá ficar no mesmo repositório, com autorização
explícita para cada envio de atividade e um orçamento de uso do modelo.
