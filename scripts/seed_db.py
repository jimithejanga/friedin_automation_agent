import asyncio
import hashlib
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.retrieval import generate_deterministic_mock_embedding
from app.cases.models import Case, CaseEvent, CasePriority, CaseStatus, Conversation, ExtractedFact, Message, MessageSenderType, Person
from app.knowledge.models import Chunk, Document, DocumentVersion, DocumentVersionStatus
from app.platform.audit import AuditLogger
from app.platform.auth import Role, hash_password
from app.platform.database import Base, get_engine, get_session_factory


DEFAULT_STAFF_ACCOUNTS = [
    {
        "full_name": "Chief Administrative Officer",
        "email": "admin@cmr.police.gov.ng",
        "phone_number": "+2348000000001",
        "role": Role.ADMIN,
        "password": "AdminSecurePassword2026!",
    },
    {
        "full_name": "Head of Operations Supervisor",
        "email": "supervisor@cmr.police.gov.ng",
        "phone_number": "+2348000000002",
        "role": Role.SUPERVISOR,
        "password": "SupervisorSecurePassword2026!",
    },
    {
        "full_name": "Support Desk Officer",
        "email": "support@cmr.police.gov.ng",
        "phone_number": "+2348000000003",
        "role": Role.SUPPORT,
        "password": "SupportSecurePassword2026!",
    },
    {
        "full_name": "Compliance & Audit Inspector",
        "email": "auditor@cmr.police.gov.ng",
        "phone_number": "+2348000000004",
        "role": Role.AUDITOR,
        "password": "AuditorSecurePassword2026!",
    },
]

PROCEDURAL_DOCUMENTS = [
    {
        "title": "CMR Operational Guidelines 2026",
        "description": "Comprehensive guidelines for motor vehicle clearance, registration verification, and statutory fee payment under the Central Motor Registry.",
        "category": "PROCEDURAL_GUIDE",
        "source_url": "https://cmr.police.gov.ng/guidelines/clearance",
        "chunks": [
            {
                "chunk_id_code": "Sec-1.4",
                "content": (
                    "Statutory fee payments for official Central Motor Registry (CMR) vehicle clearance and biometric capture "
                    "must be remitted strictly via authorized federal remita government payment gateways. Never pay cash to any individual "
                    "or intermediary. Official verification requires authenticated backend integration or human specialist sign-off."
                ),
            },
            {
                "chunk_id_code": "Sec-2.1",
                "content": (
                    "Motor vehicle clearance requires verified proof of vehicle ownership (Original Receipt, Custom Duty Papers for imported vehicles, "
                    "or Allocation of Plate Number), valid National Identification Number (NIN) of the registered owner, and digital chassis VIN inspection. "
                    "Standard digital clearance turnaround is 24 to 48 business hours."
                ),
            },
            {
                "chunk_id_code": "Sec-3.5",
                "content": (
                    "Change of vehicle ownership requires verified legal deed of sale signed by both seller and buyer, valid NIN biometric verification, "
                    "and previous motor licensing authority registration papers."
                ),
            },
        ],
    },
    {
        "title": "Nigeria Police CMR Standard Handbook",
        "description": "Standard operating guidelines, SLAs, and dispute procedures for vehicle owners and licensing authorities.",
        "category": "OFFICIAL_HANDBOOK",
        "source_url": "https://cmr.police.gov.ng/handbook",
        "chunks": [
            {
                "chunk_id_code": "Sec-4.2",
                "content": (
                    "Turnaround time for standard vehicle clearance is 24 to 48 hours upon biometric inspection. "
                    "Inter-state transfer clearances require 3 to 5 business days for cross-jurisdictional verification."
                ),
            },
            {
                "chunk_id_code": "Sec-5.1",
                "content": (
                    "When an application exceeds the 48-hour service level agreement (SLA) standard, the applicant may escalate "
                    "directly to the support desk to open an administrative review case."
                ),
            },
        ],
    },
    {
        "title": "CMR Fee Schedule & Remittance Circular",
        "description": "Official schedule of biometric capture and vehicle registry clearance fees.",
        "category": "REGULATORY_CIRCULAR",
        "source_url": "https://cmr.police.gov.ng/fees",
        "chunks": [
            {
                "chunk_id_code": "Sec-6.1",
                "content": (
                    "Standard motor vehicle registration and biometric capture fee is set by federal statutory regulations. "
                    "All payments produce a verified RRR tracking reference that must be attached to the clearance dossier."
                ),
            }
        ],
    },
]


