# CMR Specialist Automation Agent

High-traffic, case-centered, Python-first automation product for the Central Motor Registry (CMR) framework under the Nigeria Police Force.

> **Foundational Architectural Law:**  
> The AI is replaceable. The case record, knowledge history, and audit trail are the product memory. A conversation is temporary. A case is durable. An answer is useful only when its source and effect can be traced. **AI reasons; software decides.**

---

## Current Roadmap & Phase Implementation Status

- [x] **Phase 0: Foundation & Platform Infrastructure**
  - Async PostgreSQL session factory, connection pooling, and Declarative Base with UUID primary keys.
  - JWT generation/validation, bcrypt password hashing, and role-based access control (RBAC).
  - Append-only audit logging sink with automatic PII masking (BVN, NIN, passwords, card numbers).
  - Telemetry middleware injecting `X-Request-ID` and structured `structlog` context.
  - Health check endpoint `GET /health`.

- [x] **Phase 1: Durable Core & Case State Machine**
  - Core database entities: `Person`, `Case`, `CaseEvent`, `Conversation`, `Message`, `ExtractedFact`.
  - Strict case lifecycle transitions: `NEW -> TRIAGED -> WAITING <-> IN_REVIEW -> RESOLVED -> CLOSED`.
  - Named transition commands: `Triage`, `Assign`, `RequestInfo`, `CustomerReply`, `Resolve`, `Reopen`, `Close`.
  - Alembic initial schema migration (`0001_initial_schema.py`) and pgvector extension initialization.

- [x] **Phase 2: Customer Surface**
  - `POST /api/v1/customer/questions`: Ingest inquiry, binary routing, grounded answers with citations.
  - `POST /api/v1/customer/cases`: Open formal support case pre-populating extracted facts from conversation history.
  - `GET /api/v1/customer/cases/{id}`: Detailed case timeline, requested actions, messages, and facts.
  - `POST /api/v1/customer/cases/{id}/messages`: Customer response submission (automatically shifts case from `WAITING` to `IN_REVIEW`).

- [x] **Phase 3: Support Console Surface**
  - `GET /api/v1/support/people`: Cross-case search by name, phone, email, or verified identity identifier.
  - `GET /api/v1/support/cases`: Case queue filtering by status, priority (`LOW`, `NORMAL`, `HIGH`, `URGENT`), category, assignee, and SLA.
  - `POST /api/v1/support/cases/{id}/commands/{cmd}`: Execution of named staff lifecycle commands.
  - `POST /api/v1/support/cases/{id}/notes`: Internal confidential staff notes and decisions.

- [x] **Phase 5: AI Grounding, Routing & Traceability**
  - `app/ai/router.py`: Binary router classifying `INFORMATIONAL` vs `SUPPORT_REQUEST` with automated fact extraction.
  - `app/ai/retrieval.py`: Vector cosine similarity search querying **ONLY** chunks associated with `ACTIVE` document versions.
  - `app/ai/inference.py`: Grounded response generator enforcing strict `[Doc: title, Chunk: id]` citations and system boundary guardrails (forbidding fabrication of payment verifications, ownership certifications, or NIMC availability).
  - `app/ai/models.py`: `AIRun` entity recording model parameters, prompt version, retrieved chunks, citations, tokens, latency, and full reconstruction trace.
  - `GET /api/v1/customer/ai-runs/{run_id}`: Trace inspection endpoint for auditing every AI decision.

- [x] **Phase 6: Operations Dashboard & Reliability**
  - Observability dashboard across 4 pillars: Service Health, Customer Flow, AI Quality, and Knowledge Base.
  - Durable append-only `audit_events` table with guaranteed automatic PII masking (BVN, NIN, card numbers, passwords).
  - `GET /api/v1/ops/dashboard`: Aggregated metrics and SLO status tracking.
  - `GET /api/v1/ops/audit-logs`: Searchable audit logs filtered by `request_id`, `actor_role`, `action`, and date ranges.
  - `GET /api/v1/ops/requests/{request_id}`: Phase 6 Exit Check failure diagnosis reconstructing events, AI execution traces, and errors by Request ID.
  - `GET /api/v1/ops/runbooks`: Incident diagnosis and recovery runbooks for error spikes, AI latency, ingestion backlog, and SLA breaches.
  - `GET /health/ready`: Database connectivity readiness probe.

- [ ] **Phase 4: Knowledge Base & Vector Publishing (Ingestion Worker & Pipeline)**
  - Background worker PDF parser (`pypdf`), chunking pipeline, and atomic draft-to-active version promotion.

- [x] **Phase 7: Launch, Verification & Testing**
  - Database seeder (`scripts/seed_db.py`): Seeds default admin/support accounts, active procedural documents with embeddings, and realistic sample cases.
  - End-to-end integration suite (`tests/integration/test_e2e_lifecycle.py`): Full Question -> Case Created -> Triaged -> In Review -> Resolved -> Closed flow.
  - Simulated 2x peak load SLO testing (`tests/integration/test_load_slo.py`): Validates 0% error rate, non-AI p95 < 500ms, and AI answer p95 < 12s.
  - Disaster Recovery drill (`scripts/disaster_recovery_drill.py`): Point-in-time state snapshot/restore continuity and container rollback audit.

---

## Directory Structure

```text
app/
  api/
    v1/
      customer/      # Customer inquiry, case opening, and AI trace routes
      support/       # Staff queue filtering, command execution, and internal notes
      ops/           # Telemetry dashboard, request tracing, and incident runbooks
  cases/             # Durable case domain, entities, commands, and strict state machine
  knowledge/         # Documents, versioning (DRAFT, ACTIVE, RETIRED), and Chunk models
  ai/                # Intent routing, active vector retrieval, inference, guardrails, AIRun
  platform/          # Async SQLAlchemy engine, JWT/RBAC auth, audit logging, telemetry, vector type
scripts/             # Database seeder (seed_db.py) and disaster recovery drill (disaster_recovery_drill.py)
worker/              # Background worker for document ingestion and async tasks
migrations/          # Versioned Alembic migrations
tests/               # Unit, grounding, surface, and end-to-end integration test suites
```

---

## Running the Application & Tests

### Environment Setup
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### Run Tests (100% Passing - 41/41 tests)
```bash
pytest -v
```

### Run E2E & Load SLO Integration Tests
```bash
pytest tests/integration/ -v
```

### Seed Database
```bash
python3 scripts/seed_db.py
# Or with specific database target:
python3 scripts/seed_db.py --db postgresql+asyncpg://postgres:postgres@localhost:5432/friedin_cmr
```

### Execute Disaster Recovery Drill
```bash
python3 scripts/disaster_recovery_drill.py
```

### Run Database Migrations
```bash
alembic upgrade head
```

### Start Development Server
```bash
uvicorn app.main:create_app --factory --reload --port 8000
```
