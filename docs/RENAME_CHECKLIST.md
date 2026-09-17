# Rename Checklist - product name (future)

The product is currently titled "AskSage Proof Agent". The name is a legacy
of the AskSage workflow this project replicates; the runtime is local models.
When a new name is chosen, work through the three lists below in order.
Nothing here blocks current use - this file is the plan for that day.

Suggested name directions (pick or ignore): "Pubs Review Agent" (matches the
proven workflow's own name), "Manuscript Review Agent", "Army Pubs Reviewer".
One rule: avoid "AskSage" in the new name to prevent confusion with the
optional cloud outlet.

## A. Product display name (safe, mechanical)

Each is a one-line string change; no behavior impact.

- dashboard.py: Dash(title=...) - browser tab (search: title="AskSage Proof Agent")
- dashboard.py: brand-wordmark div in the layout (search: brand-wordmark)
- dashboard.py: export letter "source" field (search: "source": "AskSage Proof Agent")
- dashboard.py: summary letter "Prepared by" line (search: Prepared by)
- QUICKSTART.md / DEPLOY.md / README_short.md: headings and first lines
- docker-compose.yml / requirements.txt / run_local.ps1 / setup.ps1 / setup.sh:
  header comments and the console banner string
- data/reference/README.txt: first line
- src/__init__.py, src/runner.py, src/pipeline.py: module docstrings

Tip for the pass: add a single PRODUCT_NAME constant in dashboard.py and use
it in all four dashboard strings first, so later renames touch one line.

## B. Infrastructure identifiers (coordinated pass, one maintenance window)

Renaming these touches runtime wiring; do them together, then rebuild.

- Docker image tag ask-sage-proof-agent:latest - defined in docker-compose.yml
  (dash-app service, image:) and referenced by DEPLOY.md/QUICKSTART docs and
  local muscle memory. Change image:, keep build context.
- Container name ask-sage-dash (docker-compose.yml container_name).
- Engine container/image names maple-llm / maple-llm-server - ALSO legacy
  (Maple-era). Renaming them means: compose service name, container_name,
  image tag, LOCAL_API_BASE default in configs/.env + .env.example
  (http://maple-llm:8080/v1), Dockerfile.app ENV default, and a
  `docker rm` of the old container on each machine. Highest churn item;
  schedule it, do not mix it into a casual pass.
- Folder names: AskSageProofAgent_Local (dev root), G-drive
  AskSageProofAgent, workstation Downloads\AskSageProofAgent. Renaming the
  dev root invalidates absolute paths baked into docs and
  tools/build_prompts_json.py defaults - update or leave the folder.
- src/runner.py thread name "asksage-seven-stage-run" (cosmetic, logs only).

## C. Historical references - keep as-is on purpose

These describe where the workflow came from; renaming them would falsify
provenance and break the audit trail.

- docs/CURRENT_PLAN.md, docs/plans/*, docs/G3_AUDIT.md (planning/audit
  records; CURRENT_PLAN.md already carries a SUPERSEDED banner)
- BUGFIXES.md (historical changelog, banner present)
- README_long.md (design history; describes the AskSage-to-local journey)
- src/pub_pipeline.py / src/prompts.py docstrings ("proven Pubs Review Agent
  v3 AskSage workflow" - provenance statement, keep)
- tools/build_prompts_json.py (extraction provenance)

## D. Legacy items - candidates for removal during the rename pass

- app.py: retired Streamlit entry point (the Dash app is the product).
  Candidate for deletion; it is not referenced by Docker or run_local.ps1.
- test_asksage.py: live cloud-API test for asksage.ai; not part of the
  offline suite. Delete or keep as an optional custom-outlet smoke test.
- configs/.env + setup scripts: ASKSAGE_API_* fallback block - superseded by
  the outlets.json custom outlet; simplify or keep as an example.
- Modelfile: unused by the current stack; review during the pass.

## Order of work on rename day

1. Pick the name; update list A (mechanical strings).
2. Run the full offline suites + QA probe; browser-check the wordmark and
   the browser tab.
3. Schedule list B as one pass: compose names first, then folders, then
   docs; rebuild both images; `docker rm` stale containers.
4. Decide list D items (delete or keep) and record the decision here.
5. Re-sync the G-drive package and the workstation checkout.
