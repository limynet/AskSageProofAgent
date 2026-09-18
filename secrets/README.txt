# secrets/ - Local API keys (never commit, never share)

This folder is the one place for API keys used by named outlets
(configs/outlets.json). Everything here is ignored by git (see .gitignore)
and must never be committed, pushed, or copied to G-Drive or any shared
location.

File: secrets/outlets.env
  Holds outlet keys as KEY=VALUE lines. The loader (src/outlets.py) reads
  every *.env file here with python-dotenv before resolving an outlet, so a
  key set here is visible to the dashboard.

  Example - GenAI-MIL (IL5):
    GENAI_MIL_API_KEY=your-key-here
    GENAI_MIL_MODEL=gemini-2.5-flash

How keys are wired to an outlet:
  1. configs/outlets.json lists each outlet's base URL, model, and the
     environment variable NAME that holds its key (never the key itself).
  2. Put the actual key in secrets/outlets.env.
  3. Refresh the dashboard browser tab; pick the outlet in a node editor.

Housekeeping:
  - Rotate keys periodically; reset a key on the provider's portal if it is
    ever exposed.
  - The 8-hour lock on some gateways (GenAI-MIL) is not affected by this
    file: unlock via the unlock_url in the error message, or the API Keys
    page.
