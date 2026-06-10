# OSSM Evaluation Guide

This document describes how to run the **OpenShift LightSpeed (OLS) OSSM** evaluation
suite in this repository. It is a focused subset of the full Kiali troubleshooting
evaluations, intended to satisfy OLS reporting requirements.

**Latest results:** [RESULTS_OSSM.md](RESULTS_OSSM.md)

---

## Scope

The OSSM suite is intentionally narrow compared to the main evaluation in
[RESULTS.md](RESULTS.md):

| Item | OSSM value |
|---|---|
| Provider | **OpenAI only** (`system/system_openai.yaml`, `olsconfig/olsconfig-openai.yaml`) |
| Conversation | `check_mesh_status` — mesh health check via Kiali |
| Metric | `custom:answer_correctness` |
| Eval data | `ossm/conversations.yaml` |
| Output | `ossm/results/` |

For the full multi-scenario, multi-metric evaluation, see [DEVELOPMENT.md](DEVELOPMENT.md).

---

## Prerequisites

Same cluster and credential requirements as the main evaluation:

1. OpenShift/CRC cluster with Istio and Kiali running
2. Bookinfo demo deployed (`./install-bookinfo-demo.sh -tg true`)
3. OpenAI API key at `~/.openai/openai_api_key.txt` (or `OPENAI_API_KEY` exported)
4. Evaluation framework installed:

```bash
make setup && make setup-vector-db
```

See [DEVELOPMENT.md](DEVELOPMENT.md) for the full setup guide.

---

## Run OSSM tests

Start the required services in separate terminals, then run the test target.

### Terminal 1 — MCP server

```bash
make run-mcp
```

### Terminal 2 — OLS service (OpenAI)

```bash
make run-ols
```

OLS listens on port **8080**. The OSSM system config sends queries in
**troubleshooting** mode via `extra_request_params.mode`.

### Terminal 3 — Run the OSSM evaluation

```bash
make test
```

This runs the `check_mesh_status` conversation from `ossm/conversations.yaml` and
writes results to `ossm/results/`.

To run only that conversation explicitly:

```bash
make check_mesh_status-test
```

---

## Web dashboard

The evaluation dashboard can run OSSM tests interactively and browse past results.

### Setup (once)

```bash
make setup-dashboard
```

### Start the OSSM dashboard

```bash
make run-dashboard OLS_ENV=true
```

Open **http://localhost:5173**. The dashboard is configured with:

| Setting | Path |
|---|---|
| System config | `system/system_openai.yaml` |
| Eval data | `ossm/conversations.yaml` |
| Results | `ossm/results/` |

The dashboard uses the project `venv` so it matches the same
`lightspeed-evaluation` version as `make test`.

From the UI you can trigger a run, stream logs, and inspect CSV/JSON output.

---

## Generate the OSSM report

After a test run, regenerate the committed summary:

```bash
make generate-ossm-results
```

This produces:

- **`RESULTS_OSSM.md`** — summary table linked from [README.md](README.md)
- **`ossm/results/<conversation>_<model>.md`** — per-run detail pages

---

## Project layout (OSSM)

```
ossm/
├── conversations.yaml       # OSSM eval scenarios (currently one conversation)
├── ossm_scenarios.mk        # make test, generate-ossm-results, …
└── results/                 # evaluation CSV, JSON, graphs, detail pages
    └── evaluation_*.csv
```

---

## Makefile reference

| Target | Description |
|---|---|
| `make test` | Run all OSSM conversations (currently `check_mesh_status`) |
| `make check_mesh_status-test` | Run the mesh status conversation only |
| `make run-dashboard OLS_ENV=true` | Start the web dashboard for OSSM results |
| `make generate-ossm-results` | Regenerate `RESULTS_OSSM.md` from `ossm/results/` |

---

## Adding scenarios

1. Add a conversation block to `ossm/conversations.yaml`
2. Optionally add a dedicated target in `ossm/ossm_scenarios.mk`
3. Run `make test` and `make generate-ossm-results`

Keep metrics aligned with OLS requirements. The current suite uses
`custom:answer_correctness` only.

---

## CI (Pull Requests)

Every pull request that changes `ossm/**` triggers [`.github/workflows/ossm-pr.yml`](.github/workflows/ossm-pr.yml)
when the PR author is a **repo collaborator with write access** (`admin`, `maintain`, or `write`).
Fork or external PRs are skipped automatically.

| Job | Stack | Make target | OLS config |
|---|---|---|---|
| **with MCP** | kind + Istio + Kiali + MCP + OLS | `make test` | `olsconfig-openai.yaml` |
| **without MCP** | OLS + RAG only | `make test-without-mcp` | `olsconfig-openai-no-mcp.yaml` |

Results are uploaded as GitHub Actions artifacts (`ossm-results-mcp`,
`ossm-results-no-mcp`, and a combined `ossm-results-combined` with `RESULTS_OSSM.md`).

Requires the `OPENAI_KEY` repository secret.

On each run the workflow posts (or updates) a PR comment with job status and the
`RESULTS_OSSM.md` summary tables. Full CSV/JSON output is in the
`ossm-results-combined` workflow artifact.

### On-demand (manual)

Run **[OSSM Evaluation — On Demand](.github/workflows/ossm-on-demand.yml)** from
Actions → Run workflow. It executes the same parallel evals as PR CI, then opens a
pull request committing `RESULTS_OSSM.md` and `ossm/results/{mcp,no-mcp}/`
(including CSV, JSON, graphs, and detail pages).
