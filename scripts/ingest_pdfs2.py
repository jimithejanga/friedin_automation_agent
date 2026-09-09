import asyncio
import os
from pathlib import Path
import structlog
from sqlalchemy import select

from app.knowledge.models import Chunk, Document, DocumentVersion
from app.knowledge.service import KnowledgeService
from app.platform.database import get_session_factory
from worker.tasks.ingestion import PDFIngestionPipeline

logger = structlog.get_logger("cmr.scripts.ingest_pdfs2")

DOCUMENTS_CONFIG = [
    {
        "file_path": "pdfs 2/knowledge/SOP For Digitalized Central Motor Registry Operations - 080524.pdf",
        "title": "NPF SOP for Digitalized Central Motor Registry Operations (2024)",
        "category": "STANDARD_OPERATING_PROCEDURE",
        "description": "Standard Operating Procedure (SOP) manual NPF/CMRIS/SOP/2024/V1.0 for digitalized CMR operations.",
        "source_url": "https://cmris.npf.gov.ng/sop",
    },
    {
        "file_path": "pdfs 2/procedures/Copy of CMRIS Email & Phone Support Scripts_Prompts.pdf",
        "title": "NPF CMRIS Support Interaction Scripts and Prompts (2024)",
        "category": "SUPPORT_SCRIPTS",
        "description": "Official call center and email support interaction scripts and prompts for NPF CMRIS operations.",
        "source_url": "https://cmris.npf.gov.ng/support",
    },
    {
        "file_path": "pdfs 2/knowledge/Step-By-Step - Process Flow for Change of Ownership (1).pdf",
        "title": "CMRIS Step-By-Step Guide for Change of Ownership",
        "category": "PROCEDURAL_GUIDE",
        "description": "Step-by-step citizen application guide to apply for motor vehicle change of ownership on CMRIS.",
        "source_url": "https://cmris.npf.gov.ng/procedures/change-of-ownership",
    },
    {
        "file_path": "pdfs 2/knowledge/Steps to Renew CMR Certificate.pdf",
        "title": "CMRIS Steps to Renew CMR Certificate",
        "category": "PROCEDURAL_GUIDE",
        "description": "Citizen guide for identifying and renewing expired Central Motor Registry certificates online.",
        "source_url": "https://cmris.npf.gov.ng/procedures/renew-certificate",
    },
    {
        "file_path": "pdfs 2/knowledge/New Steps to Request for CMR Motor Vehicle Information.pdf",
        "title": "CMRIS Steps to Request Motor Vehicle Information",
        "category": "PROCEDURAL_GUIDE",
        "description": "Official instructions to request for CMR motor vehicle information report on CMRIS.",
        "source_url": "https://cmris.npf.gov.ng/procedures/vehicle-information",
    },
]


async def main():
    factory = get_session_factory()
    print("==========================================================")
    print("🚀 Starting Ingestion of Official NPF CMRIS Documents (pdfs 2)")
    print("==========================================================")

    async with factory() as session:
        for item in DOCUMENTS_CONFIG:
            pdf_path = Path(item["file_path"])
            if not pdf_path.exists():
                print(f"❌ File not found: {pdf_path}")
                continue

            print(f"\n📄 Ingesting: {item['title']}")
            print(f"   Source: {pdf_path}")

            # 1. Create or fetch Document
            doc = await KnowledgeService.create_document(
                session=session,
                title=item["title"],
                category=item["category"],
                description=item["description"],
                source_url=item["source_url"],
                actor_role="system",
            )

            # 2. Create Draft Version
            draft_version = await KnowledgeService.create_draft_version(
                session=session,
                document_id=doc.id,
                file_path=str(pdf_path),
            )

            # 3. Parse PDF, Chunk Text, Generate Embeddings, and Persist
            await PDFIngestionPipeline.process_and_persist_version(
                session=session,
                version_id=draft_version.id,
                file_source=pdf_path,
            )

            # 4. Atomically Publish Draft to ACTIVE
            published_doc, active_ver, retired_ver = await KnowledgeService.publish_version(
                session=session,
                document_id=doc.id,
                version_id=draft_version.id,
                actor_role="supervisor",
            )

            # 5. Fetch Chunk Statistics
            chunk_count_stmt = select(Chunk).where(Chunk.version_id == active_ver.id)
            chunks = (await session.execute(chunk_count_stmt)).scalars().all()
            total_tokens = sum(c.token_count for c in chunks)

            print(f"   ✅ Published Version {active_ver.version_number} as ACTIVE")
            print(f"   📊 Chunks Created: {len(chunks)} | Total Tokens: {total_tokens}")
            if retired_ver:
                print(f"   🔄 Retired Previous Version {retired_ver.version_number}")

        await session.commit()

    print("\n==========================================================")
    print("🎉 All 5 Documents Ingested, Chunked, and Published to Knowledge Base!")
    print("==========================================================")


if __name__ == "__main__":
    asyncio.run(main())
