# Kiali — LightSpeed Troubleshooting Evaluation

> Latest evaluation results: **[RESULTS.md](RESULTS.md)**

End-to-end evaluation of the [OpenShift LightSpeed](https://github.com/openshift/lightspeed-service)
troubleshooting agent against a live Kiali / Istio cluster.

Each scenario deploys a specific broken or misconfigured workload, asks the agent to diagnose it,
and scores the response against an expected answer using LLM-based metrics.

---

## Prerequisites

### 1. CRC cluster with Istio and Kiali

You need a running [CRC (OpenShift Local)](https://developers.redhat.com/products/openshift-local)
cluster with Istio and Kiali installed.

```bash
# Start CRC
crc start

# Log in
eval $(crc oc-env)
oc login -u developer -p developer https://api.crc.testing:6443

# Verify Kiali is running
oc get pods -n istio-system | grep kiali
```

The default Kiali endpoint for CRC is:

```
https://kiali-istio-system.apps-crc.testing/
```

This is already the default value of `KIALI_ENDPOINT` in the Makefile.

### 2. Bookinfo application with traffic generation

The evaluation scenarios query live mesh traffic data through Kiali. The
[Bookinfo](https://istio.io/latest/docs/examples/bookinfo/) sample application must be
deployed and actively receiving traffic.

Use the Kiali hack script to install Bookinfo **and** start the traffic generator in one step:

```bash
curl -L https://raw.githubusercontent.com/kiali/kiali/master/hack/istio/install-bookinfo-demo.sh \
  -o install-bookinfo-demo.sh
chmod +x install-bookinfo-demo.sh

# Install Bookinfo + enable the traffic generator (-tg)
./install-bookinfo-demo.sh -tg true
```

The `-tg true` flag deploys the Kiali traffic generator alongside Bookinfo, which continuously
sends requests across all service versions so Kiali always has fresh metrics to report.

Verify the application is running:

```bash
oc get pods -n bookinfo
```

All pods should be in `Running` state before executing any evaluation scenarios.

### 3. API key

The judge LLM and the OLS provider use the configured LLM (see `olsconfig/olsconfig-openai.yaml`).
Store your key in a file so both the Makefile and the OLS container can read it:

```bash
# OpenAI
mkdir -p ~/.openai
echo "sk-..." > ~/.openai/openai_api_key.txt

# Google Gemini (if using the Gemini provider)
mkdir -p ~/.gemini
echo "AIza..." > ~/.gemini/google_api_key.txt
```

Alternatively, export the variable directly (the Makefile will detect it and skip the file):

```bash
export OPENAI_API_KEY="sk-..."
```

### 4. Node.js (for the MCP server)

The Kubernetes MCP server is distributed as an npm package and requires Node.js ≥ 18:

```bash
node --version   # should be v18 or higher
```

### 5. Podman (for the OLS service)

The LightSpeed service runs as a container:

```bash
podman --version
```

### 6. Python 3.11+

Required by the evaluation framework:

```bash
python3 --version   # should be 3.11 or higher
```

---

## Setup

### 1. Install the evaluation framework

```bash
make setup
```

Creates `venv/` and installs `lightspeed-evaluation` from GitHub. Fails early if Python is
missing or older than 3.11.

### 2. Extract the Kiali RAG vector database

OLS is configured to use a Kiali knowledge base built from [kiali.io](https://kiali.io)
documentation using the [kiali-byok](https://github.com/kiali/kiali-byok) BYOK tool.
The pre-built index is published as a container image and must be extracted locally before
starting OLS.

```bash
make setup-vector-db
```

This command:
1. Pulls `quay.io/kiali/kiali-byok:latest`
2. Creates a temporary container and copies `/rag/vector_db/kiali` out of it
3. Places the index under `vector_db/kiali/` on your host
4. Removes the temporary container

The extraction is skipped automatically if `vector_db/kiali/` already exists.
To force a refresh (e.g. after a new image release):

```bash
rm -rf vector_db/kiali && make setup-vector-db
```

The vector database is then mounted into the OLS container at `/app-root/vector_db` by
`make run-ols`, and `olsconfig/olsconfig-openai.yaml` references it under
`ols_config.reference_content.indexes`:

```yaml
reference_content:
  embeddings_model_path: ./embeddings_model
  indexes:
    - product_docs_index_path: ./vector_db/kiali
      product_docs_index_id: kiali-istio-docs
```

This gives the OLS assistant grounded knowledge about Kiali and the Istio service mesh,
improving the quality of its troubleshooting responses.

---

## Running the evaluations

The evaluations require **two background services** and the **eval runner** in separate terminals.

### Terminal 1 — Kubernetes MCP server

```bash
make run-mcp
# Override the Kiali endpoint if needed:
make run-mcp KIALI_ENDPOINT=https://kiali-istio-system.apps-crc.testing/
```

Starts the Kubernetes MCP server on port **8089** with the Kiali toolset enabled.

### Terminal 2 — OLS LightSpeed service

```bash
make run-ols
```

Starts the LightSpeed API container on port **8080**. Automatically extracts the vector
database first if it has not been set up yet. Mounts:

| Host path | Container path | Purpose |
|-----------|---------------|---------|
| `./olsconfig/` | `/app-root/config/` | OLS configuration |
| `./vector_db/` | `/app-root/vector_db/` | Kiali RAG index |
| `~/.openai/openai_api_key.txt` | `/app-root/openai_api_key.txt` | OpenAI API key |
| `~/.gemini/google_api_key.txt` | `/app-root/google_api_key.txt` | Gemini API key |

### Terminal 3 — Run evaluations

Once both services are up, run all scenarios or a specific one:

```bash
# Run all scenarios
make all

# Run a single scenario
make fix_bookinfo_fault_injection
```

Before running, Make automatically checks that:
- `venv/` exists (run `make setup` if not)
- `OPENAI_API_KEY` is set or loadable from `~/.openai/openai_api_key.txt`
- Port **8080** is open (OLS service)
- Port **8089** is open (MCP server)
- Bookinfo pods are running in the `bookinfo` namespace

Results are written to `results/`.

---

## Makefile reference

| Target | Description |
|--------|-------------|
| `make setup` | Create `venv/` and install the evaluation framework |
| `make generate-results` | Generate `RESULTS.md` from the latest run in `results/` |
| `make setup-vector-db` | Extract the Kiali RAG vector database from the BYOK image |
| `make run-ols` | Run the LightSpeed service container on port 8080 (runs `setup-vector-db` first) |
| `make run-mcp` | Start the Kubernetes MCP server on port 8089 |
| `make all` | Run all evaluation scenarios |
| `make fix_bookinfo_fault_injection` | Run the Bookinfo fault injection scenario only |

### Overridable variables

| Variable | Default | Description |
|----------|---------|-------------|
| `KIALI_ENDPOINT` | `https://kiali-istio-system.apps-crc.testing/` | Kiali UI/API URL |
| `OLS_IMAGE` | `quay.io/openshift-lightspeed/lightspeed-service-api:latest` | OLS container image |
| `KIALI_RAG_DB` | `quay.io/kiali/kiali-byok:latest` | BYOK image to extract the vector DB from |
| `MCP_CONFIG` | `mcp_config.toml` | MCP server config file |
| `OPENAI_KEY_FILE` | `~/.openai/openai_api_key.txt` | Path to OpenAI API key file |

---

## Project layout

```
.
├── Makefile
├── README.md
├── system.yaml                       # Evaluation system config (judge LLM + metrics)
├── scenario_evals.yaml               # Evaluation conversations and expected answers
├── mcp_evals.yaml                    # MCP-based live evaluation data
├── mcp_config.toml                   # Kubernetes MCP server configuration
├── olsconfig/
│   └── olsconfig-openai.yaml         # OLS service configuration (LLM provider + RAG index)
├── vector_db/                        # Generated by make setup-vector-db (git-ignored)
│   └── kiali/                        # Kiali RAG index (LlamaIndex / FAISS format)
└── scenarios/
    └── fix_bookinfo_fault_injection/
        ├── setup.sh
        ├── cleanup.sh
        └── fixtures/manifests.yaml
```

---

## Scenarios

### `fix_bookinfo_fault_injection`

**Category:** Istio Fault Injection Diagnosis  
**Tag:** `fix_bookinfo_fault_injection`

Applies a VirtualService fault rule that aborts **100% of requests** to the `ratings` service
with HTTP 503. Waits 60 seconds for Kiali metrics to reflect the fault, then runs a two-turn
conversation:

1. *"My Bookinfo app is having problems, users see errors — what is wrong?"*
2. *"How can I fix it?"*

The agent must identify the fault injection in the `ratings` VirtualService and propose
removing the `fault.abort` block as the fix. After the eval, cleanup removes the
VirtualService and waits another 60 seconds for metrics to stabilise.

**Metric:** `custom:answer_correctness`

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `ERROR: venv not found` | Run `make setup` |
| `ERROR: python3 >= 3.11 is required` | Install Python 3.11+ and retry |
| `ERROR: Nothing is listening on port 8080` | Run `make run-ols` in a separate terminal |
| `ERROR: Nothing is listening on port 8089` | Run `make run-mcp` in a separate terminal |
| `ERROR: Key file not found` | Run `echo "sk-..." > ~/.openai/openai_api_key.txt` |
| `ERROR: Bookinfo application is not running` | Run `./install-bookinfo-demo.sh -tg true` |
| `SKIP vector_db/kiali already exists` | Run `rm -rf vector_db/kiali && make setup-vector-db` to refresh |
