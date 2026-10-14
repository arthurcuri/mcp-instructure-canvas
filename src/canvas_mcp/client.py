"""Canvas requests with same-origin credentials and read-only retry semantics."""

import asyncio
import base64
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urljoin, urlsplit

import httpx

from canvas_mcp import __version__
from canvas_mcp.config import Settings


class CanvasError(RuntimeError):
    """A Canvas failure safe to display to the MCP client."""


class CanvasClient:
    def __init__(self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None):
        self.api_url = settings.api_url.rstrip("/") + "/"
        self.api_root = settings.api_url.removesuffix("/api/v1") + "/api/"
        self.read_only = settings.read_only
        self._token = settings.api_token
        self._http = httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {settings.api_token}",
                "Accept": "application/json",
                "User-Agent": f"mcp-instructure-canvas/{__version__}",
            },
            timeout=httpx.Timeout(30.0, connect=10.0),
            limits=httpx.Limits(max_connections=5, max_keepalive_connections=5),
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )

    async def close(self) -> None:
        await self._http.aclose()

    def _safe_url(self, path: str, *, full_api: bool = False) -> str:
        prefix = self.api_root if full_api else self.api_url
        target = urljoin(prefix, path)
        try:
            base = urlsplit(prefix)
            url = urlsplit(target)
            segments = [unquote(segment) for segment in url.path.split("/")]
            safe = (
                url.scheme == "https"
                and (url.hostname, url.port) == (base.hostname, base.port)
                and url.username is None
                and url.password is None
                and url.path.startswith(base.path)
                and not url.fragment
                and not any(
                    segment in {".", ".."}
                    or "\\" in segment
                    or "%" in segment
                    or (not full_api and "/" in segment)
                    or (full_api and any(part in {".", ".."} for part in segment.split("/")))
                    for segment in segments
                )
            )
        except ValueError:
            safe = False
        if not safe:
            raise CanvasError("O Canvas retornou uma URL fora da API configurada.")
        return target

    async def _get(self, path: str, params: dict | None = None) -> httpx.Response:
        return await self.request("GET", path, params=params)

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json_body: Any = None,
        form: dict | None = None,
        content: Any = None,
        files: Any = None,
        content_type: str | None = None,
        full_api: bool = False,
        graphql_query: bool = False,
    ) -> httpx.Response:
        method = method.upper()
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}:
            raise CanvasError("Método HTTP não suportado.")
        url = self._safe_url(path, full_api=full_api)
        if graphql_query and not (method == "POST" and urlsplit(url).path == "/api/graphql"):
            raise CanvasError("A exceção de leitura GraphQL só vale para /api/graphql.")
        is_read = method in {"GET", "HEAD", "OPTIONS"} or graphql_query
        if self.read_only and not is_read:
            raise CanvasError("Escrita desativada por CANVAS_READ_ONLY=true.")
        if sum(value is not None for value in (json_body, form, content)) > 1:
            raise CanvasError("Use somente um formato de corpo por requisição.")
        if files and (json_body is not None or content is not None):
            raise CanvasError("Arquivos multipart não podem acompanhar JSON ou corpo bruto.")
        headers = {"Content-Type": content_type} if content_type else None
        attempts = 3 if is_read else 1
        for attempt in range(attempts):
            try:
                response = await self._http.request(
                    method,
                    url,
                    params=params,
                    json=json_body,
                    data=form,
                    content=content,
                    files=files,
                    headers=headers,
                )
            except httpx.RequestError:
                if not is_read:
                    raise CanvasError(
                        "Conexão interrompida durante escrita; o resultado é indeterminado. "
                        "Confira o Canvas antes de repetir a operação."
                    ) from None
                raise CanvasError("Falha de conexão com o Canvas. Tente novamente.") from None
            if response.status_code in {429, 503} and attempt < attempts - 1:
                try:
                    delay = float(response.headers.get("Retry-After", 2**attempt))
                except ValueError:
                    delay = 2**attempt
                await asyncio.sleep(max(0.0, min(delay, 10.0)))
                continue
            if response.status_code == 401:
                raise CanvasError("Canvas recusou o token: verifique se foi revogado ou expirou.")
            if response.status_code == 403:
                raise CanvasError("Sua conta não tem permissão para executar essa operação.")
            if response.status_code == 404:
                raise CanvasError("Recurso não encontrado ou indisponível para sua conta.")
            if not 200 <= response.status_code < 300:
                suffix = (
                    " Tente novamente." if is_read else " Escrita não foi repetida automaticamente."
                )
                raise CanvasError(f"Canvas retornou HTTP {response.status_code}.{suffix}")
            return response
        raise CanvasError("Canvas temporariamente indisponível.")

    def redact(self, value: Any) -> Any:
        if isinstance(value, str):
            return value.replace(self._token, "[REDACTED]")
        if isinstance(value, list):
            return [self.redact(item) for item in value]
        if isinstance(value, dict):
            return {self.redact(key): self.redact(item) for key, item in value.items()}
        return value

    def _json(self, response: httpx.Response) -> Any:
        try:
            return self.redact(response.json())
        except ValueError:
            raise CanvasError("O Canvas retornou uma resposta que não é JSON.") from None

    def response_data(self, response: httpx.Response) -> Any:
        if not response.content:
            return None
        if len(response.content) > 20_000_000:
            raise CanvasError(
                "Resposta excede 20 MB; use a ferramenta de download para salvar localmente."
            )
        mime = response.headers.get("Content-Type", "").lower()
        if "json" in mime:
            return self._json(response)
        if mime.startswith("text/") or "xml" in mime or not mime:
            try:
                return self.redact(response.json())
            except ValueError:
                return self.redact(response.text)
        sanitized = response.content.replace(self._token.encode(), b"[REDACTED]")
        return {"content_type": mime, "base64": base64.b64encode(sanitized).decode()}

    async def download(self, path: str, destination: Path) -> dict:
        """Stream an API GET to a new private local file, without loading it into MCP context."""
        import os
        import tempfile

        url = self._safe_url(path, full_api=True)
        if await asyncio.to_thread(destination.exists):
            raise CanvasError("O arquivo de destino já existe; escolha um caminho novo.")
        await asyncio.to_thread(destination.parent.mkdir, parents=True, exist_ok=True, mode=0o700)
        temporary = None
        size = 0
        try:
            async with self._http.stream("GET", url) as response:
                if not 200 <= response.status_code < 300:
                    raise CanvasError(
                        f"Download recusado pelo Canvas: HTTP {response.status_code}."
                    )
                with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as output:
                    temporary = Path(output.name)
                    os.fchmod(output.fileno(), 0o600)
                    async for block in response.aiter_bytes():
                        await asyncio.to_thread(output.write, block)
                        size += len(block)
                # Linking is atomic and refuses to overwrite a concurrently created destination.
                await asyncio.to_thread(os.link, temporary, destination)
        except httpx.RequestError:
            raise CanvasError(
                "Falha de conexão durante download; nenhum arquivo completo foi salvo."
            ) from None
        finally:
            if temporary is not None:
                await asyncio.to_thread(temporary.unlink, missing_ok=True)
        return {"saved_to": str(destination), "bytes": size, "status_code": response.status_code}

    async def get(self, path: str, params: dict | None = None) -> dict:
        result = self._json(await self._get(path, params))
        if not isinstance(result, dict):
            raise CanvasError("Formato inesperado na resposta do Canvas.")
        return result

    async def list(self, path: str, params: dict | None = None) -> list[dict]:
        url = self._safe_url(path)
        query = {"per_page": 100, **(params or {})}
        items: list[dict] = []
        visited: set[str] = set()
        for _ in range(100):
            if url in visited:
                raise CanvasError("O Canvas retornou um ciclo na paginação.")
            visited.add(url)
            response = await self._get(url, query)
            page = self._json(response)
            if not isinstance(page, list) or any(not isinstance(item, dict) for item in page):
                raise CanvasError("Formato inesperado na lista retornada pelo Canvas.")
            items.extend(page)
            if len(items) > 10_000:
                raise CanvasError(
                    "Consulta excedeu 10.000 itens; use um curso ou filtro específico."
                )
            next_page = response.links.get("next", {}).get("url")
            if not next_page:
                return items
            url = self._safe_url(urljoin(str(response.url), next_page))
            # Follow Canvas's opaque next URL without reapplying the first-page query.
            query = None
        raise CanvasError("Consulta excedeu 100 páginas; use um curso ou filtro específico.")
