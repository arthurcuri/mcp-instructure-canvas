# MCP Instructure Canvas

Servidor MCP **local, com leitura, escrita e envio de atividades**, para a API
oficial do Canvas LMS. O catálogo embarcado cobre **1.118 operações REST em 144
grupos**, com ferramentas adicionais para GraphQL e transferência de arquivos.
Pode ser conectado a Claude Code,
Codex, Gemini CLI, Cursor, Kiro ou outro cliente com suporte a MCP por `stdio`.
A URL é configurável; o exemplo usa a instância da PUC Minas.

## Como funciona e por que não precisa de deploy

```text
Cliente de IA → processo MCP no seu computador → API HTTPS do Canvas
```

O cliente executa `canvas-mcp-server` automaticamente e conversa com ele por
`stdio`, usando a entrada e a saída do processo. O servidor consulta o Canvas
com seu token pessoal. Não abre uma porta HTTP nem precisa receber conexões
pela internet. Assim, para uso local, você instala e configura uma vez; não
precisa publicar o projeto nem manter um terminal rodando o servidor.

O GitHub guarda o código e executa os testes de CI. Fazer push **não coloca o MCP
em funcionamento na nuvem**. O servidor acompanha o uso do cliente local.
O computador precisa estar disponível, com acesso à internet e um token válido.
Os clientes documentam esse transporte: [Claude Code](https://code.claude.com/docs/en/mcp#option-3-add-a-local-stdio-server)
e [Codex](https://learn.chatgpt.com/docs/extend/mcp?surface=cli).

Para um cliente que só conecta a endpoints remotos, seria necessária outra
implementação, com transporte HTTP, hospedagem e autenticação do MCP. Essa opção
não faz parte deste servidor local. A URL da API Canvas é a origem dos dados,
não um endereço onde este MCP está hospedado.

A checagem semanal também pode rodar no GitHub Actions: ele inicia um processo
temporário, consulta a API e encerra. Isso funciona com o Mac desligado e não
exige publicar um servidor MCP. Veja o [guia do agendamento](automation/README.md#5-github-actions-sem-o-mac-ligado).

## 1. Obter um token pessoal do Canvas

Este fluxo serve para seu próprio protótipo local. O token usa as permissões da
sua conta; não é uma chave de API da Anthropic ou da OpenAI.

1. Abra o Canvas da instituição, por exemplo [Canvas PUC Minas](https://pucminas.instructure.com), e faça login.
2. Entre em **Conta → Configurações**. Dependendo da interface, abra primeiro seu perfil.
3. Procure **Integrações aprovadas / Approved Integrations**.
4. Clique em **Novo token de acesso / New Access Token**, se essa opção estiver disponível.
5. Informe uma finalidade, como `MCP local Canvas`, e a expiração solicitada pela instituição.
6. Gere o token e copie o valor para seu arquivo `.env`, conforme a próxima seção.
   O Canvas não mostra novamente o valor gerado; se perdê-lo, será necessário criar outro.
7. Guarde qualquer anotação de validade somente no `.env` ou em `.local/`, ambos ignorados pelo Git.

Se a instituição não mostrar o botão, bloquear a geração ou exigir autorização,
solicite acesso à API ao administrador do Canvas ou ao suporte de TI. Não use
sua senha do portal como token. A documentação oficial descreve a
[geração manual de tokens](https://developerdocs.instructure.com/services/canvas/oauth2/file.oauth#manual-token-generation).

Para oferecer uma aplicação a vários usuários, o Canvas exige o fluxo OAuth,
com uma chave de desenvolvedor fornecida pelo administrador. Este projeto ainda
não implementa OAuth; cada instalação pessoal mantém suas próprias credenciais.
Veja [autenticação oficial](https://developerdocs.instructure.com/services/canvas/oauth2/file.oauth).

## 2. Instalar o projeto

Os comandos abaixo são para macOS/Linux. É necessário Git e Python 3.11+.
O projeto usa Python 3.12 por padrão, que o uv pode instalar automaticamente.

### Instalar o uv

No macOS com Homebrew:

```sh
brew install uv
uv --version
```

Para outros métodos, consulte a [instalação oficial do uv](https://docs.astral.sh/uv/getting-started/installation/).

### Clonar e instalar as dependências

```sh
git clone https://github.com/arthurcuri/mcp-instructure-canvas.git
cd mcp-instructure-canvas
uv sync --locked
```

Se o projeto já estiver clonado, abra seu diretório e execute apenas `uv sync --locked`.
O uv cria `.venv/` e instala as versões de `uv.lock`.

### Preparar a configuração privada

Crie o arquivo somente se ele ainda não existir:

```sh
if [ ! -f .env ]; then cp .env.example .env; fi
chmod 600 .env
nano .env
```

No editor, preencha `CANVAS_API_TOKEN` com o valor obtido no Canvas. Não passe o
valor pelo comando de registro do MCP nem o publique em configurações de clientes.

| Variável | Como preencher |
|---|---|
| `CANVAS_API_URL` | Origem HTTPS do Canvas, com ou sem `/api/v1`; por exemplo `https://pucminas.instructure.com/api/v1` |
| `CANVAS_API_TOKEN` | Seu token pessoal; obrigatório |
| `CANVAS_DEFAULT_COURSE_ID` | Opcional: número presente no endereço de uma matéria, depois de `/courses/` |
| `CANVAS_TIMEZONE` | Fuso dos prazos; padrão `America/Sao_Paulo` |
| `CANVAS_TOKEN_EXPIRES_AT` | Opcional: anotação privada da validade em `YYYY-MM-DD`; não altera a validade no Canvas |
| `CANVAS_READ_ONLY` | `false` por padrão habilita escrita; `true` oculta ferramentas de escrita e bloqueia mutações no cliente HTTP |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Opcionais: usados somente quando a checagem recebe `--telegram` |

Exemplo de identificação: em `https://canvas.example.edu/courses/12345`, o curso
é `12345`. Sem um curso padrão, informe `course_id` nas ferramentas de uma matéria
ou use `all_courses=true` na consulta de prazos.

Variáveis do processo prevalecem sobre o arquivo. O parâmetro `--env-file` permite
usar um caminho explícito, evitando depender do diretório em que o cliente abriu.

### Verificar o acesso

```sh
uv run canvas-mcp-server --test
uv run canvas-mcp-server --config
```

`--test` consulta seu perfil e, se configurado, o curso padrão e suas atividades.
`--config` mostra a configuração sem exibir o token. Ambos encerram após a consulta.
O token e qualquer anotação pessoal permanecem em arquivos ignorados.

## 3. Conectar a um cliente MCP

Os clientes usam o **mesmo servidor e as mesmas ferramentas**. Seus arquivos
de instruções ajudam o agente a trabalhar neste repositório; a configuração MCP
é o que permite consultar o Canvas.

Modelos versionados usam caminhos fictícios e nenhum token. As cópias com caminhos
reais são ignoradas pelo Git. Se você já tiver uma configuração, acrescente somente
a entrada `canvas-pucminas`, preservando as outras entradas e preferências.

### Claude Code

Na raiz do projeto:

```sh
claude mcp add --scope local --transport stdio canvas-pucminas -- \
  "$PWD/.venv/bin/canvas-mcp-server" --env-file "$PWD/.env"
claude mcp get canvas-pucminas
```

O escopo `local` salva um registro privado em `~/.claude.json`, associado a este
projeto. Abra uma nova sessão no diretório do projeto e use `/mcp` para conferir
as ferramentas. O registro contém o comando e o caminho do `.env`, sem copiar o token.

Também existe o modelo [examples/mcp.json](examples/mcp.json) para um registro em
`.mcp.json`. Adapte os caminhos e escolha um dos dois registros para evitar duplicação.
A pasta [.claude](.claude/README.md) contém orientações e regras para contribuir com Claude Code.

### Codex

Na raiz do projeto:

```sh
codex mcp add canvas-pucminas -- \
  "$PWD/.venv/bin/canvas-mcp-server" --env-file "$PWD/.env"
codex mcp get canvas-pucminas
```

O registro fica em `~/.codex/config.toml`. Abra uma nova sessão do Codex e confira
`/mcp`. Para uma configuração restrita ao projeto, copie
[.codex/config.toml.example](.codex/config.toml.example) para `.codex/config.toml`,
adapte os caminhos e abra o projeto como confiável. Se a configuração já existir,
mescle a seção em vez de substituir o arquivo.

O Codex lê `AGENTS.md` automaticamente. Veja [.codex/README.md](.codex/README.md) e a
[documentação de configuração por projeto](https://learn.chatgpt.com/docs/config-file/config-advanced).

### Gemini CLI

1. Conclua a instalação e o teste de conexão acima.
2. Copie o modelo, se ainda não existir uma configuração:

   ```sh
   if [ ! -f .gemini/settings.json ]; then cp .gemini/settings.json.example .gemini/settings.json; fi
   ```

3. Substitua os dois caminhos absolutos em `.gemini/settings.json`: o executável
   `.venv/bin/canvas-mcp-server` e o `.env`.
4. Reinicie Gemini CLI neste projeto e use `/mcp` para conferir a conexão.
5. Use `/memory show` para verificar as instruções do `GEMINI.md`, que importa `AGENTS.md`.

A cópia local é ignorada. Veja [.gemini/README.md](.gemini/README.md),
[configuração MCP](https://geminicli.com/docs/tools/mcp-server/) e
[configuração de contexto](https://geminicli.com/docs/get-started/configuration/).

### Cursor

1. Conclua a instalação e o teste de conexão.
2. Copie [.cursor/mcp.json.example](.cursor/mcp.json.example) para `.cursor/mcp.json`,
   se o arquivo ainda não existir; caso contrário, mescle a entrada do servidor.
3. Substitua os caminhos absolutos do executável e do `.env`.
4. Abra o projeto no Cursor e confira/reconecte o servidor nas configurações de MCP.
5. As regras de desenvolvimento são carregadas de `.cursor/rules/`; `AGENTS.md`
   também é suportado pelo Cursor.

Veja [.cursor/README.md](.cursor/README.md), [MCP no Cursor](https://cursor.com/docs/mcp)
e [regras do projeto](https://cursor.com/docs/rules).

### Kiro

1. Conclua a instalação e o teste de conexão.
2. Copie [.kiro/settings/mcp.json.example](.kiro/settings/mcp.json.example) para
   `.kiro/settings/mcp.json`, se ainda não existir; caso contrário, mescle a entrada.
3. Substitua os caminhos absolutos do executável e do `.env`.
4. Abra o painel de MCP do workspace do Kiro e confira/reconecte o servidor.
5. O Kiro recebe as orientações de `.kiro/steering/` e do `AGENTS.md` do projeto.

Veja [.kiro/README.md](.kiro/README.md), [configuração MCP](https://kiro.dev/docs/mcp/configuration/)
e [steering](https://kiro.dev/docs/steering/).

### Claude Desktop e outros clientes

Adapte [examples/mcp.json](examples/mcp.json) para a configuração `mcpServers` do
cliente, com caminhos absolutos. Para a instalação manual no Claude Desktop,
veja a [documentação de servidores locais](https://support.claude.com/en/articles/10949351-getting-started-with-local-mcp-servers-on-claude-desktop).
Esta versão não fornece uma extensão `.mcpb` empacotada.

Claude Code e Codex foram verificados nesta instalação. Os modelos dos demais
clientes seguem suas documentações oficiais; suas interfaces não fazem parte
dos testes automatizados deste repositório.

## 4. Usar o Canvas pelo assistente

Depois de conferir o MCP no seu cliente, faça perguntas como:

- “Liste minhas matérias e mostre os IDs.”
- “Quais atividades da matéria 12345 vencem nesta semana?”
- “O que vence nos próximos sete dias em todas as minhas matérias?”
- “Leia a descrição completa da atividade X e explique os requisitos.”
- “Mostre os módulos e as páginas de orientação da matéria.”

O curso padrão é usado quando `course_id` é omitido. Na consulta de prazos,
`all_courses=true` verifica todas as matérias com matrícula ativa. Os resumos
omitem descrições; o assistente pode usar a ferramenta de detalhes quando precisar.

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

`get_assignment` exige `assignment_id`; `get_page` exige `page_url`, o slug
retornado pela listagem de páginas ou módulos. As consultas de detalhes devolvem
todo o texto, com links e descrições de imagens, sem baixar os anexos.

### Como os prazos são interpretados

- `period="this_week"`: segunda-feira às 00h até a próxima segunda-feira às 00h,
  com início incluído e fim excluído, no fuso configurado. Inclui prazos que já
  passaram dentro da semana.
- `period="next_7_days"`: do instante da consulta até sete dias depois, com fim excluído.
- As listagens pedem ao Canvas `override_assignment_dates=true` e
  `include[]=submission`, preservando as datas efetivas e a sua entrega.
- Entregas submetidas, em revisão, dispensadas ou corrigidas sem `missing` são
  excluídas por padrão. Use `include_completed=true` para incluí-las.
- Atividades sem prazo entram em `undated_count`, sem serem colocadas artificialmente no período.
- `missing` e `late` vêm do Canvas, sem inferência apenas porque uma data passou.

### Acessar a API completa, incluindo escrita

Além das oito consultas acima, o MCP oferece dez ferramentas:

| Ferramenta | Uso |
|---|---|
| `search_canvas_operations` | Buscar operações por termos em inglês, método e grupo |
| `get_canvas_operation` | Consultar parâmetros obrigatórios, enums e link da documentação |
| `canvas_api_read` | Executar GET do catálogo, com paginação automática de listas |
| `canvas_api_write` | Executar POST, PUT, PATCH ou DELETE; aceita JSON, formulário, multipart e corpo bruto |
| `canvas_api_download` | Salvar a resposta de um GET, como relatório/CSV/ZIP, em um arquivo local novo |
| `canvas_upload_file` | Executar as três etapas de upload, retornando o `file_id` |
| `download_canvas_file` | Baixar um anexo pela URL assinada, sem enviar o token ao armazenamento |
| `submit_assignment` | Enviar uma entrega real: texto, URL, arquivos e outros tipos aceitos pelo Canvas |
| `canvas_graphql_read` | Executar query ou introspecção GraphQL; rejeita mutations |
| `canvas_graphql_write` | Executar mutation GraphQL |

São **18 ferramentas MCP**, que dão acesso ao catálogo sem registrar 1.118
ferramentas separadas no contexto do assistente. O transporte cobre todos os
métodos/rotas do catálogo oficial obtido em 13/10/2026, incluindo `/api/v1`,
New Quizzes em `/api/quiz/v1` e rotas `/api/lti`. Consulte o
[guia da API](docs/api.md) para exemplos de execução e atualização do catálogo.

Peça, por exemplo: “Descubra a operação para enviar minha atividade e mostre os
parâmetros exigidos” ou “Envie este arquivo para a atividade X”. Para anexos,
o assistente faz upload e depois chama `submit_assignment` com o ID recebido.
**Upload sozinho não entrega a atividade.** Escritas não são repetidas
automaticamente; se a conexão cair, confira o Canvas antes de tentar novamente.

As quatro ferramentas de escrita são identificadas como mutações. Consultas
sem gravação têm `readOnlyHint=true`; os dois downloads indicam que criam arquivos
locais novos, embora consultem o Canvas sem alterar seus dados. Para usar apenas consultas, defina
`CANVAS_READ_ONLY=true` no `.env` e reinicie/reconecte o MCP no cliente.

O catálogo completo não amplia as permissões da conta: recursos de professor,
administrador ou LTI exigem os papéis e credenciais correspondentes. Não há OAuth
de aplicação implementado. Processos com várias etapas continuam exigindo os
parâmetros e a sequência da documentação oficial. Os testes de escrita usam HTTP
simulado; operações destrutivas não são testadas na sua conta.

## 5. Preparar a checagem semanal no mesmo repositório

O agendamento não precisa de outro repositório. Um cron pode executar qualquer
comando local; mantemos o código e os modelos em [automation/](automation/README.md)
para permitir manutenção e reprodução pelos desenvolvedores.

**Estado:** a consulta semanal, o relatório privado e o envio opcional ao Telegram
estão implementados. Há modelos locais e workflows do GitHub Actions no mesmo
repositório, com frequências semanal e diária. Receber respostas no Telegram e
chamar Claude Code a partir delas
ainda está em construção.
Nenhum job é ativado pela instalação, pelo registro do MCP ou pelos testes.

### Testar a checagem

```sh
uv run canvas-weekly-check --output .local/weekly-report.json
bash automation/run_weekly.sh
```

O padrão consulta o curso do `.env` nos próximos sete dias. Para todas as matérias:

```sh
bash automation/run_weekly.sh --all-courses
```

O relatório fica na pasta privada `.local/`, ignorada pelo Git, com permissão `600`.
Esse comando reutiliza a API do Canvas diretamente e não depende de uma sessão
MCP aberta. Não chama modelos e não consome tokens de IA. Se a consulta falhar,
o relatório anterior permanece intacto; verifique `checked_at` antes de utilizá-lo.

Depois de configurar o bot conforme [automation/README.md](automation/README.md#telegram-configurar-o-bot),
um envio manual usa:

```sh
bash automation/run_weekly.sh --all-courses --telegram
```

Sem `--telegram`, o comando apenas gera o relatório. A mensagem lista atividades,
prazos e links e pergunta se você quer ajuda. As respostas ainda não são processadas.

### Agendar gratuitamente no GitHub Actions

O workflow [weekly-canvas.yml](.github/workflows/weekly-canvas.yml) está preparado
para **segunda-feira às 09h17, no fuso de São Paulo**. O agendamento fica inativo
até você criar a variável `CANVAS_WEEKLY_ENABLED=true` nas configurações do repo.
Também é possível executar manualmente com **Actions → Weekly Canvas reminder → Run workflow**.

Para receber **todos os dias às 09h17**, use
[daily-canvas.yml](.github/workflows/daily-canvas.yml), escolha **Daily Canvas reminder**
em Actions e ative `CANVAS_DAILY_ENABLED=true` em Variables após o teste manual.
Os secrets são os mesmos; deixe `CANVAS_WEEKLY_ENABLED=false` para evitar duplicação
na segunda-feira. Cada mensagem inclui as atividades pendentes dos próximos sete dias.

1. Configure `CANVAS_API_TOKEN` em **Settings → Secrets and variables → Actions → Secrets**.
2. Para enviar mensagens, configure também `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID`.
3. Faça uma execução manual e confira o resultado.
4. Ative a variável `CANVAS_WEEKLY_ENABLED=true` em **Variables**.

Não envie o arquivo `.env` ao GitHub: cadastre apenas as credenciais necessárias
como secrets. O job consulta todas as matérias, força somente leitura e não
publica o relatório como artifact. Sua saída mostra contagens, sem descrições.
O bot e os secrets precisam ser configurados por você; o push não os configura.

Neste repositório público, o runner padrão `ubuntu-latest` é gratuito conforme a
[cobrança oficial do GitHub Actions](https://docs.github.com/en/billing/concepts/product-billing/github-actions).
Não há chamadas a Claude/OpenAI neste job. Se acrescentar IA, o uso terá os custos
ou limites do provedor. Em repositórios privados há uma cota dependente do plano
(2.000 minutos/mês no GitHub Free); runners maiores são cobrados.

O GitHub pode atrasar o horário e desativa schedules de repositórios públicos
após 60 dias sem atividade. Veja os detalhes e a reativação no
[guia de automação](automation/README.md#5-github-actions-sem-o-mac-ligado) e na
[documentação de schedules](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).

### Agendar no macOS com launchd

1. Teste a checagem manual acima.
2. Prepare uma configuração local; isso **não a ativa**:

   ```sh
   uv run python automation/prepare_launchd.py
   plutil -lint .local/com.canvas-mcp.weekly.plist
   ```

3. Revise a cópia em `.local/`: o modelo executa segunda-feira, 09h, no fuso do
   macOS. Use `prepare_launchd.py --all-courses` para incluir todas as matérias.
4. Quando quiser ativar a geração de relatórios locais:

   ```sh
   mkdir -p "$HOME/Library/LaunchAgents"
   cp .local/com.canvas-mcp.weekly.plist "$HOME/Library/LaunchAgents/com.canvas-mcp.weekly.plist"
   launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.canvas-mcp.weekly.plist"
   launchctl print "gui/$(id -u)/com.canvas-mcp.weekly"
   ```

5. Para uma execução imediata, use `launchctl kickstart "gui/$(id -u)/com.canvas-mcp.weekly"`.
6. Para desativar e remover essa instalação:

   ```sh
   launchctl bootout "gui/$(id -u)/com.canvas-mcp.weekly"
   rm "$HOME/Library/LaunchAgents/com.canvas-mcp.weekly.plist"
   ```

O guia [automation/README.md](automation/README.md) explica edição do horário,
logs, atualização, requisitos do Mac e como usar `CANVAS_UV_BIN` se necessário.
O Mac desligado não executa tarefas locais. O agendamento de calendário do launchd
pode executar ao acordar de um período de sono; a consulta precisa de internet.

### Alternativa com cron ou Claude Code

Para cron, abra `crontab -e`, acrescente a linha de
[automation/crontab.example](automation/crontab.example) com o caminho real e
confira `crontab -l`. Preserve suas outras entradas. Para remover, apague somente
essa linha. Use cron ou launchd para evitar duplicação.

Também existem [tarefas persistentes no Claude Code Desktop](https://code.claude.com/docs/en/desktop-scheduled-tasks).
O `/loop` da CLI depende de uma sessão em execução, conforme a
[comparação oficial](https://code.claude.com/docs/en/scheduled-tasks).
Para acrescentar envio aos modelos locais, siga o
[guia de automação](automation/README.md). A integração automática com Claude Code
a partir de respostas no Telegram continua pendente.

## Desenvolvimento com agentes de IA

As pastas abaixo têm orientações reais para quem desenvolve o projeto usando
cada ferramenta, além de modelos opcionais de configuração MCP:

| Cliente | Orientações versionadas | Modelo de configuração local |
|---|---|---|
| Claude Code | `CLAUDE.md` + `.claude/rules/repository.md` | `examples/mcp.json` |
| Codex | `AGENTS.md` + `.codex/README.md` | `.codex/config.toml.example` |
| Gemini CLI | `GEMINI.md`, que importa `AGENTS.md` | `.gemini/settings.json.example` |
| Cursor | `AGENTS.md` + `.cursor/rules/repository.mdc` | `.cursor/mcp.json.example` |
| Kiro | `AGENTS.md` + `.kiro/steering/repository.md` | `.kiro/settings/mcp.json.example` |

`AGENTS.md` é a referência comum para arquitetura, comportamento, proteção das
credenciais e validação. As orientações específicas apontam para ela.

```sh
uv sync --locked
uv run ruff check src tests scripts automation
uv run ruff format --check src tests scripts automation
uv run pytest -q
bash -n automation/run_weekly.sh
uv build
```

Os testes usam credenciais sintéticas e HTTP simulado. Para verificar o protocolo
MCP contra sua conta real, de forma opcional:

```sh
uv run python scripts/verify_mcp.py
```

Estrutura: `src/canvas_mcp/` para API, serviços, MCP e checagem semanal; `tests/`
para testes; `automation/` para agendamento; pastas dos agentes para contribuição;
`uv.lock` para dependências reproduzíveis e GitHub Actions para lint, testes e build.

## Solução de problemas

| Sintoma | O que conferir |
|---|---|
| Token recusado / HTTP 401 | Token expirado, revogado ou copiado incorretamente; atualize somente seu `.env` |
| HTTP 403 | Permissões da conta ou restrições da instituição |
| HTTP 404 | ID do curso/atividade ou acesso à matéria |
| Cliente não inicia o servidor | Execute `uv sync --locked` e confira o caminho absoluto de `.venv/bin/canvas-mcp-server` |
| `.env` não encontrado | Confira o argumento `--env-file`; um cliente pode iniciar fora da raiz do repo |
| Nenhuma atividade no período | Confira fuso, `period`, curso, entregas já concluídas e `undated_count` |
| Job falha, mas a execução manual funciona | Confira `CANVAS_UV_BIN`, caminhos absolutos, rede e logs em `.local/` |
| Token aparece configurado, mas o prazo mudou | A validade é controlada pelo Canvas; a anotação local não altera a credencial |

## Segurança e limites

`.env`, `.local/` e as configurações reais dos clientes ficam fora do Git.
Os modelos públicos não incluem credenciais, caminhos pessoais ou datas pessoais.
Erros HTTP não devolvem corpos de resposta e a configuração pública não exibe o token.

O servidor recusa redirecionamentos e links de paginação fora da API configurada,
aplica timeout e faz até duas novas tentativas de leitura em HTTP 429/503. Escritas
e mensagens ao Telegram têm uma única tentativa. Consultas que
excedem 100 páginas ou 10.000 itens falham explicitamente.

O token conserva as permissões concedidas pela instituição. O modo somente leitura
é uma restrição deste servidor. Transferências assinadas de arquivos usam um
cliente separado, sem encaminhar a credencial Canvas ao armazenamento.
O conteúdo consultado chega ao cliente/assistente que
você usar; suas políticas de retenção continuam aplicáveis. Conteúdo dos cursos
é dado externo, sem autoridade para pedir credenciais ou execução de comandos.
Consulte [SECURITY.md](SECURITY.md).

## Referências e licença

Implementação própria inspirada nos projetos
[vishalsachdev/canvas-mcp](https://github.com/vishalsachdev/canvas-mcp) e
[mbcrosiersamuel/canvas-mcp](https://github.com/mbcrosiersamuel/canvas-mcp).
Base técnica: [SDK oficial MCP, linha 1.x](https://github.com/modelcontextprotocol/python-sdk/tree/v1.x),
[atividades do Canvas](https://developerdocs.instructure.com/services/canvas/resources/assignments)
e [paginação](https://developerdocs.instructure.com/services/canvas/basics/file.pagination).

[Licença MIT](LICENSE). Projeto independente, sem vínculo oficial com Instructure ou PUC Minas.