async def seed_staff_accounts(session: AsyncSession) -> None:
    """Seed default admin, supervisor, support, and auditor user records."""
    for staff in DEFAULT_STAFF_ACCOUNTS:
        stmt = select(Person).where(Person.email == staff["email"])
        existing = (await session.execute(stmt)).scalar_one_or_none()
        if not existing:
            person = Person(
                full_name=staff["full_name"],
                email=staff["email"],
                phone_number=staff["phone_number"],
                contact_preferences={"email": True, "sms": True},
                metadata_json={
                    "role": staff["role"].value,
                    "password_hash": hash_password(staff["password"]),
                    "is_staff": True,
                },
            )
            session.add(person)
            await session.flush()
            await AuditLogger.record_async(
                session=session,
                action="STAFF_ACCOUNT_SEEDED",
                entity_type="person",
                entity_id=str(person.id),
                actor_role="system",
                details={"email": staff["email"], "role": staff["role"].value},
            )


async def seed_procedural_knowledge(session: AsyncSession) -> None:
    """Seed authoritative CMR procedural documents, active versions, and vector chunks."""
    for doc_data in PROCEDURAL_DOCUMENTS:
        stmt = select(Document).where(Document.title == doc_data["title"])
        existing_doc = (await session.execute(stmt)).scalar_one_or_none()

        if not existing_doc:
            doc = Document(
                title=doc_data["title"],
                description=doc_data["description"],
                category=doc_data["category"],
                source_url=doc_data["source_url"],
            )
            session.add(doc)
            await session.flush()

            # Create Version 1 as ACTIVE
            ver = DocumentVersion(
                document_id=doc.id,
                version_number=1,
                status=DocumentVersionStatus.ACTIVE,
                content_hash=hashlib.sha256(doc_data["title"].encode("utf-8")).hexdigest(),
                published_at=datetime.now(timezone.utc),
            )
            session.add(ver)
            await session.flush()

            for idx, chunk_data in enumerate(doc_data["chunks"]):
                embedding = generate_deterministic_mock_embedding(chunk_data["content"])
                chunk = Chunk(
                    version_id=ver.id,
                    chunk_index=idx,
                    chunk_id_code=chunk_data["chunk_id_code"],
                    content=chunk_data["content"],
                    embedding=embedding,
                    token_count=len(chunk_data["content"].split()) * 2,
                    metadata_json={"document_title": doc.title},
                )
                session.add(chunk)

            await session.flush()
            await AuditLogger.record_async(
                session=session,
                action="DOCUMENT_PUBLISHED",
                entity_type="document",
                entity_id=str(doc.id),
                actor_role="system",
                details={"title": doc.title, "version": 1, "status": "ACTIVE"},
            )


