"""Canvas GET requests, safe pagination, bounded retries and redacted errors."""

import asyncio
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

    def _safe_url(self, path: str) -> str:
        target = urljoin(self.api_url, path)
        try:
            base = urlsplit(self.api_url)
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
                    segment in {".", ".."} or any(char in segment for char in "/\\%")
                    for segment in segments
                )
            )
        except ValueError:
            safe = False
        if not safe:
            raise CanvasError("O Canvas retornou uma URL fora da API configurada.")
        return target

    async def _get(self, path: str, params: dict | None = None) -> httpx.Response:
        url = self._safe_url(path)
        for attempt in range(3):
            try:
                response = await self._http.get(url, params=params)
            except httpx.RequestError:
                raise CanvasError("Falha de conexão com o Canvas. Tente novamente.") from None
            if response.status_code in {429, 503} and attempt < 2:
                try:
                    delay = float(response.headers.get("Retry-After", 2**attempt))
                except ValueError:
                    delay = 2**attempt
                await asyncio.sleep(max(0.0, min(delay, 10.0)))
                continue
            if response.status_code == 401:
                raise CanvasError("Canvas recusou o token: verifique se foi revogado ou expirou.")
            if response.status_code == 403:
                raise CanvasError("Sua conta não tem permissão para consultar esse recurso.")
            if response.status_code == 404:
                raise CanvasError("Recurso não encontrado ou indisponível para sua conta.")
            if not 200 <= response.status_code < 300:
                raise CanvasError(f"Canvas retornou HTTP {response.status_code}. Tente novamente.")
            return response
        raise CanvasError("Canvas temporariamente indisponível.")

    @staticmethod
    def _json(response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError:
            raise CanvasError("O Canvas retornou uma resposta que não é JSON.") from None

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
