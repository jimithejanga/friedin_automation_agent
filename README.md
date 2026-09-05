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

- [ ] **Phase 4: Knowledge Base & Vector Publishing (Ingestion Worker & Pipeline)**
  - Background worker PDF parser (`pypdf`), chunking pipeline, and atomic draft-to-active version promotion.

- [ ] **Phase 6: Operations Dashboard & Reliability**
  - Observability dashboard, SLO tracking (availability, p95 latency, answer time, ingestion), and incident diagnosis runbooks.

- [ ] **Phase 7: Launch, Verification & Testing**
  - Database seeder (`scripts/seed_db.py`), 2x load testing, and disaster recovery restore drill.

---

## Directory Structure

```text
app/
  api/
    v1/
      customer/      # Customer inquiry, case opening, and AI trace routes
      support/       # Staff queue filtering, command execution, and internal notes
  cases/             # Durable case domain, entities, commands, and strict state machine
  knowledge/         # Documents, versioning (DRAFT, ACTIVE, RETIRED), and Chunk models
  ai/                # Intent routing, active vector retrieval, inference, guardrails, AIRun
  platform/          # Async SQLAlchemy engine, JWT/RBAC auth, audit logging, telemetry, vector type
worker/              # Background worker for document ingestion and async tasks
migrations/          # Versioned Alembic migrations
tests/               # Unit, integration, grounding, and surface test suites
```

---

## Running the Application & Tests

### Environment Setup
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### Run Tests
```bash
pytest -v
```

### Run Database Migrations
```bash
alembic upgrade head
```

### Start Development Server
```bash
uvicorn app.main:create_app --factory --reload --port 8000
```
