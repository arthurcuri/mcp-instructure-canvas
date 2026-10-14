"""Catalog-backed REST requests and correctly classified GraphQL operations."""

import asyncio
from contextlib import ExitStack
from pathlib import Path
from typing import Any

import httpx
from graphql import OperationType, get_operation_ast, parse
from graphql.error import GraphQLError

from canvas_mcp.catalog import ApiCatalog, validate_required
from canvas_mcp.client import CanvasClient, CanvasError


def local_file(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute() or not path.is_file():
        raise ValueError("Informe o caminho absoluto de um arquivo local regular.")
    return path


def wire_form(values: dict, prefix: str = "") -> dict:
    """Encode nested form objects in Canvas/Rails bracket notation."""
    result = {}
    for name, value in values.items():
        key = f"{prefix}[{name}]" if prefix else name
        if isinstance(value, dict):
            result.update(wire_form(value, key))
        elif isinstance(value, list) and any(isinstance(item, dict) for item in value):
            for index, item in enumerate(value):
                if isinstance(item, dict):
                    result.update(wire_form(item, f"{key}[{index}]"))
                else:
                    result[f"{key}[{index}]"] = item
        else:
            key = key if not isinstance(value, list) or key.endswith("[]") else key + "[]"
            result[key] = "true" if value is True else "false" if value is False else value
    return result


class CanvasApi:
    def __init__(self, client: CanvasClient):
        self.client = client
        self.catalog = ApiCatalog()

    async def read(
        self,
        operation_id: str,
        path_parameters: dict | None = None,
        query_parameters: dict | None = None,
        paginate: bool = True,
    ) -> dict:
        operation = self.catalog.get(operation_id)
        if operation["method"] not in {"GET", "HEAD", "OPTIONS"}:
            raise ValueError("Use canvas_api_write para essa operação de escrita.")
        path = self.catalog.render_path(operation, path_parameters)
        validate_required(operation, query_parameters, None)
        query = dict(query_parameters or {})
        if paginate and operation["response"].get("type") == "array":
            query.setdefault("per_page", 100)
        response = await self.client.request(operation["method"], path, params=query, full_api=True)
        data = self.client.response_data(response)
        pages = 1
        visited = {str(response.url)}
        next_page = response.links.get("next", {}).get("url")
        if paginate and isinstance(data, list):
            while next_page:
                if pages >= 100 or len(data) >= 10_000:
                    raise CanvasError("Paginação excedeu 100 páginas/10.000 itens. Use filtros.")
                url = self.client._safe_url(str(response.url.join(next_page)), full_api=True)
                if url in visited:
                    raise CanvasError("O Canvas retornou um ciclo na paginação.")
                visited.add(url)
                response = await self.client.request(operation["method"], url, full_api=True)
                page = self.client.response_data(response)
                if not isinstance(page, list):
                    raise CanvasError("O Canvas mudou o formato durante a paginação.")
                data.extend(page)
                if len(data) > 10_000:
                    raise CanvasError("Paginação excedeu 10.000 itens. Use filtros.")
                pages += 1
                next_page = response.links.get("next", {}).get("url")
        if next_page:
            next_page = self.client._safe_url(str(response.url.join(next_page)), full_api=True)
        return {
            "operation_id": operation_id,
            "method": operation["method"],
            "status_code": response.status_code,
            "data": data,
            "pages": pages,
            "next_page": self.client.redact(next_page),
        }

    async def write(
        self,
        operation_id: str,
        path_parameters: dict | None = None,
        query_parameters: dict | None = None,
        json_body: Any = None,
        form_parameters: dict | None = None,
        file_parameters: dict | None = None,
        raw_body: str | None = None,
        binary_body_file: str | None = None,
        content_type: str | None = None,
    ) -> dict:
        operation = self.catalog.get(operation_id)
        if operation["method"] in {"GET", "HEAD", "OPTIONS"}:
            raise ValueError("Use canvas_api_read para essa operação de leitura.")
        if self.client.read_only:
            raise CanvasError("Escrita desativada por CANVAS_READ_ONLY=true.")
        body_formats = (json_body, form_parameters, raw_body, binary_body_file)
        if sum(value is not None for value in body_formats) > 1:
            raise ValueError("Escolha JSON, formulário, corpo textual ou arquivo binário.")
        if file_parameters and (json_body is not None or raw_body is not None or binary_body_file):
            raise ValueError("Arquivos multipart só podem acompanhar parâmetros de formulário.")
        path = self.catalog.render_path(operation, path_parameters)
        body = json_body if json_body is not None else form_parameters
        validate_required(operation, query_parameters, body, file_parameters)
        raw = raw_body.encode() if raw_body is not None else None
        with ExitStack() as stack:
            attachments = {}
            for name, filename in (file_parameters or {}).items():
                selected = await asyncio.to_thread(local_file, filename)
                handle = stack.enter_context(await asyncio.to_thread(selected.open, "rb"))
                attachments[name] = (selected.name, handle)
            if binary_body_file:
                selected = await asyncio.to_thread(local_file, binary_body_file)
                handle = stack.enter_context(await asyncio.to_thread(selected.open, "rb"))

                async def blocks():
                    while block := await asyncio.to_thread(handle.read, 1024 * 1024):
                        yield block

                raw = blocks()
                content_type = content_type or "application/octet-stream"
            response = await self.client.request(
                operation["method"],
                path,
                params=query_parameters,
                json_body=json_body,
                form=wire_form(form_parameters) if form_parameters is not None else None,
                files=attachments or None,
                content=raw,
                content_type=content_type,
                full_api=True,
            )
        return {
            "operation_id": operation_id,
            "method": operation["method"],
            "status_code": response.status_code,
            "data": self.client.response_data(response),
        }

    async def download(
        self,
        operation_id: str,
        destination: str,
        path_parameters: dict | None = None,
        query_parameters: dict | None = None,
    ) -> dict:
        operation = self.catalog.get(operation_id)
        if operation["method"] != "GET":
            raise ValueError("Somente operações GET podem ser baixadas.")
        path = self.catalog.render_path(operation, path_parameters)
        validate_required(operation, query_parameters, None)
        url = str(httpx.URL(self.client._safe_url(path, full_api=True), params=query_parameters))
        target = Path(destination)
        if not target.is_absolute():
            raise ValueError("Informe um caminho absoluto para o download.")
        return await self.client.download(url, target)

    async def graphql(
        self,
        query: str,
        variables: dict | None = None,
        operation_name: str | None = None,
        *,
        mutation: bool = False,
    ) -> dict:
        try:
            operation = get_operation_ast(parse(query), operation_name)
        except GraphQLError:
            raise ValueError("Documento GraphQL inválido.") from None
        if operation is None:
            raise ValueError("Selecione uma operação GraphQL válida com operation_name.")
        expected = OperationType.MUTATION if mutation else OperationType.QUERY
        if operation.operation != expected:
            raise ValueError("Use a ferramenta GraphQL correspondente a query ou mutation.")
        response = await self.client.request(
            "POST",
            "/api/graphql",
            json_body={
                "query": query,
                "variables": variables or {},
                "operationName": operation_name,
            },
            full_api=True,
            graphql_query=not mutation,
        )
        return {
            "operation": "mutation" if mutation else "query",
            "status_code": response.status_code,
            "data": self.client.response_data(response),
        }
