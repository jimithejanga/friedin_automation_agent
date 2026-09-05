import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.ai.inference import AIInferenceService
from app.ai.models import AIRun
from app.ai.retrieval import AIRetrievalService, generate_deterministic_mock_embedding
from app.ai.router import BinaryIntentRouter, IntentType
from app.knowledge.models import Chunk, Document, DocumentVersion, DocumentVersionStatus
from app.main import create_app
from app.platform.database import Base, get_db_session


@pytest.fixture
async def async_db():
    """Provides an isolated in-memory SQLite database for AI grounding tests."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )

    async with session_maker() as session:
        yield session, engine

    await engine.dispose()


@pytest.fixture
async def client(async_db):
    """Provides an AsyncClient bound to the FastAPI app with test db session override."""
    session, _ = async_db
    app = create_app()

    async def override_get_db_session():
        session.expire_all()
        yield session
        await session.commit()

    app.dependency_overrides[get_db_session] = override_get_db_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_binary_intent_routing_and_fact_extraction():
    """Verify Binary Router accurately separates INFORMATIONAL queries from SUPPORT_REQUESTs
    and extracts structured facts (VIN, Plate, NIN, State, Phone).
    """
    # 1. Informational query
    info_q = "How do I get motor vehicle clearance in Lagos?"
    result = BinaryIntentRouter.route(info_q)
    assert result.intent == IntentType.INFORMATIONAL
    assert result.prompt_case_creation is False
    assert len(result.citations) >= 1
    assert any(f.fact_key == "registration_state" and f.fact_value == "Lagos" for f in result.extracted_facts)

    # 2. Support request with multiple facts
    support_q = "Help me! My car was stolen in Abuja. VIN: 1HGCR2F83HA123456, plate KJA123AA, NIN: 12345678901, phone 08012345678"
    result = BinaryIntentRouter.route(support_q)
    assert result.intent == IntentType.SUPPORT_REQUEST
    assert result.prompt_case_creation is True
    assert result.suggested_category == "STOLEN_VEHICLE_REPORT"

    fact_dict = {f.fact_key: f.fact_value for f in result.extracted_facts}
    assert fact_dict.get("vin_or_chassis") == "1HGCR2F83HA123456"
    assert fact_dict.get("license_plate") == "KJA123AA"
    assert fact_dict.get("nin") == "12345678901"
    assert fact_dict.get("phone_number") == "08012345678"
    assert fact_dict.get("registration_state") == "Abuja"


@pytest.mark.asyncio
async def test_active_version_retrieval_isolation(async_db):
    """Publishing Guarantee: Cosine similarity vector search queries ONLY chunks
    linked to ACTIVE DocumentVersions. DRAFT and RETIRED chunks MUST be ignored.
    """
    session, _ = async_db

    # 1. Create a Document
    doc = Document(
        title="Nigeria Police CMR Standard Regulations",
        description="Official CMR Regulations",
        category="PROCEDURAL_GUIDE",
        source_url="https://cmr.police.gov.ng/regulations",
    )
    session.add(doc)
    await session.flush()

    # 2. Version 1: RETIRED (Historical text)
    v1_retired = DocumentVersion(
        document_id=doc.id,
        version_number=1,
        status=DocumentVersionStatus.RETIRED,
        content_hash="hash-v1-retired",
    )
    session.add(v1_retired)
    await session.flush()

    chunk_retired = Chunk(
        version_id=v1_retired.id,
        chunk_index=0,
        chunk_id_code="Retired-Sec-1.0",
        content="Old clearance procedure: Physical paper application at state command headquarters.",
        embedding=generate_deterministic_mock_embedding("clearance procedure paper application"),
        token_count=12,
    )
    session.add(chunk_retired)

    # 3. Version 2: ACTIVE (Current authoritative text)
    v2_active = DocumentVersion(
        document_id=doc.id,
        version_number=2,
        status=DocumentVersionStatus.ACTIVE,
        content_hash="hash-v2-active",
    )
    session.add(v2_active)
    await session.flush()

    chunk_active = Chunk(
        version_id=v2_active.id,
        chunk_index=0,
        chunk_id_code="Active-Sec-2.1",
        content="Current digital clearance procedure: Submit vehicle chassis VIN and biometric NIN for automated clearance in 24 hours.",
        embedding=generate_deterministic_mock_embedding("clearance procedure automated digital vin nin"),
        token_count=18,
    )
    session.add(chunk_active)

    # 4. Version 3: DRAFT (Unpublished revision)
    v3_draft = DocumentVersion(
        document_id=doc.id,
        version_number=3,
        status=DocumentVersionStatus.DRAFT,
        content_hash="hash-v3-draft",
    )
    session.add(v3_draft)
    await session.flush()

    chunk_draft = Chunk(
        version_id=v3_draft.id,
        chunk_index=0,
        chunk_id_code="Draft-Sec-3.0",
        content="Unpublished future draft: Instant drone clearance inspection protocol.",
        embedding=generate_deterministic_mock_embedding("clearance procedure drone inspection protocol"),
        token_count=10,
    )
    session.add(chunk_draft)
    await session.commit()

    # 5. Query active chunks
    retrieved = await AIRetrievalService.retrieve_active_chunks(
        session=session,
        query="What is the official vehicle clearance procedure?",
        top_k=5,
        min_similarity=0.1,
    )

    # Assertion: ONLY the ACTIVE version's chunk is returned
    assert len(retrieved) == 1
    assert retrieved[0].chunk_id_code == "Active-Sec-2.1"
    assert "automated clearance in 24 hours" in retrieved[0].content
    assert retrieved[0].version_id == v2_active.id


@pytest.mark.asyncio
async def test_cosine_similarity_ranking(async_db):
    """Verify vector search ranks chunks in descending order of cosine similarity."""
    session, _ = async_db

    doc = Document(title="CMR Service Handbook")
    session.add(doc)
    await session.flush()

    version = DocumentVersion(
        document_id=doc.id,
        version_number=1,
        status=DocumentVersionStatus.ACTIVE,
    )
    session.add(version)
    await session.flush()

    # Chunk A: highly relevant to plate numbers
    chunk_a = Chunk(
        version_id=version.id,
        chunk_index=0,
        chunk_id_code="Sec-Plate-1",
        content="Number plate registration requires biometric capture, license papers, and NIN verification.",
        embedding=generate_deterministic_mock_embedding("number plate registration license papers"),
        token_count=14,
    )
    # Chunk B: somewhat relevant (fees)
    chunk_b = Chunk(
        version_id=version.id,
        chunk_index=1,
        chunk_id_code="Sec-Fee-1",
        content="Statutory fee payments are processed via remita gateway.",
        embedding=generate_deterministic_mock_embedding("statutory fee payments remita"),
        token_count=10,
    )
    session.add_all([chunk_a, chunk_b])
    await session.commit()

    query = "How do I register a new vehicle plate?"
    results = await AIRetrievalService.retrieve_active_chunks(session, query=query, top_k=2)

    assert len(results) >= 1
    assert results[0].chunk_id_code == "Sec-Plate-1"
    if len(results) > 1:
        assert results[0].similarity_score >= results[1].similarity_score


@pytest.mark.asyncio
async def test_boundary_guardrail_enforcement(async_db):
    """System Boundary Constraint: The system MUST NEVER fabricate payment confirmations,
    ownership status, or NIMC availability without verified integration.
    """
    session, _ = async_db

    # Test 1: Payment confirmation attempt
    q_payment = "Please confirm that my payment of 45,000 Naira RRR 2201-9988-1234 has gone through."
    result_payment = await AIInferenceService.generate_grounded_answer(
        session=session,
        question=q_payment,
    )
    assert result_payment.guardrail_triggered is True
    assert "automated agents cannot authoritatively confirm financial transactions" in result_payment.answer
    assert "formal support case" in result_payment.answer
    assert len(result_payment.citations) >= 1

    # Test 2: Ownership confirmation attempt
    q_ownership = "Can you verify vehicle ownership and confirm that I own Toyota Camry chassis 1HGCR2F83HA999999?"
    result_ownership = await AIInferenceService.generate_grounded_answer(
        session=session,
        question=q_ownership,
    )
    assert result_ownership.guardrail_triggered is True
    assert "certify vehicle ownership status" in result_ownership.answer


@pytest.mark.asyncio
async def test_phase_5_exit_check_answer_reconstruction_from_airun(async_db):
    """PHASE 5 EXIT CHECK:
    Every AI answer can be completely reconstructed and verified from stored AIRun records and citations.
    """
    session, _ = async_db

    # 1. Seed active knowledge document
    doc = Document(
        title="CMR Operational Guidelines 2026",
        category="PROCEDURAL_GUIDE",
        source_url="https://cmr.police.gov.ng/guidelines",
    )
    session.add(doc)
    await session.flush()

    ver = DocumentVersion(
        document_id=doc.id,
        version_number=1,
        status=DocumentVersionStatus.ACTIVE,
    )
    session.add(ver)
    await session.flush()

    chunk = Chunk(
        version_id=ver.id,
        chunk_index=0,
        chunk_id_code="Sec-2.1",
        content="Vehicle clearance requires proof of vehicle ownership, owner NIN, and digital chassis verification.",
        embedding=generate_deterministic_mock_embedding("vehicle clearance proof of ownership nin chassis"),
        token_count=16,
    )
    session.add(chunk)
    await session.commit()

    # 2. Execute grounded inference
    question = "What is required for vehicle clearance?"
    inference_result = await AIInferenceService.generate_grounded_answer(
        session=session,
        question=question,
        request_id="req-test-trace-12345",
    )
    await session.commit()

    assert inference_result.ai_run_id is not None
    assert len(inference_result.citations) >= 1
    assert "[Doc: CMR Operational Guidelines 2026, Chunk: Sec-2.1]" in inference_result.answer

    # 3. Retrieve AIRun from database and reconstruct answer
    stored_run = await session.get(AIRun, inference_result.ai_run_id)
    assert stored_run is not None
    assert stored_run.request_id == "req-test-trace-12345"
    assert stored_run.prompt_template_version == "v1.0.0"
    assert stored_run.query_text == question
    assert stored_run.answer_text == inference_result.answer
    assert stored_run.total_tokens > 0
    assert stored_run.latency_ms > 0
    assert len(stored_run.retrieved_chunks) >= 1
    assert stored_run.retrieved_chunks[0]["chunk_id_code"] == "Sec-2.1"

    # 4. Execute reconstruction helper
    reconstructed = AIInferenceService.reconstruct_answer_from_airun(stored_run)
    assert reconstructed["is_verified"] is True
    assert reconstructed["answer_text"] == stored_run.answer_text
    assert reconstructed["citations"] == stored_run.citations
    assert reconstructed["retrieved_chunks"] == stored_run.retrieved_chunks


@pytest.mark.asyncio
async def test_customer_api_ai_run_trace_endpoint(client: AsyncClient, async_db):
    """Verify that asking a question via the customer endpoint records an AIRun,
    returns the ai_run_id, and allows querying the trace endpoint GET /api/v1/customer/ai-runs/{id}.
    """
    session, _ = async_db

    # Seed active document
    doc = Document(title="CMR Standard Handbook")
    session.add(doc)
    await session.flush()
    ver = DocumentVersion(document_id=doc.id, version_number=1, status=DocumentVersionStatus.ACTIVE)
    session.add(ver)
    await session.flush()
    chunk = Chunk(
        version_id=ver.id,
        chunk_index=0,
        chunk_id_code="Sec-4.2",
        content="Turnaround time for standard vehicle clearance is 24 to 48 business hours.",
        embedding=generate_deterministic_mock_embedding("turnaround time vehicle clearance 24 48 hours"),
        token_count=14,
    )
    session.add(chunk)
    await session.commit()

    # 1. Ask informational question via API
    resp = await client.post(
        "/api/v1/customer/questions",
        json={
            "question": "What is the turnaround time for standard vehicle clearance?",
            "channel": "web",
        },
    )
    assert resp.status_code == 200
    data = resp.json()

    assert data["intent"] == "INFORMATIONAL"
    assert data["ai_run_id"] is not None
    ai_run_id = data["ai_run_id"]

    # 2. Query trace endpoint GET /api/v1/customer/ai-runs/{ai_run_id}
    trace_resp = await client.get(f"/api/v1/customer/ai-runs/{ai_run_id}")
    assert trace_resp.status_code == 200
    trace_data = trace_resp.json()

    assert trace_data["id"] == ai_run_id
    assert trace_data["intent"] == "INFORMATIONAL"
    assert trace_data["prompt_template_version"] == "v1.0.0"
    assert "clearance" in trace_data["query_text"].lower()
    assert trace_data["answer_text"] == data["answer"]
    assert trace_data["total_tokens"] > 0
    assert trace_data["latency_ms"] > 0
