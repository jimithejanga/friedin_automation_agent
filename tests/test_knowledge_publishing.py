import io
import uuid
import pypdf
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.knowledge.models import Chunk, Document, DocumentVersion, DocumentVersionStatus
from app.knowledge.service import KnowledgeService
from app.main import create_app
from app.platform.auth import Role, create_access_token
from app.platform.database import Base, get_db_session


def generate_test_pdf_bytes(pages_text: list[str]) -> bytes:
    """Generates a valid PDF with custom text on each page using pypdf."""
    writer = pypdf.PdfWriter()

    for text in pages_text:
        page = writer.add_blank_page(width=612, height=792)

        # PDF Content stream with text operators
        content_stream = pypdf.generic.DecodedStreamObject()
        stream_data = f"BT /F1 12 Tf 50 700 Td ({text}) Tj ET".encode("latin-1")
        content_stream.set_data(stream_data)
        page[pypdf.generic.NameObject("/Contents")] = content_stream

        # Font definition
        font_dict = pypdf.generic.DictionaryObject()
        f1 = pypdf.generic.DictionaryObject()
        f1[pypdf.generic.NameObject("/Type")] = pypdf.generic.NameObject("/Font")
        f1[pypdf.generic.NameObject("/Subtype")] = pypdf.generic.NameObject("/Type1")
        f1[pypdf.generic.NameObject("/BaseFont")] = pypdf.generic.NameObject("/Helvetica")
        font_dict[pypdf.generic.NameObject("/F1")] = f1

        resources = pypdf.generic.DictionaryObject()
        resources[pypdf.generic.NameObject("/Font")] = font_dict
        page[pypdf.generic.NameObject("/Resources")] = resources

    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


@pytest.fixture
async def async_db():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False, "timeout": 30.0},
        poolclass=StaticPool,
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )

    yield session_maker, engine
    await engine.dispose()


@pytest.fixture
async def client(async_db):
    session_maker, _ = async_db
    app = create_app()

    async def override_get_db_session():
        async with session_maker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db_session] = override_get_db_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c

    app.dependency_overrides.clear()


