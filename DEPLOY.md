# AskSage Proof Agent - Docker Deployment

Current version: 1.0.0 (see VERSION). New users: read docs/NEW_USERS_GUIDE.md
for the model download, first-run steps, and update instructions.

This file documents how to run the AskSage Proof Agent (APA/ARI publication
review dashboard) as a Docker Compose stack with the local Bonsai-1.7B engine.

## What is in the stack

| Service      | Image                   | Port | Purpose                                            |
|--------------|-------------------------|------|----------------------------------------------------|
| maple-llm    | maple-llm-server:latest | 8080 | llama-server engine serving Bonsai-1.7B (OpenAI API) |
| dash-app     | ask-sage-proof-agent:latest | 8501 | Dash review app behind gunicorn                     |

The engine image `maple-llm-server:latest` bundles the llama-server binary
(built from the deepgrove llama.cpp fork). The Bonsai GGUF is bind-mounted
from the host `./models` directory read-only, so you do not need to rebuild
the engine image to swap models.

## Prerequisites

- Docker Desktop (or a Docker Engine with Compose v2+) running on Windows.
- The model file present at `./models/Bonsai-1.7B-Q1_0.gguf`
  (download from `prism-ml/Bonsai-1.7B-gguf` on Hugging Face if missing).
- Port 8080 and 8501 free on the host.

## First run on a new machine: build the engine image

The engine image `maple-llm-server:latest` is built locally, never pushed to
a registry, so `docker compose up` cannot pull it. Build it once from the
deepgrove llama.cpp fork at the pinned commit this project uses:

```powershell
git clone https://github.com/deepgrove-ai/llama.cpp.git
cd llama.cpp
git checkout 7e30f3adb34b444c3527f94c3343612d71b47d0d
docker build -t maple-llm-server:latest --target server -f .devops/cpu.Dockerfile .
cd ..
```

No git? Download the same commit as a zip:
`https://github.com/deepgrove-ai/llama.cpp/archive/7e30f3adb34b444c3527f94c3343612d71b47d0d.zip`

Notes:
- The tag must be exactly `maple-llm-server:latest` (compose references it).
- `--target server` produces an image whose entrypoint is `/app/llama-server`.
- First build compiles llama.cpp with gcc-14: about 10-30 minutes; later
  rebuilds are cached. Internet is required for base images and apt packages.

## Run

```powershell
docker compose up -d --build
```

First run builds the dash-app image (a few minutes for pip installs).
Subsequent runs reuse the cached image.

## Verify

```powershell
docker compose ps          # both containers Up + healthy
docker ps                  # same, with published ports

# Engine serves the bonsai alias:
curl http://localhost:8080/v1/models

# Dashboard is alive:
curl -i http://localhost:8501/health

# Browser: open http://localhost:8501
```

Then run the browser-equivalent QA probe from a checkout with the Python
dependencies installed:

```powershell
.\.venv\Scripts\python.exe qa_probe.py
```

Expect `12 PASS, 0 FAIL` against a healthy stack.

## Configuration

Environment for the dash-app service is defined in `docker-compose.yml`
and in `configs/.env` (values injected by Docker WIN over dotenv).

- `LOCAL_API_BASE` - OpenAI-compatible endpoint of the local engine.
- `LOCAL_MODEL` - model id (alias) the engine reports, e.g. `bonsai-1.7b`.
- `LLM_REQUEST_TIMEOUT` - per-request budget (900 s; a slow CPU stage on a
  long document can take several minutes).
- `CUSTOM_API_BASE` / `CUSTOM_MODEL` / `CUSTOM_API_KEY` - optional second
  (cloud) outlet for a review stage.

Per-stage model, temperature, token budget, outlet, and prompt text live in
`configs/prompts.json` and are editable from the dashboard UI (Node editor
panels). Each save archives the replaced config under
`configs/history/<stage>.json` (last 20 versions per node), and the node
editor lists them with Roll back buttons - a rollback lands as a new
version, so it is itself undoable. The `configs/` folder is bind-mounted
into the container, so saves persist on the host across rebuilds.

## Reference documents (RAG attachments)

Each review node can attach reference documents (ARI manual, Army AR/RAG,
DTIC regs). Drop the files into `data/reference/` - in Docker the `./data`
folder is bind-mounted, so no rebuild is needed:

- `ari_publication_manual.txt` (or `.md`, `.pdf`, `.docx`)
- `army_ar_rag.txt` (or `.md`, `.pdf`, `.docx`)
- `dtic_regs.txt` (or `.md`, `.pdf`, `.docx`)

Then refresh the browser page: the node editors show each document as
`[Loaded]`. Check the documents a node should attach and press Save on that
node; the review injects the attached text into that node's prompts. See
`data/reference/README.txt` for details.

## Per-node API entry points (outlets)

Each review node can call its own API entry point. Named outlets live in
`configs/outlets.json` (two defaults ship: `local` and `custom`). Add an
entry with any key, then pick it in the node editor's Outlet dropdown and
Save. Base URL, model, and API key are resolved from environment variables
first and fall back to the JSON defaults - keep keys in env vars, not JSON.
A node with an empty outlet follows the Engine panel selection. An outlet
that fails at run time fails that stage loudly (no silent fallback).

## Updating prompts / reference docs

- Prompts live in `configs/prompts.json`; the Dash UI writes back to it.
- Modernized reference docs (ARI manual, Army AR, DTIC regs) are loaded from
  `data/reference/` when present and registered in `configs/references.json`.
- After editing `configs/prompts.json` or `configs/references.json`, rebuild
  the dash-app image: `docker compose up -d --build dash-app`.

## Security note

The dashboard binds to 127.0.0.1 by default (`ASK_DASH_HOST` env, see
`app.run` in `dashboard.py`) so it is not exposed on the LAN. The engine
container binds 0.0.0.0:8080 inside the Compose network but is only reachable
through the Docker port mapping on the host loopback host port 8080.

## Troubleshooting

- Port already in use (8080/8501): stop whatever holds the port
  (`Get-NetTCPConnection -State Listen -LocalPort 8080,8501`), or change the
  host-side port mapping in `docker-compose.yml`.
- `Conflict. The container name ... is already in use`: a container created
  outside this Compose project holds the name. Remove it with
  `docker rm -f <name>` and run `docker compose up -d` again.
- Engine healthy but dashboard cannot reach it: check `docker compose logs dash-app`.
- Docker CLI transient failures (`npipe`): restart Docker Desktop and retry.
- QA probe shows `500`: run the stack's dashboard, not a stray host instance;
  the probe targets `http://127.0.0.1:8501`.