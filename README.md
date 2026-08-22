## ⚡ Enterprise Multi-Agent Customer Support Platform

An enterprise-grade, production-ready AI customer support platform built on top of LangGraph, FastAPI, SQLAlchemy, and OpenTelemetry. This system features adaptive multi-agent intent routing, automated RAG guardrails backed by Chroma DB, real-time async WebSocket token streaming, a secure role-based JWT administrative takeover API, and an end-to-end telemetry observability stack (Prometheus + Jaeger + Grafana).

> **This README documents the project as reassembled and repaired from the original notebook.** See [What Was Reviewed and Fixed](#-what-was-reviewed-and-fixed) at the bottom for the full list of bugs found and changes made — several of them are load-bearing (the app could not start or would silently misbehave without them).

## 📂 Project Directory Structure

```
customer_support_agent/
├── .github/
│   └── workflows/
│       └── ci.yml                     # GitHub Actions CI workflow for testing & validation
├── alembic/                           # Alembic Database Migration Management Engine
│   ├── versions/                      # Chronological version control history files
│   │   ├── 1a2b3c4d5e6f_initial.py    # Baseline migration schema script
│   │   └── 6f5e4d3c2b1a_add_active.py # Incremental column modification script
│   ├── env.py                         # Migration context runner (hooked to SQLAlchemy Base)
│   └── script.py.mako                 # Migration file template schema layout
├── grafana/
│   ├── dashboards/
│   │   └── langgraph_dashboard.json   # Grafana telemetry dashboard presentation layout
│   └── provisioning/
│       └── dashboards/
│           └── dashboard-provider.yml # Automated dashboard ingestion provider mapper
├── knowledge_source/                  # Input directory for product manuals (Source of Truth)
├── chroma_db/                         # Local database folder for persistent dense vector indexes (created on first ingest)
├── tests/
│   ├── __init__.py
│   ├── test_agent.py                  # Functional graph flow verification (pytest-asyncio)
│   └── test_security.py               # Cryptographic validation & unauthorized endpoint tests
├── alertmanager.yml                   # Slack notifications routing webhook configurations
├── alerts.yml                         # Prometheus monitoring rules for latency and abuse alerts
├── alembic.ini                        # Core Alembic setup configuration and DB string target
├── docker-compose.yml                 # Multi-container enterprise cluster layer orchestrator
├── Dockerfile                         # Multi-stage optimized Docker deployment container instructions
├── entrypoint.sh                      # Container entrypoint: runs migrations, then starts Uvicorn
├── prometheus.yml                     # Prometheus scrape + alerting configuration
├── requirements.txt                   # Production package dependencies baseline pins
├── main.py                            # FastAPI application entrypoint, WebSockets, Auth & Takeover API
├── database_persistence.py            # SQLAlchemy engine/session + UserModel (auth & RBAC)
├── ingest.py                          # Multi-format folder scanning script with temporal TTL injection
├── telemetry.py                       # OpenTelemetry engine initialization and custom alerting spans
├── production_support.db              # Local SQLite database file for multi-turn thread checkpoints (created at runtime)
└── users.db                           # Relational persistent SQLite database file for user profiles (created by Alembic)
```

## ⚡ Production Feature Matrix

- **Multi-Agent Orchestration**: Independent sub-graphs (Order & Tech) overseen by an LLM supervisor to reduce prompt bloat and keep token execution quick.
- **Vector-Backed Guardrail Verification**: Cross-checks technical advice against unexpired knowledge-base artifacts (Chroma dense retrieval, TTL-filtered) using a self-correcting loop and a `revision_count` circuit breaker.
- **Token-Bucket Throttling**: Protects LLM token budgets from malicious traffic or automated message loops, with periodic sweeping of stale per-user buckets.
- **Distributed OpenTelemetry Tracking**: Instruments graph nodes into hierarchical spans that pipe asynchronously via gRPC into Jaeger timelines.
- **Role-Based Admin Interception**: Allows human supervisors to issue an authorized HTTP POST (secured with a signed JWT bearer token) to append instructions directly to the graph state and update the active user's canvas.
- **Human-in-the-Loop Approval Gate**: Refund actions freeze the graph (`interrupt_before`) until an admin explicitly signs off via the takeover endpoint; approval is single-use and cannot be replayed against later requests in the same thread.

> **Note on "Hybrid BM25 + Chroma" search**: the original README and `requirements.txt` advertised hybrid BM25 + dense-vector search (`rank-bm25`, `flashrank`). No code in the notebook actually implemented BM25 retrieval anywhere — only Chroma dense vector search is wired into `live_rag_validation_node`. This README has been corrected to describe what the code actually does. If hybrid search is wanted, it would need to be implemented (e.g. `langchain`'s `EnsembleRetriever` combining a `BM25Retriever` over the same corpus with the existing Chroma retriever) — that work is out of scope for this review pass.

## 🚀 Step-by-Step Operations Runbook

**1. Provision Environment Secrets**

Export your API credentials and security signature parameters into your terminal shell context:

```bash
export OPENAI_API_KEY="sk-proj-your-actual-api-key-here"
export JWT_SECRET_KEY="your-highly-secure-production-signing-passphrase-hex"
```

**2. Populate Knowledge Base & Ingest**

Drop your raw product manuals (`.pdf` or `.txt`) into the target source directory, then trigger the vectorization pipeline:

```bash
mkdir -p knowledge_source
cp /path/to/your/manuals/*.txt ./knowledge_source/

# Run the ingestion parser script
python ingest.py
```

Re-running `python ingest.py` is safe and idempotent — it clears previously-ingested chunks before re-embedding, so editing a manual and re-running won't leave stale duplicate vectors behind (see fixes below).

**3. Initialize Relational Table Schemas**

Apply sequential database changes safely using Alembic to sync your employee profiles layout on disk:

```bash
alembic upgrade head
```

**4. Create an Administrative Employee Profile**

Seed an administrative profile into your persistent `users.db` storage layer:

```bash
python -c "
from database_persistence import SessionLocal, UserModel, pwd_context

db = SessionLocal()
db.add(UserModel(username='supervisor_sarah', email='sarah@company.com', hashed_password=pwd_context.hash('SecurePassword2026!'), role='admin'))
db.commit()
db.close()
print('Sarah committed safely to users.db.')
"
```

New agent accounts can also self-register via `POST /api/v1/auth/register` (defaults to the `agent` role).

**5. Launch the Containerized Cluster Stack**

Spin up your unified core application alongside the complete telemetry scraper grid:

```bash
docker-compose up --build
```

## 🛰️ Monitoring, Testing, & Takeover Endpoints

**Run the Automated Quality Control Tests**

Verify that authorization boundaries, encryption, and state routing pass tests safely inside an in-memory sandbox:

```bash
pytest -v tests/
```

**Accessing Local Observability Dashboards**

Once your containers boot up, you can review system health via the following URLs:

- Web UI Support Portal Interface: `http://localhost:8000/` (connects to active WebSocket stream loops at `/ws/{thread_id}`)
- Prometheus Metrics Endpoint: `http://localhost:8000/metrics` (scraped globally at `http://localhost:9090`)
- Grafana KPI Dashboards Canvas: `http://localhost:3000/` (default logins: `admin` / `admin`)
- Jaeger Distributed Tracing Interface: `http://localhost:16686/` (inspects trace spans delivered via OTLP gRPC on port 4317)

**Simulating an Admin Interception Takeover Flow**

If a ticket escalates, an admin can log in and issue a takeover command to update the live conversation history.

Step A — Authenticate and request an access token:

```bash
curl -X POST "http://localhost:8000/api/v1/auth/login" \
     -H "Content-Type: application/json" \
     -d '{"username": "supervisor_sarah", "password": "SecurePassword2026!"}'
```

Copy the string value from the returned `access_token` field.

Step B — Submit an authorized session override interception:

```bash
curl -X POST "http://localhost:8000/api/v1/support/takeover" \
     -H "Content-Type: application/json" \
     -H "Authorization: Bearer YOUR_COPIED_JWT_STRING_HERE" \
     -d '{
       "thread_id": "secure_ticket_101",
       "override_message": "Hello, I am reviewing your account logs personally. Let me reverse that shipping charge for you instantly."
     }'
```

The manager's statement injects directly into the active user's chat stream, and the underlying LangGraph conversation log is updated (and, for a frozen refund thread, unfrozen) accordingly.

### 🔒 Security & Scaling Guardrails

- **Durable Volume Maps**: the file paths for `users.db` and `production_support.db` are mapped directly to your host machine. If containers cycle, no customer context or employee registry data is lost.
- **Logical Eviction Handling**: vector indices use an absolute `expires_at` timestamp. Chroma metadata filters skip stale entries during retrieval so expired guidance is never surfaced.
- **Deduplicated Slack Alerts**: Alertmanager bundles and groups high-frequency errors, protecting your communication channels from notification fatigue under heavy system strain.
- **Single-use Approval**: an admin's refund sign-off applies to exactly the one frozen request it was granted for and cannot be reused for later refund requests in the same thread (see fixes below).

---

## 🛠 What Was Reviewed and Fixed

This project was supplied as a Jupyter notebook (`Customer_Support_Agent_AI.ipynb`) where each file's content lived in its own code cell. Reassembling it into a real project tree and reading it file-by-file surfaced a number of issues, ranging from "the app cannot start" to a real security bug. Everything below was fixed directly in this delivered copy.

**Missing files (the project could not run at all as originally notebook'd):**

- `database_persistence.py` was imported by `alembic/env.py`, `main.py`, and `tests/test_security.py`, but did not exist anywhere in the notebook — there was an orphaned empty markdown header where its cell should have been. Rewritten from scratch to match both Alembic migrations exactly (`UserModel` with `username`, `email`, `hashed_password`, `role`, `is_active`, `created_at`), plus the `engine`/`SessionLocal`/`get_db()` scaffolding the rest of the app expects.
- `entrypoint.sh` was referenced by the `Dockerfile` (`chmod +x entrypoint.sh`, `ENTRYPOINT ["./entrypoint.sh"]`) but never included — the Docker build would fail at the `chmod` step. Added: runs `alembic upgrade head` then execs Uvicorn. Deliberately does not auto-run `ingest.py` on every boot (see idempotency note below).
- `prometheus.yml` was mounted by `docker-compose.yml` but never included — the `prometheus` container would fail to start with no config to read. Added scrape config targeting `support-agent:8000`, alerting to `alertmanager:9093`, and `rule_files: [alerts.yml]`.

**Missing functionality:**

- `main.py` had no `/api/v1/auth/register` or `/api/v1/auth/login` endpoints and no JWT-issuing function, even though the README's own runbook told operators to `curl` a login endpoint that didn't exist, and `tests/test_security.py` expected to authenticate. Added `RegisterRequestSchema`/`LoginRequestSchema`/`TokenResponseSchema`, `generate_access_token()`, and the two endpoints (password hashing via `passlib`, `is_active` check on login).

**Security bug — refund approval never expired:**

`order_management_agent` set `action_requires_approval = True` to freeze a thread pending admin sign-off on a refund, and the takeover endpoint set `approval_granted = True` to unfreeze it — but nothing ever reset `approval_granted` back to `False`. Once any admin approved *any* refund on a thread, every subsequent refund request on that same thread would sail through the approval gate unchecked, permanently. Fixed by resetting `approval_granted` to `False` immediately after it's consumed, and — because a naive "reset after every pass through this node" fix would re-freeze the graph on the tool's own success message (which also contains the word "refund") — the freeze check is now additionally gated on the triggering message actually being a fresh `HumanMessage`, not a `ToolMessage` or an admin-injected message. Traced the full `order_agent → order_tools → order_agent` loop by hand to confirm the fix doesn't introduce that regression.

**Test suite was not actually testing anything:**

`tests/test_agent.py` mocks `ChatOpenAI.ainvoke` / `with_structured_output(...).ainvoke`, but the four LLM-calling node functions (`supervisor_router_node`, `order_management_agent`, `troubleshooting_agent`, `live_rag_validation_node`) called the synchronous `.invoke()`. The async mocks would never intercept a sync call — tests would either silently no-op or hit the real OpenAI API. Converted all four nodes to `async def` using `await ...ainvoke(...)`.

**Telemetry was fully disconnected:**

- `telemetry.py` built its OpenTelemetry `Resource` with `Resource.attributes = {...}` — this mutates the `Resource` *class* itself as a side effect and binds the local `resource` variable to a plain `dict`, which then breaks `TracerProvider(resource=resource)`. Fixed with the correct `Resource.create({...})`.
- Even if that worked, `main.py` never imported `telemetry` at all — it only did `from opentelemetry import trace`, so the custom `TracerProvider`, OTLP exporter, and latency-alerting `SpanProcessor` set up in `telemetry.py`'s import-time init never activated. Every `tracer.start_as_current_span(...)` call in the app was a silent no-op. Added `import telemetry` to `main.py`.

**RAG guardrail didn't actually enforce its own TTL:**

`live_rag_validation_node` computed and stored an `expires_at` timestamp on every ingested chunk (see `ingest.py`) but never passed a filter to `vector_store.similarity_search(...)`, so expired/stale manual content could still be retrieved and cited. Added `filter={"expires_at": {"$gte": current_epoch}}` to the search call.

**Wrong checkpointer, and instantiated outside an event loop:**

`from langgraph_checkpoint_sqlite import SqliteSaver` imports a module name that doesn't exist on PyPI (compare with the correctly-named `from langgraph.checkpoint.memory import MemorySaver` already used in `tests/test_agent.py`). Separately, the graph is invoked exclusively through async methods (`.ainvoke`, `.astream_events`, `.aupdate_state`), so a *sync* checkpointer was the wrong choice regardless. Switched to `from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver`, and — because that class is an async context manager that needs a running event loop to enter — moved graph compilation out of module level and into a FastAPI `lifespan()` context manager that runs at app startup. This also required updating `tests/test_security.py`'s client fixture to enter `TestClient(app)` as a context manager (`with TestClient(app) as client: yield client`) so lifespan actually runs before the takeover tests execute.

**Other hardening:**

- `TokenBucketLimiter` grew one bucket per distinct user/IP forever with no eviction, an unbounded-memory-growth path under real traffic. Added a `stale_after_sec` threshold and a periodic sweep of inactive buckets.
- `ingest.py`'s `Chroma.from_documents(...)` *appends* to the persisted collection rather than replacing it, so re-running ingestion after editing a manual piled up duplicate, increasingly-stale embeddings alongside the new ones. Added a clear-before-ingest step so re-ingestion is idempotent.
- `docker-compose.yml` used `network_mode: "host"` on every service — Linux-only, silently broken on Docker Desktop for Mac/Windows, and removes Docker's inter-container network isolation. Replaced with a standard bridge network (`support-net`); services now address each other by name (`jaeger:4317`, `support-agent:8000`, etc.) and the compose file behaves identically on any platform.
- `requirements.txt` pinned `langgraph` and `fastapi` but not the SQLite checkpointer package or a `bcrypt` version compatible with the pinned `passlib==1.7.4` (passlib 1.7.4 + bcrypt ≥ 4.1 raises an `AttributeError` at import time due to a well-known compatibility break). Added `langgraph-checkpoint-sqlite` and pinned `bcrypt==4.0.1`.
- Fixed a garbled character in the original README's directory tree (`hooked to大Base` → `hooked to SQLAlchemy Base`), and corrected the feature matrix's "Hybrid BM25 + Chroma" claim (see the note above).

**Flagged, not changed** (lower confidence / judgment calls — worth your own review rather than silently altered):

- Whether FastAPI's `BackgroundTasks` dependency injection behaves as intended on a `@app.websocket(...)` route on the exact FastAPI version you deploy — this pattern has version-dependent quirks and is worth a smoke test on your target version.
- `/metrics` is exposed without authentication. Common and often acceptable behind a private network / reverse proxy, but worth deciding deliberately rather than by default.
- `telemetry.py`'s auto-init-on-import pattern (tracer/provider setup runs as a side effect of `import telemetry`) works but is a somewhat fragile design to unit-test cleanly. A more testable design would use an explicit FastAPI startup hook instead; preserved the original module's designed behavior here rather than restructuring it further.

**Verification method — please read this before treating this as fully tested:**

Every Python file compiles cleanly (`py_compile`), every YAML file parses (`yaml.safe_load`), the Grafana dashboard JSON parses, and `alembic.ini` parses via `configparser`. The refund-approval fix and the checkpointer/lifespan fix were verified by manually tracing the graph's execution paths rather than by running them.

**This project's test suite (`pytest -v tests/`) was *not* executed in this environment.** Unlike a smaller, previously-reviewed project where a full stub-based test run was built and 36 tests were actually executed and passed, this project's dependency surface (FastAPI, LangGraph with async checkpointing/interrupts, SQLAlchemy, Alembic, ChromaDB, langchain-openai, OpenTelemetry, prometheus-client, passlib) is large enough, and the async/interrupt/checkpoint semantics involved are complex enough, that building faithful stubs for all of it risked giving false confidence rather than real verification — and this sandbox cannot reach PyPI to install the real packages. Please run `pip install -r requirements.txt && pytest -v tests/` in an environment with real network access before deploying this.
