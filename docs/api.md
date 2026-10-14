# API completa do Canvas pelo MCP

O MCP combina oito consultas de uso comum com descoberta e execução do catálogo
REST oficial. O snapshot de **13/10/2026** contém **1.118 operações, em 144 grupos**:

| Método | Operações |
|---|---:|
| GET | 563 |
| POST | 236 |
| PUT | 188 |
| PATCH | 6 |
| DELETE | 125 |

Fonte: [índice Swagger oficial](https://canvas.instructure.com/doc/api/api-docs.json).
As ferramentas genéricas executam todas essas rotas, preservando método,
parâmetros e corpo. Não existe uma função Python específica para cada operação.
GraphQL e o fluxo completo de transferência de arquivos complementam o catálogo.

## 1. Descobrir a operação

Peça ao assistente para chamar:

```json
{
  "query": "submit assignment",
  "method": "POST",
  "limit": 10
}
```

Essa entrada é de `search_canvas_operations`. A busca usa os nomes e resumos em
inglês do catálogo. Entre os resultados está `submissions.submit_assignment_courses`.
Depois, consulte `get_canvas_operation`:

```json
{"operation_id": "submissions.submit_assignment_courses"}
```

O resultado inclui método, rota, parâmetros obrigatórios, opções enumeradas e um
link para a documentação oficial da operação. `include_response_models=true`
inclui os modelos do grupo; use quando precisar interpretar uma resposta.
Descrições longas e exemplos oficiais não são duplicados no catálogo local.
Leia o link oficial para regras condicionais, tipos de papel e processos com várias etapas.

## 2. Fazer uma consulta

Entrada de `canvas_api_read` para consultar o próprio perfil:

```json
{
  "operation_id": "users.get_user_profile",
  "path_parameters": {"user_id": "self"}
}
```

Parâmetros de rota devem corresponder aos nomes de `{placeholders}` da operação.
IDs numéricos, `self` e identificadores SIS são codificados como valores de caminho.
Parâmetros de busca ficam em `query_parameters`; campos com colchetes devem
preservar o nome documentado, como `"include[]": ["submission"]`.

A resposta inclui `status_code`, `data`, `pages` e `next_page`. Listas seguem os
links opacos de paginação sem reaplicar os filtros iniciais. `paginate=false`
devolve apenas a primeira página e o próximo link, quando houver. Consultas que
excedem 100 páginas ou 10.000 itens falham explicitamente: restrinja a consulta.

Respostas JSON são preservadas, sem resumir os corpos; texto é devolvido como
texto e binários pequenos como base64. Para um relatório grande, use
`canvas_api_download` com um caminho absoluto de destino que ainda não exista.
Para um anexo identificado por `file_id`, use `download_canvas_file`.

## 3. Criar, editar ou excluir

`canvas_api_write` executa POST, PUT, PATCH e DELETE. Primeiro descubra a operação
e confira os parâmetros. Por exemplo, criar uma página exige permissão de edição
no curso; a entrada da ferramenta seria:

```json
{
  "operation_id": "pages.create_page_courses",
  "path_parameters": {"course_id": 12345},
  "json_body": {
    "wiki_page": {"title": "Página de orientação", "body": "<p>Conteúdo</p>"}
  }
}
```

Escolha um formato de corpo por requisição:

- `json_body`: objeto, array ou outro valor JSON aceito pela operação.
- `form_parameters`: formulário; aceita objetos aninhados e nomes com colchetes.
- `raw_body` e `content_type`: texto bruto, como CSV ou XML quando a rota permitir.
- `binary_body_file` e `content_type`: conteúdo de um arquivo local por streaming.
- `file_parameters`: multipart, mapeando campos para caminhos absolutos de arquivos;
  pode acompanhar `form_parameters`.

Parâmetros obrigatórios e enums conhecidos são verificados antes do HTTP. O
Canvas valida as demais regras e permissões. Algumas rotas aceitam parâmetros
de formulário também na query, conforme a documentação; `query_parameters`
permanece disponível em escritas.

Não há retries automáticos de escrita. Uma queda de conexão pode ocorrer depois
que o Canvas executou a ação; confira o recurso antes de repetir. A resposta
traz o código HTTP e os dados originais, inclusive estados de trabalhos
assíncronos. HTTP 200/202 não implica que uma importação ou migração já terminou:
consulte a operação de progresso indicada pelo Canvas.

## 4. Enviar uma atividade

Para texto, a entrada de `submit_assignment` é:

```json
{
  "course_id": 12345,
  "assignment_id": 67890,
  "submission": {
    "submission_type": "online_text_entry",
    "body": "Texto final da entrega"
  }
}
```

O curso padrão pode substituir `course_id`. Para arquivo, primeiro use
`canvas_upload_file`:

```json
{
  "operation_id": "submissions.upload_file_courses",
  "path_parameters": {
    "course_id": 12345, "assignment_id": 67890, "user_id": "self"
  },
  "file_path": "/caminho/absoluto/trabalho.pdf"
}
```

A ferramenta inicia o upload autenticado, envia o multipart ao armazenamento
**sem o token Canvas** e completa o fluxo na API da instituição. O arquivo fica
disponível, mas a atividade ainda não foi entregue. Com o `file_id` recebido,
chame `submit_assignment`:

```json
{
  "course_id": 12345,
  "assignment_id": 67890,
  "submission": {"submission_type": "online_upload", "file_ids": [112233]}
}
```

O tipo de entrega deve estar habilitado na atividade, e as datas/regras do Canvas
continuam valendo. A ferramenta também aceita URL, mídia, anotação e o formato
LTI documentado, quando a conta/atividade permitir. Campos específicos ficam
em `submission`; um comentário opcional fica em `comment`.

`canvas_upload_file` também aceita os inicializadores de arquivos de usuários,
cursos, grupos e pastas. Para operações que documentam `pre_attachment`, use
`pre_attachment=true` e forneça os demais campos exigidos em `parameters`.
Uploads por URL e outros trabalhos assíncronos podem ser iniciados com a
operação genérica e acompanhados pelas operações de progresso correspondentes.
Veja [uploads](https://developerdocs.instructure.com/services/canvas/basics/file.file_uploads)
e [submissões](https://developerdocs.instructure.com/services/canvas/resources/submissions).

## 5. GraphQL

As ferramentas GraphQL usam o endpoint oficial `/api/graphql`. Uma consulta
de `canvas_graphql_read` pode usar:

```json
{
  "query": "query Course($id: ID!) { course(id: $id) { _id name } }",
  "variables": {"id": "12345"},
  "operation_name": "Course"
}
```

`canvas_graphql_write` recebe `mutation`, `variables` e `operation_name`.
Um parser GraphQL identifica a operação selecionada; uma mutation enviada à
ferramenta de leitura é rejeitada antes de qualquer chamada HTTP. Se o documento
possuir várias operações, selecione uma pelo nome.

Queries funcionam no modo somente leitura, embora o transporte GraphQL use POST.
Mutations ficam desabilitadas nesse modo. A resposta mantém os campos `data` e
`errors` do GraphQL: HTTP 200 pode incluir erros de execução.
Use introspecção ou `/graphiql` para conhecer o esquema disponível na instituição.
GraphQL não contém todos os recursos REST. Consulte a
[documentação oficial](https://developerdocs.instructure.com/services/canvas/basics/file.graphql).

## 6. Permissões, autenticação e cobertura

O catálogo cobre o inventário REST publicado pela Instructure nessa data;
rotas futuras, privadas ou não publicadas podem exigir uma atualização. Alguns
grupos incluem APIs New Quizzes/LTI. O transporte suporta suas rotas, mas tokens
pessoais não substituem credenciais OAuth/LTI específicas, papéis de professor
ou administrador, nem habilitam funcionalidades desativadas na instituição.

Esta versão não implementa o login OAuth multiusuário, a configuração de uma
ferramenta LTI ou um assistente especializado para cada processo administrativo.
O servidor fornece descoberta, execução dos contratos HTTP e fluxos auxiliares.
Foi testado com HTTP simulado para todas as 1.118 combinações de método/rota e
com casos funcionais de corpos, paginação, envios, GraphQL e transferências.
Isso não comprova acesso à sua conta em todas as operações. Testes de integração
reais consultam dados; não alteram o Canvas para testar uma funcionalidade.

Para ocultar as quatro ferramentas de mutação e bloquear escritas:

```dotenv
CANVAS_READ_ONLY=true
```

Depois reinicie/reconecte o MCP. As checagens semanais sempre usam somente leitura,
independentemente desse valor no MCP interativo.

## 7. Atualizar o catálogo

O gerador baixa apenas schemas públicos, sem token ou acesso à sua conta:

```sh
uv run python scripts/sync_api_catalog.py
uv run ruff check src tests scripts automation
uv run pytest -q
```

Para cache local, acrescente `--cache-dir .firecrawl/canvas-schemas`. Revise as
mudanças em `src/canvas_mcp/data/operations.json` e atualize os números de cobertura
documentados/testados quando o inventário oficial mudar. O JSON é embarcado no
wheel; o MCP não depende de baixar schemas a cada execução.
