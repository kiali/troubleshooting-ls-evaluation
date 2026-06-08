# Development Guide — Step-by-step Setup and Evaluation Run

This guide walks through every step needed to go from a clean checkout to running
evaluations against a live Kiali / Istio cluster.

---

## 1. Prerequisites

### Cluster

A running [CRC (OpenShift Local)](https://developers.redhat.com/products/openshift-local)
cluster with Istio and Kiali installed:

```bash
crc start
eval $(crc oc-env)
oc login -u developer -p developer https://api.crc.testing:6443
oc get pods -n istio-system | grep kiali   # verify Kiali is up
```

### Bookinfo + traffic generator

```bash
curl -L https://raw.githubusercontent.com/kiali/kiali/master/hack/istio/install-bookinfo-demo.sh \
  -o install-bookinfo-demo.sh
chmod +x install-bookinfo-demo.sh
./install-bookinfo-demo.sh -tg true   # -tg deploys the Kiali traffic generator
oc get pods -n bookinfo               # all pods must be Running
```

### Runtime dependencies

| Tool | Min version | Check |
|------|-------------|-------|
| Python | 3.11 | `python3 --version` |
| Node.js | 18 | `node --version` |
| Podman | any | `podman --version` |

---

## 2. Credentials

The evaluation uses two independent LLM roles:

| Role | Description |
|------|-------------|
| **OLS backend** | The LightSpeed service that acts as the troubleshooting agent |
| **Judge LLM** | Scores the agent's responses (independent of the OLS backend) |

Choose a **provider** (`openai` or `google`) — both roles are configured per provider.

---

### Provider: `openai` (default)

#### OLS backend + Judge key

```bash
mkdir -p ~/.openai
echo "sk-..."  > ~/.openai/openai_api_key.txt   # OpenAI API key
```

> The same key file is used by both OLS (backend model) and the judge LLM.

#### Gemini key (optional — only needed if olsconfig references the Gemini endpoint)

```bash
mkdir -p ~/.gemini
echo "AIza..." > ~/.gemini/google_api_key.txt
```

---

### Provider: `google`

The `google` provider uses:
- **OLS backend**: Gemini model via Google Vertex AI (`google_vertex` provider in OLS)
- **Judge LLM**: Gemini model via Vertex AI (`vertex` provider in lightspeed-evaluation)

Both require a **GCP service account JSON** file with Vertex AI permissions.

#### Step 1 — Create or download a GCP service account key

In Google Cloud Console → IAM → Service Accounts → create a key (JSON format)
for a service account that has the `Vertex AI User` role.

#### Step 2 — Store the credentials

```bash
mkdir -p ~/.gcp
cp /path/to/downloaded-key.json ~/.gcp/gcp_credentials.txt
```

> The filename must match exactly: `gcp_credentials.txt`

#### Step 3 — (Optional) Store the Gemini API key

The OLS `google_vertex` provider uses the service account JSON — not an API key.
The Gemini API key file is only needed if your `olsconfig-google.yaml` references
the OpenAI-compatible Gemini endpoint instead of Vertex.

```bash
mkdir -p ~/.gemini
echo "AIza..." > ~/.gemini/google_api_key.txt
```

---

## 3. Python environment

```bash
make setup
```

Creates `venv/` and installs `lightspeed-evaluation`. Only needed once (or when
the framework is updated).

---

## 4. Kiali RAG vector database

OLS uses a Kiali knowledge base to improve response quality:

```bash
make setup-vector-db
```

Extracts the index from `quay.io/kiali/kiali-byok:latest` into `vector_db/kiali/`.
Only needed once — re-run after a new release:

```bash
rm -rf vector_db/kiali && make setup-vector-db
```

---

## 5. Running the services (three terminals)

### Terminal 1 — Kubernetes MCP server

```bash
make run-mcp
# Custom Kiali URL:
make run-mcp KIALI_ENDPOINT=https://kiali-istio-system.apps-crc.testing/
```

Starts on port **8089** with the `kiali` toolset enabled.

### Terminal 2 — OLS LightSpeed service

```bash
# Default provider (openai):
make run-ols

# Google Vertex AI provider:
make run-ols PROVIDER=google
```

Starts on port **8080**. Key files are mounted conditionally (skipped if missing):

| Host path | Container path | When used |
|-----------|---------------|-----------|
| `~/.openai/openai_api_key.txt` | `/app-root/openai_api_key.txt` | openai provider |
| `~/.gemini/google_api_key.txt` | `/app-root/google_api_key.txt` | Gemini endpoint |
| `~/.gcp/gcp_credentials.txt` | `/app-root/gcp_credentials.txt` | google provider (Vertex AI) |

### Terminal 3 — Run evaluations

```bash
# Run all scenarios (default provider: openai)
make all

# Run all scenarios with Google provider
make all PROVIDER=google

# Run a single scenario
make fix_bookinfo_fault_injection
make fix_bookinfo_fault_injection PROVIDER=google

# Check current provider config
make check-provider
make check-provider PROVIDER=google
```

---

## 6. Generating the report

```bash
make generate-results            # openai results
make generate-results PROVIDER=google  # google results
```

Writes `RESULTS.md` (summary) and `results/<provider>/<name>.md` (per-scenario detail).

---

## 7. Provider reference

```
PROVIDER=openai  (default)
  OLS config:   olsconfig/olsconfig-openai.yaml
  System cfg:   system/system_openai.yaml
  Results:      results/openai/

PROVIDER=google
  OLS config:   olsconfig/olsconfig-google.yaml
  System cfg:   system/system_google.yaml
  Results:      results/google/
```

---

## 8. Troubleshooting

| Problem | Solution |
|---------|----------|
| `ERROR: venv not found` | `make setup` |
| `ERROR: python3 >= 3.11 is required` | Install Python 3.11+ |
| `ERROR: Port 8080 not open` | Start OLS: `make run-ols` |
| `ERROR: Port 8089 not open` | Start MCP: `make run-mcp` |
| `ERROR: Key file not found` | Create the key file (see §2) |
| `ERROR: Bookinfo is not running` | `./install-bookinfo-demo.sh -tg true` |
| `JSONDecodeError: Expecting value` (google) | `~/.gcp/gcp_credentials.txt` is empty or not valid JSON |
| `LLM Provider NOT provided … google_vertex` | `system_google.yaml` `llm.provider` must be `"vertex"` not `"google_vertex"` |
| All evaluations ERROR, 0 tokens | Judge LLM credentials missing or expired |
| `SKIP vector_db/kiali already exists` | `rm -rf vector_db/kiali && make setup-vector-db` |
