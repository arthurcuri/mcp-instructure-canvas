"""Canvas's authenticated initiation, token-free storage upload and authenticated completion."""

import asyncio
import mimetypes
import os
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlsplit

import httpx

from canvas_mcp.api import CanvasApi, local_file
from canvas_mcp.client import CanvasClient, CanvasError


class CanvasTransfers:
    def __init__(self, client: CanvasClient, *, transport: httpx.AsyncBaseTransport | None = None):
        self.client = client
        self.api = CanvasApi(client)
        self.transport = transport

    def external_url(self, value: str) -> str:
        try:
            url = urlsplit(value)
            safe = (
                url.scheme == "https"
                and bool(url.hostname)
                and url.username is None
                and url.password is None
                and not url.fragment
            )
            _ = url.port
        except ValueError:
            safe = False
        if not safe or self.client._token in unquote(value):
            raise CanvasError("Canvas returned an invalid transfer URL.")
        return value

    async def upload(
        self,
        operation_id: str,
        file_path: str,
        path_parameters: dict | None = None,
        parameters: dict | None = None,
        pre_attachment: bool = False,
    ) -> dict:
        if self.client.read_only:
            raise CanvasError("Uploads are disabled by CANVAS_READ_ONLY=true.")
        operation = self.api.catalog.get(operation_id)
        supports_pre = any(
            parameter["name"].startswith("pre_attachment[") for parameter in operation["parameters"]
        )
        if operation["method"] != "POST" or not (
            operation["path"].endswith("/files") or supports_pre
        ):
            raise ValueError("Choose a file creation or pre_attachment operation from the catalog.")
        if pre_attachment and not supports_pre:
            raise ValueError("This operation does not document pre_attachment.")
        path = await asyncio.to_thread(local_file, file_path)
        stat = await asyncio.to_thread(path.stat)
        fields = {
            "name": path.name,
            "size": stat.st_size,
            "content_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        }
        body = dict(parameters or {})
        if pre_attachment:
            body["pre_attachment"] = {**(body.get("pre_attachment") or {}), **fields}
        else:
            body.update(fields)
        initiation = await self.api.write(operation_id, path_parameters, json_body=body)
        data = initiation["data"]
        upload = data.get("pre_attachment") if pre_attachment and isinstance(data, dict) else data
        if (
            not isinstance(upload, dict)
            or not isinstance(upload.get("upload_params"), dict)
            or not upload.get("upload_url")
        ):
            raise CanvasError("Canvas did not return the upload workflow data.")
        target = self.external_url(upload["upload_url"])
        # Separate HTTP client: the Canvas bearer token is never sent to the storage server.
        async with httpx.AsyncClient(
            timeout=300, follow_redirects=False, trust_env=False, transport=self.transport
        ) as http:
            handle = await asyncio.to_thread(path.open, "rb")
            try:
                response = await http.post(
                    target,
                    data=upload["upload_params"],
                    files={"file": (path.name, handle, fields["content_type"])},
                )
            except httpx.RequestError:
                raise CanvasError("Upload interrupted; check Canvas before repeating it.") from None
            finally:
                await asyncio.to_thread(handle.close)
        location = response.headers.get("Location")
        if response.status_code not in {200, 201, 301, 302, 303, 307, 308}:
            raise CanvasError(f"File server rejected the upload: HTTP {response.status_code}.")
        if location:
            # Completion must return to this institution's API; no external bearer-token redirect.
            final_url = self.client._safe_url(str(response.url.join(location)), full_api=True)
            complete = await self.client.request("GET", final_url, full_api=True)
            result = self.client.response_data(complete)
        elif response.status_code in {200, 201}:
            result = self.client.response_data(response)
        else:
            raise CanvasError(
                "Upload returned a redirect without Location; completion was not confirmed."
            )
        if not isinstance(result, dict) or not result.get("id"):
            raise CanvasError("Canvas did not confirm a file ID. Check the upload status.")
        return {
            "file": result,
            "file_id": result["id"],
            "bytes_uploaded": stat.st_size,
            "submission_created": False,
            "pre_attachment": pre_attachment,
            "initiated_job": {
                key: data[key] for key in ("id", "workflow_state", "progress_url") if key in data
            }
            if pre_attachment and isinstance(data, dict)
            else None,
        }

    async def download_file(self, file_id: int, destination: str) -> dict:
        if file_id < 1:
            raise ValueError("file_id must be positive.")
        metadata = await self.client.get(f"files/{file_id}")
        if not metadata.get("url"):
            raise CanvasError("Canvas did not provide a URL for this file.")
        target = self.external_url(metadata["url"])
        output = Path(destination)
        if not output.is_absolute() or await asyncio.to_thread(output.exists):
            raise ValueError("Choose an absolute destination path that does not exist yet.")
        await asyncio.to_thread(output.parent.mkdir, parents=True, exist_ok=True, mode=0o700)
        temporary = None
        size = 0
        try:
            async with httpx.AsyncClient(
                timeout=300, follow_redirects=False, trust_env=False, transport=self.transport
            ) as http:
                # Signed download redirects are followed without any Canvas Authorization header.
                for _ in range(5):
                    async with http.stream("GET", target) as response:
                        if response.status_code in {301, 302, 303, 307, 308}:
                            location = response.headers.get("Location")
                            if not location:
                                raise CanvasError(
                                    "Download returned a redirect without a destination."
                                )
                            target = self.external_url(str(response.url.join(location)))
                            continue
                        if not 200 <= response.status_code < 300:
                            raise CanvasError(f"Download rejected: HTTP {response.status_code}.")
                        with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as file:
                            temporary = Path(file.name)
                            os.fchmod(file.fileno(), 0o600)
                            async for block in response.aiter_bytes():
                                await asyncio.to_thread(file.write, block)
                                size += len(block)
                        await asyncio.to_thread(os.link, temporary, output)
                        return {"file_id": file_id, "saved_to": str(output), "bytes": size}
                raise CanvasError("Download exceeded the redirect limit.")
        except httpx.RequestError:
            raise CanvasError("Download interrupted; no complete file was saved.") from None
        finally:
            if temporary is not None:
                await asyncio.to_thread(temporary.unlink, missing_ok=True)
