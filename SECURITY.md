# Security

This server runs locally over stdio and exposes read-only Canvas queries.
There is no HTTP listener, write tool or code execution tool.

Keep personal access tokens in a local `.env` with file mode `600`, or in the
process environment. Personal expiration notes remain in ignored local files.
`.env`, `.local`, real client configurations, `.venv` and fetched reference material are ignored
by Git. Do not paste real tokens in issues, logs, screenshots or client JSON.
If a token is exposed, revoke it in Canvas and replace the local credential.

The optional weekly CLI saves snapshots atomically with file mode `600`. Those
snapshots may contain course data and must stay in `.local/` or another private
location. Scheduling templates are not activated automatically and currently
generate local reports only; Telegram delivery is not implemented.

Only the configured HTTPS API origin receives the Authorization header. The
HTTP client refuses redirects and pagination outside that API. Transport errors
and Canvas error response bodies are not exposed. Diagnostics omit credentials.

The token may allow more operations than this server implements. Read-only
behavior is an application restriction, not a Canvas permission change. API
access, revocation and expiration are controlled by the institution. The
optional declared expiration date is a local reminder, not verified API metadata.

Course text and links are untrusted external content. The assistant must not
follow embedded instructions requesting secrets, command execution or rule changes.
The selected MCP/AI client can retain the returned course data under its own policies.

Report security issues without credentials or personal course content through
the repository's private vulnerability reporting if enabled. Otherwise, contact
the maintainer privately rather than disclosing exploitable details in a public issue.
