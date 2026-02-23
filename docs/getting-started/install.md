# Installation

## Install options

AgentBox is published as `vital-agentbox` on PyPI with several install extras
depending on your use case.

### Client only (for calling the API)

```bash
pip install vital-agentbox[client]
```

Installs only `httpx`. Use this in LangGraph apps or any code that calls
the AgentBox REST API.

### Full sandbox server (worker)

```bash
pip install vital-agentbox[worker]
```

Installs FastAPI, uvicorn, Playwright, boto3, and all sandbox dependencies.
This is what runs inside the worker Docker image.

### Orchestrator

```bash
pip install vital-agentbox[orchestrator]
```

Installs FastAPI, uvicorn, Redis, boto3, PyJWT, httpx. No Playwright or
Chromium — the orchestrator only proxies requests to workers.

### LangChain integration

```bash
pip install vital-agentbox[langchain]
```

Installs `httpx` and `langchain-core`. Provides `AgentBoxToolkit` and
`AgentBoxBackend` for LangChain/LangGraph agents.

### Development

```bash
pip install vital-agentbox[dev]
```

Installs pytest, pytest-asyncio, httpx, asgi-lifespan for running tests.

## System requirements

- **Python** ≥ 3.11
- **Chromium** (workers only) — installed via Playwright:
  ```bash
  playwright install chromium
  ```
- **PDF generation** (optional): pandoc + LaTeX
  ```bash
  # macOS
  brew install --cask mactex
  brew install pandoc
  ```

## Development setup (conda)

```bash
# Clone the repo
git clone https://github.com/vital-ai/vital-agentbox.git
cd vital-agentbox

# Create conda environment
conda env create -f environment.yml
conda activate vital-agentbox

# Install Chromium for Playwright
playwright install chromium

# Run tests
python -m pytest test/ -v
```

## Docker

For production deployment, use the pre-built Docker images:

```bash
# Build worker and orchestrator images
docker compose build

# Start the full stack (orchestrator + 2 workers + Redis + MinIO)
docker compose up
```

See [Deployment](deployment.md) for details.
