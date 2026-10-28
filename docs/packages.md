# Packages and releases

The [source setup](setup.md) supports the complete MCP, reminder, and agent workflow. Release packages also support a standalone MCP installation.

| Distribution | Contents | Use |
|---|---|---|
| [GitHub Releases](https://github.com/arthurcuri/mcp-instructure-canvas/releases/latest) | Wheel, source archive, SHA256SUMS | Install with Python/uv |
| [GitHub Packages](https://github.com/arthurcuri/mcp-instructure-canvas/pkgs/container/mcp-instructure-canvas) | OCI image for Linux amd64/arm64 | Run local MCP with Docker |
| Git checkout | Source, automation, instructions, and skills | Develop or configure reminders/agents |

## Install a release wheel

1. Download the `.whl` and `SHA256SUMS` from the desired release.
2. Check the wheel hash using `shasum -a 256 mcp_instructure_canvas-0.6.0-py3-none-any.whl` on macOS, or `sha256sum` on Linux, and compare the matching checksum line.
3. In a Python 3.11+ environment:

   ```sh
   python3 -m venv .venv
   .venv/bin/pip install ./mcp_instructure_canvas-0.6.0-py3-none-any.whl
   .venv/bin/canvas-mcp-server --version
   ```

4. Configure your private `.env` and register the absolute executable path with `--env-file /private/path/.env` in your MCP client.

The wheel includes the catalog and Python commands. The complete agent workflow also needs the checkout's instructions and skills. Python release files are distributed through GitHub Releases; this project does not currently publish to PyPI.

## Local Docker

With Docker running and your private `.env` configured:

```sh
docker pull ghcr.io/arthurcuri/mcp-instructure-canvas:v0.6.0
docker run --rm -i --env-file .env ghcr.io/arthurcuri/mcp-instructure-canvas:v0.6.0
```

The process waits for MCP messages on stdio. It exposes no HTTP port. Use `-i` without `-t` in client configuration:

```json
{
  "mcpServers": {
    "canvas": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i",
        "--env-file", "/private/path/.env",
        "ghcr.io/arthurcuri/mcp-instructure-canvas:v0.6.0"
      ]
    }
  }
}
```

The client must find Docker in PATH; use an absolute executable path when necessary. Docker selects the native image architecture. The image starts only MCP; configure reminders and agents from the checkout.

### Files and volumes

Tool paths refer to the container filesystem. To share files, first create `.local/files`, then add `--user "$(id -u):$(id -g)" --volume "$PWD/.local/files:/files"` to `docker run`. Use `/files/...` inside MCP tool arguments. In JSON configuration, replace shell expansions with numeric UID/GID and absolute host paths.

### Package visibility

Anonymous download of the maintainer's published image was verified in the [validation record](validation.md). A fork's first publication may be private. Its owner can change **Packages → package → Package settings → Change visibility → Public** when public access is intended. Verify visibility after publication; publishing an image does not authenticate an agent account.

## Maintainer release procedure

1. Update `pyproject.toml`, `src/canvas_mcp/__init__.py`, `uv.lock`, the version and release links in `README.md`, package examples in this guide, the changelog, and `docs/releases/<version>.md`.
2. Run all checks in [CONTRIBUTING.md](../CONTRIBUTING.md), push the reviewed changes, and wait for CI.
3. Create and push the matching tag, for example `git tag v0.6.0` followed by `git push origin v0.6.0` for that version.
4. The release workflow validates the tag, tests native amd64/arm64 containers, publishes images, tests/builds Python distributions, audits archive contents, and creates a release with checksums.

The workflow uses the repository's temporary `GITHUB_TOKEN`; it needs no Canvas, Telegram, model-provider, or PyPI credentials. Manual dispatch must target the version tag, not a branch. Resume a failed publication only after inspecting existing assets; the current release command does not overwrite an existing release.

Images carry source, MIT license, version, and revision metadata. Prefer a version tag in client configuration; `latest` follows the newest publication. See the [workflow](../.github/workflows/release.yml) and [GitHub Container registry documentation](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry).
