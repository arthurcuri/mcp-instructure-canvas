# Pacotes e releases

O [README](../README.md) continua sendo o caminho recomendado para instalar as
três funcionalidades e configurar o agente. Os pacotes permitem também usar o
MCP de forma independente, sem copiar dados pessoais para uma imagem ou release.

| Distribuição | Conteúdo | Uso |
|---|---|---|
| [GitHub Releases](https://github.com/arthurcuri/mcp-instructure-canvas/releases/latest) | Wheel, fonte e SHA256SUMS | Instalar o MCP com Python/uv |
| [GitHub Packages](https://github.com/arthurcuri/mcp-instructure-canvas/pkgs/container/mcp-instructure-canvas) | Imagem OCI, Linux amd64/arm64 | Iniciar o MCP local com Docker |
| Checkout Git | Código, automação, instruções e skills | Configurar lembretes e agente Codex/Claude |

## Instalar o wheel

1. Baixe o `.whl` e `SHA256SUMS` da release desejada.
2. Confira o hash do wheel: `shasum -a 256 mcp_instructure_canvas-0.5.3-py3-none-any.whl`
   no macOS, ou `sha256sum` no Linux. Compare a linha correspondente em SHA256SUMS.
3. Em um ambiente Python 3.11+:

   ```sh
   python3 -m venv .venv
   .venv/bin/pip install ./mcp_instructure_canvas-0.5.3-py3-none-any.whl
   .venv/bin/canvas-mcp-server --version
   ```

4. Configure seu `.env` privado e registre o caminho absoluto do executável no
   cliente MCP, passando `--env-file /caminho/privado/.env`.

O wheel contém o catálogo Canvas e os comandos Python. O agente precisa também
do checkout e das instruções/skills; use o fluxo completo do README para ele.
Não há publicação PyPI nesta release: os arquivos Python vêm do GitHub Releases.

## Docker local

Com o Docker iniciado e seu `.env` privado preenchido, execute:

```sh
docker pull ghcr.io/arthurcuri/mcp-instructure-canvas:v0.5.3
docker run --rm -i --env-file .env ghcr.io/arthurcuri/mcp-instructure-canvas:v0.5.3
```

O processo usa stdio; iniciado sozinho, fica esperando mensagens MCP. Não publica
porta nem hospeda um endpoint remoto. Use `-i`, sem `-t`, ao registrar no cliente.

Exemplo de cliente compatível com JSON:

```json
{
  "mcpServers": {
    "canvas-pucminas": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i",
        "--env-file", "/caminho/privado/.env",
        "ghcr.io/arthurcuri/mcp-instructure-canvas:v0.5.3"
      ]
    }
  }
}
```

O cliente precisa encontrar `docker` no PATH; use o caminho absoluto quando
necessário. O Docker escolhe amd64/arm64 para o host. A imagem executa somente o
MCP: a configuração do Telegram, GitHub Actions e agente é feita no checkout.

### Arquivos e volumes

Uploads/downloads usam caminhos de dentro do container. Para compartilhar uma
pasta local, acrescente `--user "$(id -u):$(id -g)"` e
`--volume "$PWD/.local/files:/files"` ao `docker run`, após criar essa pasta.
Dentro das ferramentas MCP, use `/files/...`; o caminho do Mac não existe dentro
do container sem um volume. Esses argumentos são expandidos no shell; em uma
configuração JSON, informe UID/GID e caminhos absolutos já resolvidos.

### Visibilidade do primeiro pacote

Esta distribuição foi verificada com download anônimo e está pública. Se um
fork ou uma primeira publicação resultar em pacote privado, o proprietário pode
abrir **Packages → pacote → Package settings → Change visibility → Public** para
permitir download sem login. A visibilidade precisa ser conferida na publicação;
publicar a imagem não altera o login do Codex/Claude.
Veja [visibilidade](https://docs.github.com/en/packages/learn-github-packages/configuring-a-packages-access-control-and-visibility).

## Publicar uma versão

1. Atualize `pyproject.toml`, `src/canvas_mcp/__init__.py`, lock, changelog e
   `docs/releases/<versão>.md`.
2. Execute os checks descritos em AGENTS.md, faça push e aguarde o CI.
3. Crie e envie a tag da versão, por exemplo:

   ```sh
   git tag v0.5.3
   git push origin v0.5.3
   ```

4. O workflow **Release and GitHub Packages** valida a tag, testa o MCP em
   containers nativos amd64/arm64 e publica as imagens; depois testa/builda os
   arquivos Python, verifica os arquivos e cria a release com SHA256SUMS.

O workflow usa o `GITHUB_TOKEN` temporário do próprio repositório; não precisa de
token Canvas, bot Telegram, login de agente ou credencial PyPI. A publicação pode
ser refeita manualmente **a partir da tag**, para retomar uma execução que falhou.
Ele não altera arquivos ou releases já publicados para esconder uma falha.

A imagem tem labels de origem, licença MIT, versão e commit. As versões específicas
são recomendadas para configurações; `latest` acompanha a última publicação.
Veja [Container registry](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry)
e [GitHub Packages](https://docs.github.com/en/packages/learn-github-packages/introduction-to-github-packages).