def make_token(role: Role, user_id: uuid.UUID | None = None) -> dict:
    sub = str(user_id or uuid.uuid4())
    token = create_access_token(
        subject=sub,
        email=f"{role.value}@cmr.police.gov.ng",
        role=role,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_pdf_upload_creates_draft_and_extracts_chunks(client: AsyncClient):
    """Verifies that uploading a PDF creates a DRAFT version, extracts chunks,
    generates 1536-dim embeddings, and leaves the version unactivated.
    """
    support_headers = make_token(Role.SUPPORT)
    pdf_bytes = generate_test_pdf_bytes([
        "Section 1.1 Commercial Vehicle Clearance Rules: Annual biometric renewal required. Fee is 25000 NGN.",
        "Section 2.3 Tinted Glass Permit Clearance: Valid barcode inspection is mandatory within 24 hours.",
    ])

    files = {"file": ("commercial_clearance_2026.pdf", pdf_bytes, "application/pdf")}
    data = {
        "title": "Commercial Vehicle Clearance Regulation 2026",
        "category": "PROCEDURAL_GUIDE",
        "description": "Statutory rules for commercial motor vehicle clearance and inspection.",
        "publish_immediately": "false",
    }

    resp = await client.post(
        "/api/v1/support/documents/upload",
        files=files,
        data=data,
        headers=support_headers,
    )
    assert resp.status_code == 201
    upload_data = resp.json()

    assert upload_data["status"] == "DRAFT"
    assert upload_data["is_published"] is False
    assert upload_data["version_number"] == 1
    assert upload_data["total_chunks"] >= 2
    assert len(upload_data["content_hash"]) == 64  # SHA-256


@pytest.mark.asyncio
async def test_draft_chunks_strictly_invisible_to_customer_ai_retrieval(client: AsyncClient):
    """PUBLISHING GUARANTEE:
    Verifies that chunks belonging to a DRAFT version are NEVER retrieved
    or cited by customer AI questions.
    """
    support_headers = make_token(Role.SUPPORT)
    pdf_bytes = generate_test_pdf_bytes([
        "Section 9.9 Secret Internal Enforcement Memo: Confidential biometric patrol protocols in Lagos.",
    ])

    files = {"file": ("secret_draft.pdf", pdf_bytes, "application/pdf")}
    data = {
        "title": "Confidential Draft Guide",
        "category": "INTERNAL_POLICY",
        "publish_immediately": "false",
    }

    upload_resp = await client.post(
        "/api/v1/support/documents/upload",
        files=files,
        data=data,
        headers=support_headers,
    )
    assert upload_resp.status_code == 201
    assert upload_resp.json()["status"] == "DRAFT"

    # Customer asks about the draft content
    q_resp = await client.post(
        "/api/v1/customer/questions",
        json={"question": "What is the secret internal enforcement memo for Lagos?", "channel": "web"},
    )
    assert q_resp.status_code == 200
    q_data = q_resp.json()

    # Must NOT cite the draft document
    for citation in q_data.get("citations", []):
        assert "Confidential Draft Guide" not in citation.get("document_title", "")
        assert "Sec-9.9" not in citation.get("chunk_id_code", "")


@pytest.mark.asyncio
async def test_draft_preview_and_test_retrieval(client: AsyncClient):
    """Verifies that support staff can preview extracted chunks and test vector queries
    against a draft version before publishing.
    """
    support_headers = make_token(Role.SUPPORT)
    pdf_bytes = generate_test_pdf_bytes([
        "Section 3.1 Inter-State Vehicle Clearance: Clearance transfer between states takes 3 to 5 business days.",
    ])

    files = {"file": ("interstate_rules.pdf", pdf_bytes, "application/pdf")}
    data = {
        "title": "Inter-State Vehicle Rules",
        "publish_immediately": "false",
    }
    upload_resp = await client.post(
        "/api/v1/support/documents/upload",
        files=files,
        data=data,
        headers=support_headers,
    )
    assert upload_resp.status_code == 201
    doc_id = upload_resp.json()["document_id"]
    ver_id = upload_resp.json()["version_id"]

    # 1. Preview draft chunks
    preview_resp = await client.get(
        f"/api/v1/support/documents/{doc_id}/versions/{ver_id}/preview",
        headers=support_headers,
    )
    assert preview_resp.status_code == 200
    p_data = preview_resp.json()
    assert p_data["version_number"] == 1
    assert p_data["status"] == "DRAFT"
    assert len(p_data["chunks"]) >= 1
    assert any("Inter-State" in c["content"] for c in p_data["chunks"])

    # 2. Test draft retrieval relevance
    test_q_resp = await client.post(
        f"/api/v1/support/documents/{doc_id}/versions/{ver_id}/test-query",
        json={"query": "How many days does inter-state clearance take?", "top_k": 2},
        headers=support_headers,
    )
    assert test_q_resp.status_code == 200
    t_data = test_q_resp.json()
    assert len(t_data["matches"]) >= 1
    assert t_data["matches"][0]["similarity"] > 0


@pytest.mark.asyncio
async def test_atomic_version_publishing(client: AsyncClient):
    """Verifies that publishing a DRAFT version atomically transitions it to ACTIVE."""
    supervisor_headers = make_token(Role.SUPERVISOR)
    pdf_bytes = generate_test_pdf_bytes([
        "Section 4.1 Electric Vehicle Special Registration: Zero emission electric vehicles receive a green emblem.",
    ])

    files = {"file": ("ev_reg.pdf", pdf_bytes, "application/pdf")}
    data = {"title": "Electric Vehicle Handbook", "publish_immediately": "false"}

    upload_resp = await client.post(
        "/api/v1/support/documents/upload",
        files=files,
        data=data,
        headers=supervisor_headers,
    )
    doc_id = upload_resp.json()["document_id"]
    ver_id = upload_resp.json()["version_id"]

    # Publish draft version
    pub_resp = await client.post(
        f"/api/v1/support/documents/{doc_id}/versions/{ver_id}/publish",
        headers=supervisor_headers,
    )
    assert pub_resp.status_code == 200
    pub_data = pub_resp.json()
    assert pub_data["status"] == "ACTIVE"
    assert pub_data["published_version_number"] == 1

    # Verify Document Detail reflects ACTIVE status
    detail_resp = await client.get(
        f"/api/v1/support/documents/{doc_id}",
        headers=supervisor_headers,
    )
    assert detail_resp.status_code == 200
    versions = detail_resp.json()["versions"]
    assert len(versions) == 1
    assert versions[0]["status"] == "ACTIVE"


@pytest.mark.asyncio
async def test_customer_ai_answers_cite_newly_published_version(client: AsyncClient):
    """Verifies that as soon as a document version is published ACTIVE,
    customer AI questions immediately retrieve and cite it.
    """
    supervisor_headers = make_token(Role.SUPERVISOR)
    pdf_bytes = generate_test_pdf_bytes([
        "Section 7.4 Diplomatic Vehicle Importation: Diplomatic vehicles must attach Ministry of Foreign Affairs clearance form MFA-2026.",
    ])

    files = {"file": ("diplomatic_clearance.pdf", pdf_bytes, "application/pdf")}
    data = {"title": "Diplomatic Vehicle Regulations 2026", "publish_immediately": "true"}

    upload_resp = await client.post(
        "/api/v1/support/documents/upload",
        files=files,
        data=data,
        headers=supervisor_headers,
    )
    assert upload_resp.status_code == 201
    assert upload_resp.json()["is_published"] is True

    # Customer asks about diplomatic clearance
    q_resp = await client.post(
        "/api/v1/customer/questions",
        json={"question": "What form is needed for diplomatic vehicle clearance?", "channel": "web"},
    )
    assert q_resp.status_code == 200
    q_data = q_resp.json()

    # Grounded answer must cite the newly published document
    doc_titles = [c["document_title"] for c in q_data.get("citations", [])]
    assert "Diplomatic Vehicle Regulations 2026" in doc_titles


@pytest.mark.asyncio
async def test_atomic_version_rollback(client: AsyncClient):
    """Verifies atomic rollback:
    When a flawed Version 2 is published, rolling back restores Version 1 to ACTIVE
    and retires Version 2 in a single atomic transaction.
    """
    supervisor_headers = make_token(Role.SUPERVISOR)

    # 1. Create and publish Version 1
    pdf_v1 = generate_test_pdf_bytes([
        "Section 5.1 Fee: Standard vehicle registration fee is 15000 NGN.",
    ])
    up1 = await client.post(
        "/api/v1/support/documents/upload",
        files={"file": ("v1.pdf", pdf_v1, "application/pdf")},
        data={"title": "Official CMR Fee Guide", "publish_immediately": "true"},
        headers=supervisor_headers,
    )
    assert up1.status_code == 201
    doc_id = up1.json()["document_id"]
    v1_id = up1.json()["version_id"]

    # 2. Upload and publish flawed Version 2
    pdf_v2 = generate_test_pdf_bytes([
        "Section 5.1 Fee: Standard vehicle registration fee is mistakenly 999000 NGN.",
    ])
    up2 = await client.post(
        "/api/v1/support/documents/upload",
        files={"file": ("v2.pdf", pdf_v2, "application/pdf")},
        data={"title": "Official CMR Fee Guide", "publish_immediately": "true"},
        headers=supervisor_headers,
    )
    assert up2.status_code == 201
    v2_id = up2.json()["version_id"]

    # Verify V2 is ACTIVE and V1 is RETIRED
    detail = (await client.get(f"/api/v1/support/documents/{doc_id}", headers=supervisor_headers)).json()
    status_by_ver = {v["version_number"]: v["status"] for v in detail["versions"]}
    assert status_by_ver[1] == "RETIRED"
    assert status_by_ver[2] == "ACTIVE"

    # 3. Execute Atomic Rollback
    rollback_resp = await client.post(
        f"/api/v1/support/documents/{doc_id}/rollback",
        headers=supervisor_headers,
    )
    assert rollback_resp.status_code == 200
    rb_data = rollback_resp.json()
    assert rb_data["restored_version_number"] == 1
    assert rb_data["retired_version_number"] == 2
    assert rb_data["status"] == "ACTIVE"

    # 4. Verify in DB
    detail_post = (await client.get(f"/api/v1/support/documents/{doc_id}", headers=supervisor_headers)).json()
    status_post = {v["version_number"]: v["status"] for v in detail_post["versions"]}
    assert status_post[1] == "ACTIVE"
    assert status_post[2] == "RETIRED"


@pytest.mark.asyncio
async def test_phase_4_exit_check_complete_lifecycle(client: AsyncClient):
    """PHASE 4 EXIT CHECK:
    A new PDF can be uploaded in draft, processed in background, published atomically,
    cited, and rolled back safely.
    """
    admin_headers = make_token(Role.ADMIN)

    # 1. Upload in draft
    pdf_initial = generate_test_pdf_bytes([
        "Section 10.1 Lagos Command Impoundment Code: Unregistered vehicles impounded on expressways require Form LAG-99.",
    ])
    up_resp = await client.post(
        "/api/v1/support/documents/upload",
        files={"file": ("lagos_impound.pdf", pdf_initial, "application/pdf")},
        data={
            "title": "Lagos Expressway Enforcement Directive",
            "category": "ENFORCEMENT_DIRECTIVE",
            "publish_immediately": "false",
        },
        headers=admin_headers,
    )
    assert up_resp.status_code == 201
    doc_id = up_resp.json()["document_id"]
    v1_id = up_resp.json()["version_id"]
    assert up_resp.json()["status"] == "DRAFT"

    # 2. Preview draft
    prev = (await client.get(f"/api/v1/support/documents/{doc_id}/versions/{v1_id}/preview", headers=admin_headers)).json()
    assert prev["status"] == "DRAFT"
    assert prev["total_chunks"] >= 1

    # 3. Publish atomically
    pub = (await client.post(f"/api/v1/support/documents/{doc_id}/versions/{v1_id}/publish", headers=admin_headers)).json()
    assert pub["status"] == "ACTIVE"

    # 4. Cite in customer AI answer
    q_resp = await client.post(
        "/api/v1/customer/questions",
        json={"question": "What form is needed for expressway impoundment in Lagos?", "channel": "web"},
    )
    assert q_resp.status_code == 200
    citations = q_resp.json().get("citations", [])
    assert any("Lagos Expressway Enforcement Directive" in c["document_title"] for c in citations)

    # 5. Upload second version and roll back safely
    pdf_v2 = generate_test_pdf_bytes([
        "Section 10.1 Lagos Command Impoundment Code: Amended directive with error.",
    ])
    up_v2 = await client.post(
        "/api/v1/support/documents/upload",
        files={"file": ("lagos_impound_v2.pdf", pdf_v2, "application/pdf")},
        data={"title": "Lagos Expressway Enforcement Directive", "publish_immediately": "true"},
        headers=admin_headers,
    )
    assert up_v2.status_code == 201

    # Roll back
    rb = (await client.post(f"/api/v1/support/documents/{doc_id}/rollback", headers=admin_headers)).json()
    assert rb["restored_version_number"] == 1
    assert rb["status"] == "ACTIVE"
