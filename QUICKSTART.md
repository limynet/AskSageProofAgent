# AskSage Proof Agent - Quick Start

Current version: 1.0.0 (see VERSION). New to this project? Read
docs/NEW_USERS_GUIDE.md first - it covers the model download, engine build,
docker commands, and updating to a newer version.

Local APA 7 + ARI manuscript review agent. The proven "Pubs Review Agent v3"
7-stage pipeline runs on the **Bonsai-1.7B** local model (deepgrove
llama.cpp fork), with a Dash UI that shows every stage's model and prompt and
lets the boss edit them (AskSage-style canvas + list view).

ALL code, comments, docs, and UI are English/ASCII only. No emoji, no
em-dashes, no non-ASCII.

---

## 1. Models

- **Local engine:** Bonsai-1.7B (prism-ml Bonsai-1.7B-gguf),
  Q1_0 quantization, ~237 MiB, served by `llama-server`
  (deepgrove llama.cpp fork) on port 8080.
- **Fallback outlet (optional):** a user-configured OpenAI-compatible
  endpoint via `CUSTOM_API_BASE` / `CUSTOM_MODEL` / `CUSTOM_API_KEY`.

There is no Ollama - Bonsai is the only local model.
  (The engine image name is a legacy "maple-llm-server" tag; it serves Bonsai.)

---

## 2. Local run (no Docker)

```powershell
# 1. Create/refresh the venv and install deps
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 2. Start the local Bonsai engine (must already be serving on :8080). See section 5.

# 3. Run the dashboard
.\run_local.ps1
```

Open http://localhost:8501 . `.\run_local.ps1` defaults
`LOCAL_API_BASE=http://localhost:8080/v1` and `LOCAL_MODEL` to the served
bonsai id. Set them explicitly if your engine differs.

Configuration lives in `configs/.env` (see `configs/.env.example`).

---

## 3. Docker run (Bonsai + Dash)

```powershell
# Build the app image (engine image maple-llm-server is prebuilt; see section 5)
docker compose up -d --build
docker compose ps
docker compose logs -f
```

- Dash app: http://localhost:8501
- Bonsai engine: http://localhost:8080
- Stops with `docker compose down`.

---

## 4. Tests

All suites run with the project venv:

```powershell
.\.venv\Scripts\python.exe test_pipeline.py        # 16
.\.venv\Scripts\python.exe test_runner.py          # 8
.\.venv\Scripts\python.exe test_review_agents.py   # 20
.\.venv\Scripts\python.exe test_llm.py             # live, all pass
.\.venv\Scripts\python.exe test_prompts.py         # 11
.\.venv\Scripts\python.exe test_pub_pipeline.py    # 11
.\.venv\Scripts\python.exe test_references.py      # 5
.\.venv\Scripts\python.exe test_stage_meta.py      # 4
```

Every new source file must pass the ASCII gate
(no characters with ord > 127).

---

## 5. Bonsai engine (deepgrove llama.cpp fork)

The engine is the `maple-llm-server` image built from the deepgrove fork's
CPU `Dockerfile` (server target; the tag name is legacy). Build it once per
machine from the pinned fork commit:

```powershell
git clone https://github.com/deepgrove-ai/llama.cpp.git
cd llama.cpp
git checkout 7e30f3adb34b444c3527f94c3343612d71b47d0d
docker build -t maple-llm-server:latest --target server -f .devops/cpu.Dockerfile .
cd ..
```

The GGUF lives on the host at `models/Bonsai-1.7B-Q1_0.gguf`.

Quick run (mirrors what docker-compose does):

```powershell
docker run -d --name maple-llm -p 8080:8080 `
  -v "${PWD}\models:/models:ro" `
  maple-llm-server `
  -m /models/Bonsai-1.7B-Q1_0.gguf `
  --alias bonsai-1.7b `
  --host 0.0.0.0 --port 8080 -c 16384 -t 8 --jinja
```

Health: `curl http://localhost:8080/health` -> `{"status":"ok"}`.
Model lists at `http://localhost:8080/v1/models` (id is the alias
`bonsai-1.7b`).

Bonsai trains on a 32K-token context (`n_ctx_train` 32768); the engine runs
with `-c 16384`, which the 7-stage pipeline uses for whole documents.

---

## 6. Review flow (what the boss does)

1. Open http://localhost:8501 (List view of the 7 review stages is the only
   view; the browser binds to 127.0.0.1 by default - set ASK_DASH_HOST=0.0.0.0
   to share over the LAN).
2. **Test connection** -> green when the local engine is reachable.
3. Upload a manuscript; the deterministic scan runs immediately (instant
   findings, no LLM).
4. **Run review** runs the full pipeline in one click: the selected LLM
   passes (checklist above the button) plus extract, cross-section, dedup,
   and report - all with each node's saved prompts, outlet, temperature, and
   token budget. Findings stream into the board as stages finish; Cancel run
   stops at the next stage boundary. Every Save of a node archives the
   previous config (configs/history/<node>.json) and the node editor lists
   those versions with a Roll back button.
5. Click any stage to expand its prompt configuration: the sub-step flow with
   every prompt editable, model / temperature / max-tokens controls, and the
   reference-document checklist (attach/detach per node). Save persists with a
   version bump and is blocked mid-run.
6. Generate the findings/summary letter for export.
7. **Run review vs Run prompt:** Run review (left) runs the full 7-stage
   pipeline over the uploaded manuscript. Run prompt (right, Playground) is
   one free-form question to the engine about the loaded manuscript - it does
   not run the review. Run prompt probes the engine automatically if you have
   not clicked Test connection yet.
8. **Per-node API entry point (Outlet):** each node's editor has an Outlet
   dropdown. "Engine default" follows the Engine panel selection; the other
   entries come from `configs/outlets.json`, which you can extend with any
   OpenAI-compatible endpoint (base URL and model are read from environment
   variables first, then the JSON default - keep API keys in env vars).
   Leave the outlet empty to keep a node on the engine default.

---

## 7. Reference documents

The three gate documents (ARI internal publication manual, Army publication
regulations, DTIC regs) are injected as reference inputs. Place them under
`data/reference/` to have the review cite them directly; until then the
prompts run on their embedded distilled rules and the UI marks references
as not loaded. Each review node has its own attachment checklist so different
documents can feed different stages.
