# AskSage Proof Agent - New User Guide

Current version: 1.0.0 (see VERSION file).

This guide walks a new machine from nothing to a running review dashboard.
Prerequisites: Docker Desktop with Linux containers, internet, about 7 GB of
free disk.

----------------------------------------------------------------------------
1. Get the repository
----------------------------------------------------------------------------

  git clone https://github.com/limynet/AskSageProofAgent.git
  cd AskSageProofAgent

(Or copy the package from the G-Drive folder AskSageProofAgent if you do not
use git.)

----------------------------------------------------------------------------
2. Download the local model (Bonsai-1.7B, ~237 MB)
----------------------------------------------------------------------------

The engine needs the Bonsai-1.7B Q1_0 GGUF file. The repository does not
ship it; download it once into models/:

PowerShell:

  New-Item -ItemType Directory -Force -Path models | Out-Null
  curl.exe -L --ssl-no-revoke -o models\Bonsai-1.7B-Q1_0.gguf `
    "https://huggingface.co/prism-ml/Bonsai-1.7B-gguf/resolve/main/Bonsai-1.7B-Q1_0.gguf"

Bash (Linux/macOS or Git-Bash):

  mkdir -p models
  curl -L -o models/Bonsai-1.7B-Q1_0.gguf \
    "https://huggingface.co/prism-ml/Bonsai-1.7B-gguf/resolve/main/Bonsai-1.7B-Q1_0.gguf"

Or use the helper script:  scripts/get_bonsai_model.ps1 (or .sh).

Verify the download (must be exactly 248,302,272 bytes / 237 MiB):

  (Get-Item models\Bonsai-1.7B-Q1_0.gguf).Length    # 248302272

----------------------------------------------------------------------------
3. Build the engine image (one time per machine)
----------------------------------------------------------------------------

The engine image is built locally, never downloaded:

  git clone https://github.com/deepgrove-ai/llama.cpp.git
  cd llama.cpp
  git checkout 7e30f3adb34b444c3527f94c3343612d71b47d0d
  docker build -t maple-llm-server:latest --target server -f .devops/cpu.Dockerfile .
  cd ..

This compiles llama.cpp with gcc-14; about 10-30 minutes the first time.
Trouble cloning? Download
https://github.com/deepgrove-ai/llama.cpp/archive/7e30f3adb34b444c3527f94c3343612d71b47d0d.zip
and unzip it into llama.cpp instead.

----------------------------------------------------------------------------
4. Run the stack (first start)
----------------------------------------------------------------------------

  docker compose up -d --build

This builds the dashboard image on first run (a few minutes) and starts two
containers:

      Container      Port    Role
      maple-llm      8080    Bonsai-1.7B engine (OpenAI-compatible API)
      ask-sage-dash  8501    the review dashboard

Or use the helper script:  scripts/run_stack.ps1  (checks the model, builds
the engine image if missing, then starts the stack).

----------------------------------------------------------------------------
5. Verify it is up
----------------------------------------------------------------------------

  docker compose ps                # both containers Up + (healthy)
  curl.exe -s http://localhost:8080/v1/models      # lists bonsai-1.7b
  curl.exe -s http://localhost:8501/health         # 200

Then open http://localhost:8501 in a browser. In the Engine panel select
Test connection - the pill should show bonsai-1.7b. Upload a manuscript and
select Run review: the seven stages run one click through the engine with
the saved prompts, and findings stream into the board.

----------------------------------------------------------------------------
6. Updating to a newer version
----------------------------------------------------------------------------

For a git checkout:

  git pull
  docker compose up -d --build dash-app
  docker compose restart dash-app     (optional, keeps containers tidy)

For a G-Drive copy: replace the changed files (the release notes list them -
usually dashboard.py, src/*, configs/*, requirements.txt) and then run the
same two docker commands.

Your saved prompt edits live in configs/prompts.json and version history in
configs/history/; both are bind-mounted, so updating never touches them. If
configs/ is bind-mounted after an upgrade, first rescue a previous version:

  docker cp ask-sage-dash:/app/configs/prompts.json ./configs/prompts.json

Then hard-refresh the browser (Ctrl+Shift+R) so no stale page is cached.

----------------------------------------------------------------------------
7. Custom API outlets (e.g., GenAI-MIL / api.genai.mil)
----------------------------------------------------------------------------

Each review node can call its own OpenAI-compatible API entry point. Named
outlets live in configs/outlets.json; the GenAI-MIL (IL5) outlet ships
preconfigured.

1. Store your API key locally (never commit it). Use the helper, which
   writes it into secrets/outlets.env:

       .\scripts\use_genai_mil.ps1

   Or write the file yourself:

       # secrets/outlets.env
       GENAI_MIL_API_KEY=your-key
       GENAI_MIL_MODEL=gemini-2.5-flash

   The secrets/ folder is gitignored; keys are never committed or shipped.
2. Refresh the dashboard browser tab (configs/ and secrets/ are bind-
   mounted into the container - no rebuild needed).
3. In any node editor, set Outlet = GenAI-MIL (IL5) and Save. Unselected
   nodes keep the local Bonsai engine.
4. Run the review: the chosen nodes call api.genai.mil.

Notes:
- The key auto-locks every 8 hours. When locked, the stage error shows an
  unlock_url; visit it (or unlock on the API Keys page) to re-enable.
- IL5 / CONTROLLED UNCLASSIFIED INFORMATION (CUI) - no PII/PHI. Only send
  content you are authorized to push, through approved systems.
- Reachability: api.genai.mil may require an approved network path. Verify
  with: curl.exe -s -H "Authorization: Bearer <key>" https://api.genai.mil/v1/models
- The Engine panel Test connection probes the default engine, not per-node
  outlets; a down outlet fails that stage loudly with the API message.

----------------------------------------------------------------------------
8. Publishing a new release (maintainer only)
----------------------------------------------------------------------------

1. Bump the version in VERSION (and this guide if it changed).
2. Commit:            git add -A ; git commit -m "vX.Y.Z: short summary"
3. Tag:               git tag vX.Y.Z
4. Push:              git push origin master ; git push origin vX.Y.Z
5. Create the GitHub release at
   https://github.com/limynet/AskSageProofAgent/releases/new
   - choose tag vX.Y.Z
   - title "vX.Y.Z - short summary"
   - body: summary, changed files, the model-download note (section 2), and
     the rebuild/update commands (section 6)
6. Optionally mirror the release tree to the G-Drive folder
   AskSageProofAgent so non-git users can take it.