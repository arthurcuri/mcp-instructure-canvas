# Canvas API guide

The MCP server combines common course queries with discovery and execution of the documented REST inventory. The bundled snapshot from **October 13, 2026** contains **1,118 operations in 144 groups**: 563 GET, 236 POST, 188 PUT, 6 PATCH, and 125 DELETE operations. Source: the [official Swagger index](https://canvas.instructure.com/doc/api/api-docs.json).

The catalog is bundled in the wheel and works offline for discovery. Executing operations requires your institution's Canvas API and the permissions of your account. New, private, or institution-specific routes may require a catalog update. New Quizzes/LTI operations may require credentials beyond a personal token.

## Tool reference

| Tool | Purpose |
|---|---|
| `list_courses` | Active enrollments by default; optionally include completed enrollments |
| `get_course` | Course details and complete syllabus text |
| `list_assignments` | Summaries, effective due dates, and your submission status |
| `get_assignment` | Complete description, rubric, availability, and your submission status |
| `get_due_assignments` | Deadline summaries for a default/specific course or all active courses |
| `list_modules` | All modules and their separately paginated items |
| `list_pages` | Page titles and slugs |
| `get_page` | Complete page text |
| `search_canvas_operations` | Find REST operations by English names, summaries, routes, method, or group |
| `get_canvas_operation` | Required parameters, enums, formats, and official documentation link |
| `canvas_api_read` | Execute a catalog GET/HEAD/OPTIONS operation |
| `canvas_api_download` | Save a catalog GET response to a new absolute local path |
| `download_canvas_file` | Download an attachment by file ID without forwarding Canvas credentials to storage |
| `canvas_graphql_read` | Execute a query or introspection; reject mutations |
| `canvas_api_write` | Execute a catalog POST/PUT/PATCH/DELETE operation |
| `canvas_upload_file` | Run the file initialization, storage upload, and completion workflow |
| `submit_assignment` | Submit text, URL, uploaded files, or other supported submission data |
| `canvas_graphql_write` | Execute a mutation |

The last four tools are omitted with `CANVAS_READ_ONLY=true`. Downloads remain available but have non-read-only MCP hints because they create local files. All tools remain subject to client approval and Canvas permissions.

## Deadline windows

`get_due_assignments` defaults to the configured course and excludes completed/excused work. Set `all_courses=true` for active courses, without also specifying `course_id`. `this_week` spans local Monday 00:00 to the next Monday, with an exclusive end; `next_7_days` starts at the current instant. Results include boundaries, checked course IDs, and counts for undated and excluded completed assignments.

Submission state comes from the requesting user's submission association. Effective student due dates are preserved. The server does not mark paper/external-tool work missing solely because its due date passed. List tools omit descriptions; detail tools return complete text with links. Original course content remains in its original language.

## Discover and read an operation

Call `search_canvas_operations`:

```json
{"query": "submit assignment", "method": "POST", "limit": 10}
```

Then inspect `get_canvas_operation`:

```json
{"operation_id": "submissions.submit_assignment_courses"}
```

Use `include_response_models=true` when you need the group's response models. Read the returned official documentation link for conditional requirements and multistep processes; the local catalog does not duplicate all long descriptions/examples.

To read your own profile with `canvas_api_read`:

```json
{
  "operation_id": "users.get_user_profile",
  "path_parameters": {"user_id": "self"}
}
```

Path parameter keys match the route's placeholders. Numeric IDs, `self`, and SIS identifiers are encoded as path values. Query fields belong in `query_parameters`; preserve bracketed field names such as `"include[]": ["submission"]`.

Results include `status_code`, `data`, `pages`, and `next_page`. Lists follow opaque Link pagination without reapplying initial parameters. `paginate=false` returns the first page and its next link. Queries exceeding 100 pages or 10,000 items fail explicitly; use narrower filters.

JSON is returned unabridged, text as text, and small binary responses as base64. For large CSV/ZIP/report responses, use `canvas_api_download` with a new absolute destination. Use `download_canvas_file` for an attachment identified by `file_id`.

## Create, edit, or delete

Enable writes deliberately, discover the operation, and inspect its parameters before calling `canvas_api_write`. For example, creating a page requires course editing permissions:

```json
{
  "operation_id": "pages.create_page_courses",
  "path_parameters": {"course_id": 12345},
  "json_body": {
    "wiki_page": {"title": "Orientation", "body": "<p>Course information</p>"}
  }
}
```

Choose one body encoding:

- `json_body`: any JSON value accepted by the operation.
- `form_parameters`: form fields, including nested objects and bracketed names.
- `raw_body` plus `content_type`: text such as CSV/XML when supported.
- `binary_body_file` plus `content_type`: stream a local file.
- `file_parameters`: multipart field names mapped to absolute local paths; may accompany form parameters.

Known required parameters and enums are validated before HTTP. Canvas validates other rules and permissions. Query parameters remain available for writes where documented.

Writes are never retried automatically. A connection failure can happen after Canvas performed an action: inspect remote state before repeating. An HTTP 200/202 can acknowledge an asynchronous job without completing it; follow the documented progress operation.

## Submit an assignment

For a text submission, call `submit_assignment` only when authorized:

```json
{
  "course_id": 12345,
  "assignment_id": 67890,
  "submission": {
    "submission_type": "online_text_entry",
    "body": "Final submission text"
  }
}
```

For a file, call `canvas_upload_file` first:

```json
{
  "operation_id": "submissions.upload_file_courses",
  "path_parameters": {
    "course_id": 12345, "assignment_id": 67890, "user_id": "self"
  },
  "file_path": "/absolute/path/assignment.pdf"
}
```

The server initializes the upload with Canvas, uploads multipart data to storage **without the Canvas token**, and completes the institution's workflow. Uploading does not submit the assignment. Pass the returned file ID to `submit_assignment`:

```json
{
  "course_id": 12345,
  "assignment_id": 67890,
  "submission": {"submission_type": "online_upload", "file_ids": [112233]}
}
```

The submission type must be allowed by the assignment, and Canvas availability/permission rules still apply. Type-specific fields belong in `submission`; optional comments belong in `comment`. The configured default course can replace `course_id`.

Upload initializers for users, courses, groups, and folders are also supported. For documented pre-attachments, use `pre_attachment=true` and the required `parameters`. URL uploads and other asynchronous jobs can be initiated through generic operations and checked through their progress endpoints. See [uploads](https://developerdocs.instructure.com/services/canvas/basics/file.file_uploads) and [submissions](https://developerdocs.instructure.com/services/canvas/resources/submissions).

## GraphQL

`canvas_graphql_read` uses the official `/api/graphql` endpoint:

```json
{
  "query": "query Course($id: ID!) { course(id: $id) { _id name } }",
  "variables": {"id": "12345"},
  "operation_name": "Course"
}
```

`canvas_graphql_write` accepts `mutation`, `variables`, and `operation_name`. A GraphQL parser classifies the selected operation. Mutations passed to the read tool are rejected before HTTP; select a named operation when the document contains several.

Queries work in read-only mode even though GraphQL uses POST. Mutation tools are disabled in that mode. Results preserve GraphQL `data` and `errors`; HTTP 200 may contain execution errors. Use introspection or your institution's `/graphiql` to explore its schema. GraphQL does not expose every REST resource. See the [official guide](https://developerdocs.instructure.com/services/canvas/basics/file.graphql).

## Coverage and catalog updates

Mocked tests exercise every catalog method/route pair, plus body encodings, pagination, submissions, GraphQL, and transfers. They do not establish live access to every operation. Real integration checks use reads; do not mutate Canvas to test features.

To refresh the catalog from public schemas, without account credentials:

```sh
uv run python scripts/sync_api_catalog.py
uv run ruff check src tests scripts automation
uv run pytest -q
```

Optional cache: `--cache-dir .firecrawl/canvas-schemas`. Review changes in `src/canvas_mcp/data/operations.json` and update documented/tested counts when the public inventory changes. Runtime discovery never downloads schemas.
