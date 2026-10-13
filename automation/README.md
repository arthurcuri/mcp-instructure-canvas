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
| Enviar mensagem ao Telegram | Pendente |
| Receber a resposta do usuário no Telegram | Pendente |
| Chamar Claude Code para ajudar com a atividade | Pendente |

Nenhum job é instalado durante `uv sync`, o registro do MCP ou os testes. Os
modelos abaixo executam apenas a checagem local. Não enviam mensagens nem iniciam IA.

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
Depois de concluirmos o envio ao Telegram, uma tarefa poderá usar o MCP local.
Pelo `/loop` da CLI, a sessão precisa continuar em execução; veja a
[comparação de agendamentos](https://code.claude.com/docs/en/scheduled-tasks).

Para lembretes, a checagem atual não chama modelos e não consome tokens de IA.
Se acrescentarmos Claude Code, a execução terá o consumo do cliente/modelo.

## Próxima etapa: Telegram

Ainda faltam o bot, as credenciais locais, o envio, o tratamento das respostas
e a integração opcional com Claude Code. Não há comando de envio funcional nesta
versão. Credenciais futuras e qualquer conversa/relatório devem permanecer em
arquivos ignorados, fora dos modelos públicos de configuração.
