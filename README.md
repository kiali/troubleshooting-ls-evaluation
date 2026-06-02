# Kiali — LightSpeed Troubleshooting Evaluation

> Latest evaluation results: **[RESULTS.md](RESULTS.md)**

End-to-end evaluation of the [OpenShift LightSpeed](https://github.com/openshift/lightspeed-service)
troubleshooting agent against a live Kiali / Istio cluster.

Conversations are defined in `scenarios/conversations.yaml`. Each one may deploy a broken
workload via a setup script, ask the agent to diagnose and fix it, then clean up.
Responses are scored with LLM-based metrics (`custom:answer_correctness`,
`custom:keywords_eval`, `custom:tool_eval`).

---

## Prerequisites

### 1. CRC cluster with Istio and Kiali

A running [CRC (OpenShift Local)](https://developers.redhat.com/products/openshift-local)
cluster with Istio and Kiali installed.

```bash
crc start
eval $(crc oc-env)
oc login -u developer -p developer https://api.crc.testing:6443
oc get pods -n istio-system | grep kiali   # verify Kiali is up
```

The default `KIALI_ENDPOINT` is already set to `https://kiali-istio-system.apps-crc.testing/`.

### 2. Bookinfo application with traffic generation

```bash
curl -L https://raw.githubusercontent.com/kiali/kiali/master/hack/istio/install-bookinfo-demo.sh \
  -o install-bookinfo-demo.sh
chmod +x install-bookinfo-demo.sh
./install-bookinfo-demo.sh -tg true   # -tg starts the Kiali traffic generator
oc get pods -n bookinfo               # all pods should be Running
```

### 3. API keys

```bash
# LLM provider (judge + OLS backend)
mkdir -p ~/.openai ~/.gemini
echo "sk-..."    > ~/.openai/openai_api_key.txt
echo "AIza..."   > ~/.gemini/google_api_key.txt
```

Or export directly — the Makefile reads the file only when the variable is unset:

```bash
export OPENAI_API_KEY="sk-..."
```

### 4. Node.js ≥ 18 (MCP server)

```bash
node --version   # v18 or higher
```

### 5. Podman (OLS container)

```bash
podman --version
```

### 6. Python 3.11+

```bash
python3 --version   # 3.11 or higher
```

---

## Setup

### Install the evaluation framework

```bash
make setup
```

Creates `venv/` and installs `lightspeed-evaluation`. Fails early if Python < 3.11.

### Extract the Kiali RAG vector database

OLS uses a Kiali knowledge base built from [kiali.io](https://kiali.io) docs via
[kiali-byok](https://github.com/kiali/kiali-byok). Extract it once:

```bash
make setup-vector-db
```

Re-extract after a new release:

```bash
rm -rf vector_db/kiali && make setup-vector-db
```

### Install the web dashboard (optional)

```bash
make setup-dashboard
```

Downloads and installs the [lightspeed-evaluation dashboard](https://github.com/lightspeed-core/lightspeed-evaluation/tree/main/dashboard)
into `dashboard/`. Pin to a specific version with `LSE_TAG=v0.6.0`.

---

## Running the evaluations

Three terminals are needed: MCP server, OLS service, and the eval runner.

### Terminal 1 — Kubernetes MCP server

```bash
make run-mcp
# or with a custom Kiali URL:
make run-mcp KIALI_ENDPOINT=https://kiali-istio-system.apps-crc.testing/
```

Starts the MCP server on port **8089** with the `kiali` toolset.

### Terminal 2 — OLS LightSpeed service

```bash
make run-ols
```

Starts the LightSpeed API container on port **8080** and automatically extracts
the vector DB if needed. Mounts:

| Host path | Container path | Purpose |
|-----------|---------------|---------|
| `./olsconfig/` | `/app-root/config/` | OLS configuration |
| `./vector_db/` | `/app-root/vector_db/` | Kiali RAG index |
| `~/.openai/openai_api_key.txt` | `/app-root/openai_api_key.txt` | OpenAI key |
| `~/.gemini/google_api_key.txt` | `/app-root/google_api_key.txt` | Gemini key |

### Terminal 3 — Run evaluations

```bash
make all                          # run all conversations in conversations.yaml
make fix_bookinfo_fault_injection # run one specific conversation
make check_mesh_status            # run one specific conversation
```

Pre-flight checks before every run:
- `venv/` exists → `make setup`
- `OPENAI_API_KEY` set or readable from key file
- Port **8080** open (OLS)
- Port **8089** open (MCP)
- Bookinfo pods running in `bookinfo` namespace

Results land in `results/`.

### Generate the Markdown report

```bash
make generate-results
```

Writes `RESULTS.md` with overall summary, per-metric breakdown, graphs, and
per-turn judge reasons.

---

## Viewing results in the dashboard

The [lightspeed-evaluation dashboard](https://github.com/lightspeed-core/lightspeed-evaluation/tree/main/dashboard)
provides an interactive web UI for exploring evaluation results, comparing runs,
and re-running evaluations from the browser.

### 1. Install (once)

```bash
make setup-dashboard
```

Sparse-clones just the `dashboard/` folder from `lightspeed-evaluation` and runs
`npm install`. Re-run after removing `dashboard/` to upgrade.

### 2. Start the dashboard

```bash
make run-dashboard
```

Opens the dev server at **<http://localhost:5173>** with the project paths pre-configured:

| Variable | Value | Description |
|---|---|---|
| `LS_EVAL_SYSTEM_CFG_PATH` | `../system.yaml` | Evaluation system configuration |
| `LS_EVAL_DATA_PATH` | `../scenarios` | Conversations directory |
| `LS_EVAL_REPORTS_PATH` | `../results` | Results directory |
| `LS_EVAL_DASHBOARD_RUN_ENABLED` | `true` | Allow triggering runs from the browser |

`API_KEY` and `OPENAI_API_KEY` are injected automatically (same as the eval commands).

---

## Makefile reference

### Setup

| Target | Description |
|--------|-------------|
| `make setup` | Create `venv/` and install the evaluation framework |
| `make setup-vector-db` | Extract the Kiali RAG index from the BYOK image |
| `make setup-dashboard` | Clone and install the web dashboard |

### Services

| Target | Description |
|--------|-------------|
| `make run-ols` | Run the LightSpeed service container (port 8080) |
| `make run-mcp` | Start the Kubernetes MCP server with Kiali toolset (port 8089) |
| `make run-dashboard` | Start the evaluation dashboard (port 5173) |

### Evaluation

| Target | Description |
|--------|-------------|
| `make all` | Run all conversations in `scenarios/conversations.yaml` |
| `make fix_bookinfo_fault_injection` | Run one conversation by ID |
| `make check_mesh_status` | Run one conversation by ID |
| `make generate-results` | Generate `RESULTS.md` from the latest run |
| `make clean-results` | Wipe the `results/` directory |

### Overridable variables

| Variable | Default | Description |
|---|---|---|
| `KIALI_ENDPOINT` | `https://kiali-istio-system.apps-crc.testing/` | Kiali UI/API URL |
| `OLS_IMAGE` | `quay.io/openshift-lightspeed/lightspeed-service-api:latest` | OLS image |
| `KIALI_RAG_DB` | `quay.io/kiali/kiali-byok:latest` | BYOK image for vector DB |
| `LSE_TAG` | `main` | Branch/tag for `make setup-dashboard` |
| `MCP_CONFIG` | `mcp_config.toml` | MCP server config file |
| `OPENAI_KEY_FILE` | `~/.openai/openai_api_key.txt` | OpenAI key file path |
| `GEMINI_KEY_FILE` | `~/.gemini/google_api_key.txt` | Gemini key file path |

---

## Project layout

```
.
├── Makefile                          # Setup and service targets
├── scenarios/
│   ├── scenarios.mk                  # Evaluation targets (included by Makefile)
│   ├── conversations.yaml            # All evaluation conversations
│   └── fix_bookinfo_fault_injection/ # Scenario scripts and fixtures
│       ├── setup.sh
│       ├── cleanup.sh
│       └── fixtures/manifests.yaml
├── system.yaml                       # Evaluation system config (judge LLM + metrics)
├── mcp_config.toml                   # Kubernetes MCP server config
├── olsconfig/
│   └── olsconfig-openai.yaml         # OLS service config (LLM provider + RAG index)
├── scripts/
│   └── generate_results.py           # RESULTS.md generator
├── vector_db/                        # git-ignored — from make setup-vector-db
├── dashboard/                        # git-ignored — from make setup-dashboard
└── results/                          # git-ignored — evaluation output
```

---

## Conversations (`scenarios/conversations.yaml`)

All conversations are defined in a single YAML file. Each can optionally include
`setup_script` and `cleanup_script` paths (resolved relative to the YAML file).

### `check_mesh_status`

Asks the agent to report the current health of the Istio service mesh using Kiali.
No cluster state is modified. Validates that the agent calls `kiali_get_mesh_status`.

**Metrics:** `custom:answer_correctness` · `custom:keywords_eval` · `custom:tool_eval`

### `fix_bookinfo_fault_injection`

Injects a `fault.abort` rule into the `ratings` VirtualService (100% HTTP 503),
waits 60 s for Kiali metrics to reflect the fault, then asks the agent to diagnose
and fix the issue. Cleanup removes the fault rule and waits 60 s for metrics to
stabilise.

**Metrics:** `custom:answer_correctness` · `custom:keywords_eval` · `custom:tool_eval`

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `ERROR: venv not found` | `make setup` |
| `ERROR: python3 >= 3.11 is required` | Install Python 3.11+ |
| `ERROR: Port 8080 not open` | `make run-ols` in a separate terminal |
| `ERROR: Port 8089 not open` | `make run-mcp` in a separate terminal |
| `ERROR: Key file not found` | `echo "sk-..." > ~/.openai/openai_api_key.txt` |
| `ERROR: Bookinfo is not running` | `./install-bookinfo-demo.sh -tg true` |
| `SKIP vector_db/kiali already exists` | `rm -rf vector_db/kiali && make setup-vector-db` |
| `SKIP dashboard/ already exists` | `rm -rf dashboard && make setup-dashboard` |
| All evaluations ERROR, 0 tokens | `OPENAI_API_KEY` expired — re-export it |
