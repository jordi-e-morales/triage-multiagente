# AGNTCY Mortgage Underwriting Demo — Python / Streamlit

A fully self-contained Python implementation of the AGNTCY Mortgage Underwriting Demo, showcasing the **Internet of Agents** framework through a live mortgage loan origination pipeline. This version requires no Node.js, no database server, and no external inference server — everything runs in a single Python process.

---

## What This Demo Shows

This application demonstrates all four pillars of the [AGNTCY framework](https://github.com/agntcy):

| Pillar | What You See |
|--------|-------------|
| **Discover** | Agent Directory with 7 registered agents, OASF v1.0 capability schemas, DID-based identity |
| **Compose** | 7-agent LangGraph-style orchestration DAG: sequential → parallel → sequential |
| **Deploy** | SLIM Protocol v0.1 message envelopes with MLS encryption flags and DID routing |
| **Evaluate** | OpenTelemetry-style per-agent spans, full audit trail, per-hop latency waterfall |

---

## Architecture

```
Application Form / Test Scenario
          │
          ▼
┌─────────────────────┐
│  Application        │  Stage 1 — Sequential
│  Processor Agent    │
└─────────┬───────────┘
          │
    ┌─────┴──────────────────────┐
    │             │              │
    ▼             ▼              ▼
┌───────┐   ┌──────────┐  ┌──────────┐
│Credit │   │Collateral│  │Compliance│  Stage 2 — Parallel
│Analyz.│   │Valuator  │  │Checker   │
│XGBoost│   │LLM+Rules │  │GNN+LLM   │
└───┬───┘   └────┬─────┘  └────┬─────┘
    └────────────┴──────────────┘
                 │
                 ▼
        ┌────────────────┐
        │  Risk Scorer   │  Stage 3 — Sequential
        │  (XGBoost+LLM) │
        └───────┬────────┘
                │
                ▼
        ┌────────────────┐
        │ Decision Engine│
        │ (LLM + Rules)  │
        └───────┬────────┘
                │
                ▼
        ┌────────────────────────┐
        │ Documentation Generator│
        │ (LLM)                  │
        └────────────────────────┘
```

---

## AI / ML Stack

### Large Language Models

Every agent uses an LLM for reasoning, structured JSON output, and natural language explanations. The LLM provider is configurable at runtime via the Settings page:

| Provider | Models | Notes |
|----------|--------|-------|
| **OpenAI** | gpt-4o, gpt-4o-mini, gpt-4-turbo | Recommended for production demos |
| **Google Gemini** | gemini-2.5-flash, gemini-2.5-pro, gemini-1.5-pro | Fast and cost-effective |
| **Anthropic** | claude-opus-4-5, claude-sonnet-4-5, claude-3-haiku | Strong reasoning |
| **Ollama (local)** | llama3.2, mistral, qwen2.5, phi3 | Zero cost, runs offline |

All LLM calls use **structured JSON output** (`response_format: json_schema`) — every agent returns a strictly typed JSON object, ensuring interoperability across the pipeline.

### Machine Learning Models

Two real ML models are trained on synthetic mortgage data at first startup and cached locally:

#### XGBoost Credit Risk Model
- **Task**: Probability of default (binary classification)
- **Training data**: 50,000 synthetic mortgage records with realistic default rates
- **Features**: credit score, annual income, loan amount, property value, LTV, DTI, employment years, self-employment flag, late payment history, geographic risk
- **Performance**: AUC ~0.79, trained with 200 estimators, max depth 6
- **Used by**: Credit Analyzer Agent (primary credit risk score), Risk Scorer Agent (composite risk)

#### GNN Fraud Detector (2-layer Graph Convolutional Network)
- **Task**: Fraud ring / suspicious network detection (binary node classification)
- **Architecture**: 2-layer GCN (10 → 32 → 16 → 2), trained with PyTorch Geometric
- **Graph construction**: Nodes = loan applications; edges = shared credit/income buckets (proxy for shared employer, address, or identity)
- **Performance**: AUC ~0.83, fraud recall ~90%
- **Used by**: Compliance Checker Agent (BSA/AML fraud risk signal)

Both models are trained once on startup and cached in `ml/cached_models/` for subsequent runs.

---

## AGNTCY Protocol Visibility

The demo emulates three AGNTCY framework protocols, making them visible in the UI:

### SLIM (Secure Low-Latency Interactive Messaging)
Every inter-agent message is recorded as a full SLIM envelope:
```json
{
  "message_id": "msg_abc123",
  "session_id": "sess_xyz",
  "from_did": "did:agntcy:mortgage:credit-analyzer",
  "to_did": "did:agntcy:mortgage:risk-scorer",
  "pattern": "request-reply",
  "encryption": "MLS",
  "identity_verified": true,
  "payload_schema": "CreditAnalysisResult/v1",
  "payload_size_bytes": 847,
  "latency_ms": 1243
}
```

### OpenTelemetry Spans
Each agent emits a span with:
- Trace ID and span ID (W3C TraceContext format)
- Parent span ID (pipeline root → agent)
- Start/end timestamps, duration
- Attributes: agent version, DID, pipeline stage, ML model used
- Events: `agent.started`, `agent.llm_called`, `agent.ml_predicted`, `agent.completed`

### Agent Directory (DIR)
The full announce → discover → resolve sequence is recorded:
- `announce`: each agent registers its OASF capabilities at pipeline start
- `discover`: the orchestrator queries for agents matching required capabilities
- `resolve`: DID resolution and identity verification

---

## Pages

| Page | Description |
|------|-------------|
| **Dashboard** | Metrics: approval rate, avg processing time, avg interest rate, compliance pass rate |
| **New Application** | Full mortgage application form with borrower, employment, loan, and property sections |
| **Applications** | List of all submitted applications with status and quick-view decision |
| **Test Scenarios** | One-click launch for 5 pre-built scenarios (Prime, Good, Denied, Compliance Trigger, Complex) |
| **Agent Directory** | All 7 agents with OASF capability schemas, DID identities, and active status |
| **Settings** | LLM provider switcher, API key management, Ollama connection tester, ML model status |

After submitting an application, the **Pipeline View** page shows:
- Live agent execution status with real-time updates
- Decision output with full explainability (approval verdict, rate, terms, key factors)
- Compliance report (Fair Lending, BSA/AML, regulatory limits)
- SLIM Message Bus (all inter-agent messages with full protocol envelopes)
- OTel Trace Waterfall (per-agent span timeline with latency bars)
- Agent Discovery Flow (DIR announce/discover/resolve sequence)
- Full Audit Trail (every event with timestamps and JSON payloads)

---

## Quick Start

### Prerequisites

- Python 3.10+
- An API key for at least one LLM provider (OpenAI, Gemini, Anthropic) **or** [Ollama](https://ollama.ai) running locally

### Installation

```bash
git clone https://github.com/agntcy/agntcy-mortgage-demo
cd agntcy-mortgage-python

pip install -r requirements.txt
```

### Configure LLM Provider

**Option A — Environment variable (fastest):**
```bash
export OPENAI_API_KEY=sk-...          # for OpenAI
export GOOGLE_API_KEY=AIza...         # for Gemini
export ANTHROPIC_API_KEY=sk-ant-...   # for Anthropic
```

**Option B — Settings page:** Launch the app and configure the provider interactively in the Settings page. API keys are stored in Streamlit session state (not persisted to disk).

**Option C — Ollama (local, zero cost):**
```bash
ollama serve
ollama pull llama3.2   # or mistral, qwen2.5, phi3
# Set provider to "Ollama" in Settings, base URL: http://localhost:11434
```

### Run

```bash
streamlit run app.py
```

The app opens at `http://localhost:8501`. On first run, the ML models will train automatically (~30 seconds). Subsequent runs load cached models instantly.

---

## Demo Walkthrough

### Recommended sequence for a live audience

1. **Settings** — show the LLM provider switcher. If running locally, switch to Ollama to demonstrate zero-cost local inference.

2. **Agent Directory** — walk through the 7 agents, their OASF capability schemas, and DID identities. Explain the "Internet of Agents" discovery model.

3. **Test Scenarios → Prime Borrower** — click "Run Scenario". Watch the pipeline execute in real time.

4. **Pipeline View → SLIM Messages** — show the inter-agent message envelopes. Point out the DID routing, MLS encryption flag, and per-hop latency.

5. **Pipeline View → OTel Trace** — show the waterfall. Explain how OpenTelemetry spans give you full observability across a distributed agent system.

6. **Pipeline View → Agent Discovery** — show the DIR announce/discover/resolve sequence. Explain how agents find each other without hardcoded endpoints.

7. **Test Scenarios → Compliance Trigger** — run the second scenario. Show how the GNN fraud signal changes the compliance outcome.

8. **Test Scenarios → Denied** — run the third scenario. Compare the decision rationale with the Prime Borrower run side by side.

---

## Project Structure

```
agntcy-mortgage-python/
├── app.py                    # Streamlit entry point and navigation
├── requirements.txt
├── README.md
│
├── agents/
│   ├── __init__.py
│   ├── llm_provider.py       # Multi-provider LLM abstraction (OpenAI, Gemini, Anthropic, Ollama)
│   └── pipeline.py           # 7-agent orchestration pipeline
│
├── ml/
│   ├── __init__.py
│   ├── models.py             # XGBoost + GNN training and inference
│   └── cached_models/        # Auto-generated model cache (gitignored)
│
├── protocols/
│   ├── __init__.py
│   └── emitter.py            # SLIM / OTel / DIR protocol event emitter
│
├── data/
│   ├── __init__.py
│   └── scenarios.py          # 5 pre-built test scenarios
│
└── pages/
    ├── dashboard.py
    ├── apply.py
    ├── applications.py
    ├── scenarios.py
    ├── agent_directory.py
    ├── settings.py
    └── _pipeline_view.py     # Shared pipeline detail view component
```

---

## Configuration

| Environment Variable | Description | Default |
|---------------------|-------------|---------|
| `OPENAI_API_KEY` | OpenAI API key | — |
| `GOOGLE_API_KEY` | Google Gemini API key | — |
| `ANTHROPIC_API_KEY` | Anthropic API key | — |
| `OLLAMA_BASE_URL` | Ollama server base URL | `http://localhost:11434` |

All settings can also be configured interactively in the **Settings** page without environment variables.

---

## AGNTCY Framework References

- [AGNTCY GitHub Organisation](https://github.com/agntcy)
- [AGNTCY Documentation](https://docs.agntcy.org)
- [SLIM Specification](https://github.com/agntcy/slim-spec)
- [OASF Schema](https://github.com/agntcy/oasf)
- [Agent Directory Spec](https://github.com/agntcy/dir-spec)
- [CoffeeAgntcy Reference Implementation](https://github.com/agntcy/CoffeeAgntcy)

---

## Related

- **Node.js / React version**: See the `agntcy-mortgage-demo` directory for the full-stack TypeScript version with a persistent database, real-time polling, and a production-grade web UI.

---

## License

Apache 2.0 — consistent with the AGNTCY framework licence.
