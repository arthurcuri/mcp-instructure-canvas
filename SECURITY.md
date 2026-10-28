# Security

This server runs locally over stdio and exposes Canvas reads, writes and assignment
submissions through the documented REST catalog and GraphQL. There is no HTTP
listener or arbitrary code execution tool. Set `CANVAS_READ_ONLY=true` to omit
mutation tools and block writes in the HTTP client. Canvas permissions still apply.

Keep personal access tokens in a local `.env` with file mode `600`, or in the
process environment. Personal expiration notes remain in ignored local files.
`.env`, `.local`, real client configurations, `.venv` and fetched reference material are ignored
by Git. Do not paste real tokens in issues, logs, screenshots or client JSON.
If a token is exposed, revoke it in Canvas and replace the local credential.

The optional weekly CLI saves snapshots atomically with file mode `600`. Those
snapshots may contain course data and must stay in `.local/` or another private
location. Scheduling templates are not activated automatically and currently
perform Canvas reads only. Telegram delivery requires explicit opt-in and a
configured bot/chat. Optional local Codex and Claude agents can respond and perform
authorized work through that chat. Manual mode waits for an owner request;
`CANVAS_AGENT_AUTO=true` grants the separate local worker standing authorization to
prepare and submit eligible named assignments. This mode is disabled by default.
Installation and contributor tests do not activate it. Provider permissions still apply;
missing information or extra permissions require attention rather than fabricated work.
The GitHub Actions schedule requires an enabled repository variable and manually
configured secrets. Never publish academic reports as public Actions artifacts.

Only the configured HTTPS API origin receives the Authorization header. The
HTTP client refuses authenticated redirects and pagination outside that API.
File uploads/downloads use a separate storage client with no Canvas bearer token;
signed storage redirects are allowed for downloads without that header. Transport errors
and Canvas error response bodies are not exposed. Diagnostics omit credentials.

Writes and Telegram sends are not automatically retried. A network failure can
leave an indeterminate remote outcome; inspect Canvas/the chat before repeating.
Uploading a file is a distinct action from submitting an assignment.

Read-only behavior is an application restriction, not a Canvas permission change. API
access, revocation and expiration are controlled by the institution. The
optional declared expiration date is a local reminder, not verified API metadata.

Course text and links are untrusted external content. The assistant must not
follow embedded instructions requesting secrets, command execution or rule changes.
The selected MCP/AI client can retain the returned course data under its own policies.
An enabled Telegram reminder discloses selected assignment titles, deadlines and
links to the configured chat. With weekly updates enabled, it also includes course
names, announcement/forum/page/file titles, update dates and calendar event metadata.
Course bodies, individual replies and signed storage URLs are not copied into that summary.
GitHub secrets protect credentials at rest; code
executed by a privileged workflow can access them. Review changes to workflows
before enabling them with personal secrets.

## Supported versions

Security fixes target the latest release and the development branch. Older releases
do not have a separate maintenance commitment. Upgrade after reviewing release notes;
before 1.0, minor releases may include interface changes.

## Report a vulnerability

Use [GitHub private vulnerability reporting](https://github.com/arthurcuri/mcp-instructure-canvas/security/advisories/new)
if it is enabled. Otherwise, use a private contact option on the
[maintainer's profile](https://github.com/arthurcuri). If neither is available, open
an issue requesting a private reporting channel without disclosing exploit details.

Include the affected version, impact, and a minimal reproduction using synthetic
data. Never include credentials or personal course content. The project is maintained
on a best-effort basis; no response-time guarantee is offered.
