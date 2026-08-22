## ⚡ Enterprise Multi-Agent Customer Support Platform

An enterprise-grade, production-ready AI customer support platform built on top of LangGraph, FastAPI, SQLAlchemy, and OpenTelemetry. This system features adaptive multi-agent intent routing, automated RAG guardrails backed by Chroma DB, real-time async WebSocket token streaming, a secure role-based JWT administrative takeover API, and an end-to-end telemetry observability stack (Prometheus + Jaeger + Grafana).

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