async def seed_sample_cases(session: AsyncSession) -> None:
    """Seed realistic customer cases across multiple lifecycle stages."""
    sample_customers = [
        {
            "full_name": "Emeka Chukwu",
            "phone_number": "+2348023456789",
            "email": "emeka.chukwu@example.com",
            "case_number": "CMR-2026-08912",
            "category": "CLEARANCE_FAILURE",
            "subject": "Vehicle Clearance Verification Delay in Lagos",
            "description": "Submitted clearance papers 48 hours ago for Toyota Corolla chassis 1HGCR2F83HA123456.",
            "status": CaseStatus.IN_REVIEW,
            "priority": CasePriority.HIGH,
            "facts": [
                {"key": "vin_or_chassis", "value": "1HGCR2F83HA123456"},
                {"key": "registration_state", "value": "Lagos"},
            ],
        },
        {
            "full_name": "Amina Bello",
            "phone_number": "+2348034567890",
            "email": "amina.bello@example.com",
            "case_number": "CMR-2026-08913",
            "category": "STOLEN_VEHICLE_REPORT",
            "subject": "Urgent: Stolen Honda Accord in Abuja",
            "description": "Vehicle stolen from parking lot. Plate KJA123AA, VIN 2HGBH41JX1H123456.",
            "status": CaseStatus.NEW,
            "priority": CasePriority.URGENT,
            "facts": [
                {"key": "vin_or_chassis", "value": "2HGBH41JX1H123456"},
                {"key": "license_plate", "value": "KJA123AA"},
                {"key": "registration_state", "value": "Abuja"},
            ],
        },
        {
            "full_name": "Tunde Bakare",
            "phone_number": "+2348045678901",
            "email": "tunde.bakare@example.com",
            "case_number": "CMR-2026-08914",
            "category": "GENERAL_INQUIRY",
            "subject": "Change of Vehicle Ownership Clarification",
            "description": "Purchased vehicle from previous owner, need transfer verification.",
            "status": CaseStatus.RESOLVED,
            "priority": CasePriority.NORMAL,
            "resolved_at": datetime.now(timezone.utc),
            "facts": [
                {"key": "registration_state", "value": "Oyo"},
            ],
        },
    ]

    for data in sample_customers:
        stmt = select(Case).where(Case.case_number == data["case_number"])
        existing_case = (await session.execute(stmt)).scalar_one_or_none()

        if not existing_case:
            person = Person(
                full_name=data["full_name"],
                phone_number=data["phone_number"],
                email=data["email"],
            )
            session.add(person)
            await session.flush()

            case = Case(
                case_number=data["case_number"],
                person_id=person.id,
                status=data["status"],
                priority=data["priority"],
                category=data["category"],
                subject=data["subject"],
                description=data["description"],
                resolved_at=data.get("resolved_at"),
            )
            session.add(case)
            await session.flush()

            # Record initial CaseEvent
            event = CaseEvent(
                case_id=case.id,
                event_type="CASE_CREATED",
                to_status=case.status.value,
                actor_role="customer",
                actor_id=person.id,
                reason="Customer opened support case",
                payload={"case_number": case.case_number},
            )
            session.add(event)

            # Record conversation and message
            conv = Conversation(person_id=person.id, case_id=case.id, channel="web")
            session.add(conv)
            await session.flush()

            msg = Message(
                conversation_id=conv.id,
                sender_type=MessageSenderType.CUSTOMER,
                sender_id=person.id,
                content=data["description"],
            )
            session.add(msg)
            await session.flush()

            # Record extracted facts
            for fact_item in data["facts"]:
                fact = ExtractedFact(
                    case_id=case.id,
                    conversation_id=conv.id,
                    message_id=msg.id,
                    fact_key=fact_item["key"],
                    fact_value=fact_item["value"],
                    confidence=0.95,
                    source="AI_EXTRACTION",
                    verified=True,
                )
                session.add(fact)

            await session.flush()
            await AuditLogger.record_async(
                session=session,
                action="CASE_CREATED",
                entity_type="case",
                entity_id=str(case.id),
                actor_id=person.id,
                actor_role="customer",
                details={"case_number": case.case_number, "status": case.status.value},
            )


import argparse
import os
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


async def seed_database(db_url: Optional[str] = None, session_factory=None) -> None:
    """Main database seeder entrypoint."""
    engine = None
    dispose_engine = False

    if session_factory is None:
        if db_url is None:
            env_url = os.environ.get("DATABASE_URL")
            # If DATABASE_URL is not set or points to default unreachable postgres, fallback to sqlite
            if not env_url:
                db_url = "sqlite+aiosqlite:///cmr_seed.db"
            else:
                db_url = env_url

        connect_args = {}
        if "sqlite" in db_url:
            connect_args["check_same_thread"] = False

        engine = create_async_engine(db_url, connect_args=connect_args, echo=False)
        dispose_engine = True
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(
            bind=engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
            autocommit=False,
        )

    async with session_factory() as session:
        try:
            print("[SEEDER] Starting database seeding...")
            await seed_staff_accounts(session)
            print("[SEEDER] Staff & admin accounts seeded.")
            await seed_procedural_knowledge(session)
            print("[SEEDER] Authoritative procedural documents & chunks seeded.")
            await seed_sample_cases(session)
            print("[SEEDER] Sample cases, conversations, and facts seeded.")
            await session.commit()
            print("[SEEDER] Database seeding successfully completed.")
        except Exception as exc:
            await session.rollback()
            print(f"[SEEDER] Database seeding failed: {exc}")
            raise
        finally:
            if dispose_engine and engine is not None:
                await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed CMR database with staff, documents, and cases.")
    parser.add_argument("--db", type=str, default=None, help="Database connection URL")
    args = parser.parse_args()
    asyncio.run(seed_database(db_url=args.db))
