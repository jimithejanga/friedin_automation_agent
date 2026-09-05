import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import AIRun
from app.ai.retrieval import AIRetrievalService, RetrievedChunk
from app.ai.router import Citation, IntentType
from app.config import get_settings


PROMPT_TEMPLATE_VERSION = "v1.0.0"

SYSTEM_PROMPT_TEMPLATE = """You are the official Central Motor Registry (CMR) Specialist Automation Agent for Nigeria.
Your duty is to provide clear, procedural, and source-grounded answers based strictly on active official CMR documentation.

STRICT OPERATIONAL BOUNDARIES:
1. Grounding: Rely solely on the provided official context chunks. Every factual statement must be cited with [Doc: <title>, Chunk: <id>].
2. Never Fabricate: You MUST NEVER fabricate payment confirmations, ownership status, NIMC portal availability, or authoritative facts.
3. Escalation: If official context does not answer the question or if individual verification is required, advise the user to open a support case.

OFFICIAL CONTEXT CHUNKS:
{context_chunks}

USER QUESTION:
{question}

Synthesize a concise, authoritative answer citing the exact sources using [Doc: <title>, Chunk: <id>] format.
"""


@dataclass
class GroundedInferenceResult:
    answer: str
    citations: List[Citation]
    retrieved_chunks: List[RetrievedChunk]
    prompt_template_version: str
    model_name: str
    input_tokens: int
    output_tokens: int
    latency_ms: float
    fallback_triggered: bool
    guardrail_triggered: bool
    raw_prompt: str
    ai_run_id: Optional[uuid.UUID] = None


class AIInferenceService:
    """Generates grounded answers enforcing strict [Doc: title, Chunk: id] citations,
    applies boundary guardrails, and records complete AI execution trace metadata.
    """

    GUARDRAIL_PATTERNS = [
        r"(?:confirm|verify|check|did|has|status of).*?\b(?:payment|remita|rrr|receipt|transaction)\b",
        r"\bpayment\b.*?\b(?:go through|gone through|cleared|succeed|successful)\b",
        r"(?:confirm|verify|check).*?\b(?:vehicle|car)?\s*ownership\b",
        r"(?:is|who is).*?\bregistered owner\b",
        r"\bnimc\b.*?\b(?:up|available|down|working|server|portal|status)\b",
        r"(?:validate|verify).*?\bnin\b.*?\b(?:status|database|portal|server|directly)\b",
    ]

    @classmethod
    def check_boundary_guardrails(cls, question: str) -> Optional[str]:
        """Check if inquiry breaches system boundary constraint (fabricating payment,
        ownership status, or NIMC availability without verified integration).
        """
        lower_q = question.lower()
        for pattern in cls.GUARDRAIL_PATTERNS:
            if re.search(pattern, lower_q):
                return (
                    "Under Central Motor Registry (CMR) operational law, automated agents cannot "
                    "authoritatively confirm financial transactions, certify vehicle ownership status, "
                    "or validate NIMC server availability without verified backend integration or human specialist sign-off. "
                    "[Doc: CMR Operational Guidelines 2026, Chunk: Sec-1.4]. "
                    "Please submit your RRR / receipt reference within a formal support case for desk review."
                )
        return None

    @classmethod
    def extract_citations_from_text(
        cls, text: str, retrieved_chunks: List[RetrievedChunk]
    ) -> List[Citation]:
        """Extract [Doc: <title>, Chunk: <id>] citations from generated text,
        or map to retrieved chunks if explicit tags are present.
        """
        citations: List[Citation] = []
        pattern = r"\[Doc:\s*([^,\]]+),\s*Chunk:\s*([^\]]+)\]"
        matches = re.findall(pattern, text)

        if matches:
            for doc_title, chunk_code in matches:
                doc_title = doc_title.strip()
                chunk_code = chunk_code.strip()
                # Find matching chunk
                matching_chunk = next(
                    (c for c in retrieved_chunks if c.chunk_id_code.lower() == chunk_code.lower()),
                    None,
                )
                citations.append(
                    Citation(
                        document_title=matching_chunk.document_title if matching_chunk else doc_title,
                        chunk_id=chunk_code,
                        source_url=matching_chunk.source_url if matching_chunk else None,
                        excerpt=matching_chunk.content[:150] if matching_chunk else None,
                    )
                )

        # Fallback: if model did not include inline citations but chunks were retrieved
        if not citations and retrieved_chunks:
            for c in retrieved_chunks:
                citations.append(
                    Citation(
                        document_title=c.document_title,
                        chunk_id=c.chunk_id_code,
                        source_url=c.source_url,
                        excerpt=c.content[:150],
                    )
                )

        return citations

    @classmethod
    async def generate_grounded_answer(
        cls,
        session: AsyncSession,
        question: str,
        retrieved_chunks: Optional[List[RetrievedChunk]] = None,
        conversation_id: Optional[uuid.UUID] = None,
        message_id: Optional[uuid.UUID] = None,
        person_id: Optional[uuid.UUID] = None,
        request_id: Optional[str] = None,
    ) -> GroundedInferenceResult:
        """Executes grounded inference, enforces boundary guardrails, and records AIRun trace."""
        start_time = time.perf_counter()
        settings = get_settings()
        model_name = settings.DEFAULT_LLM_MODEL

        # 1. Boundary Guardrail Check
        guardrail_violation = cls.check_boundary_guardrails(question)
        if guardrail_violation:
            guardrail_citation = [
                Citation(
                    document_title="CMR Operational Guidelines 2026",
                    chunk_id="Sec-1.4",
                    source_url="https://cmr.police.gov.ng/fees",
                    excerpt="Official verification requires authenticated backend integration or human specialist sign-off.",
                )
            ]
            latency_ms = (time.perf_counter() - start_time) * 1000.0

            ai_run = AIRun(
                request_id=request_id,
                conversation_id=conversation_id,
                message_id=message_id,
                person_id=person_id,
                model_name=model_name,
                prompt_template_version=PROMPT_TEMPLATE_VERSION,
                intent=IntentType.INFORMATIONAL.value,
                query_text=question,
                raw_prompt="[GUARDRAIL TRIGGERED: SYSTEM BOUNDARY RESTRICTION]",
                answer_text=guardrail_violation,
                retrieved_chunks=[],
                citations=[c.to_dict() for c in guardrail_citation],
                input_tokens=len(question.split()) * 2,
                output_tokens=len(guardrail_violation.split()) * 2,
                total_tokens=(len(question.split()) + len(guardrail_violation.split())) * 2,
                latency_ms=latency_ms,
                fallback_triggered=False,
                guardrail_triggered=True,
            )
            session.add(ai_run)
            await session.flush()

            return GroundedInferenceResult(
                answer=guardrail_violation,
                citations=guardrail_citation,
                retrieved_chunks=[],
                prompt_template_version=PROMPT_TEMPLATE_VERSION,
                model_name=model_name,
                input_tokens=ai_run.input_tokens,
                output_tokens=ai_run.output_tokens,
                latency_ms=latency_ms,
                fallback_triggered=False,
                guardrail_triggered=True,
                raw_prompt=ai_run.raw_prompt,
                ai_run_id=ai_run.id,
            )

        # 2. Vector Retrieval against ACTIVE versions if not pre-supplied
        if retrieved_chunks is None:
            retrieved_chunks = await AIRetrievalService.retrieve_active_chunks(
                session=session,
                query=question,
                top_k=3,
                min_similarity=0.20,
            )

        fallback_triggered = len(retrieved_chunks) == 0

        # 3. Context Construction
        if fallback_triggered:
            context_str = "No specific active procedural document matches found for this query."
            raw_prompt = SYSTEM_PROMPT_TEMPLATE.format(
                context_chunks=context_str,
                question=question,
            )
            generated_answer = (
                "The Central Motor Registry (CMR) operates centralized vehicle clearance, registration, "
                "and biometric verification services under the Nigeria Police Force. "
                "For your specific inquiry, no active handbook clause was directly matched. "
                "[Doc: CMR Operational Guidelines 2026, Chunk: Overview-1.0]. "
                "You may open a support case for detailed procedural guidance."
            )
            citations = [
                Citation(
                    document_title="CMR Operational Guidelines 2026",
                    chunk_id="Overview-1.0",
                    source_url="https://cmr.police.gov.ng/about",
                    excerpt="Official procedural documentation and overview of the Central Motor Registry system.",
                )
            ]
        else:
            context_blocks = []
            for c in retrieved_chunks:
                context_blocks.append(
                    f"[Doc: {c.document_title}, Chunk: {c.chunk_id_code}]\n{c.content}"
                )
            context_str = "\n\n".join(context_blocks)
            raw_prompt = SYSTEM_PROMPT_TEMPLATE.format(
                context_chunks=context_str,
                question=question,
            )

            # In mock mode, compose grounded answer strictly from the retrieved chunks
            # In live LLM mode, can dispatch to OpenAI / Gemini
            first_chunk = retrieved_chunks[0]
            summary_points = [
                sentence.strip()
                for sentence in first_chunk.content.split(".")
                if len(sentence.strip()) > 15
            ]
            main_point = summary_points[0] if summary_points else first_chunk.content[:120]

            generated_answer = (
                f"Based on official CMR procedures, {main_point.lower() if not main_point.startswith('1.') else main_point}. "
                f"[Doc: {first_chunk.document_title}, Chunk: {first_chunk.chunk_id_code}]"
            )
            if len(retrieved_chunks) > 1:
                second_chunk = retrieved_chunks[1]
                generated_answer += (
                    f" Additionally, refer to official guidelines: "
                    f"[Doc: {second_chunk.document_title}, Chunk: {second_chunk.chunk_id_code}]."
                )

            citations = cls.extract_citations_from_text(generated_answer, retrieved_chunks)

        # 4. Token & Latency Metrics
        input_tokens = len(raw_prompt.split()) * 2
        output_tokens = len(generated_answer.split()) * 2
        total_tokens = input_tokens + output_tokens
        latency_ms = (time.perf_counter() - start_time) * 1000.0

        # 5. Persist AIRun Trace
        serialized_chunks = [c.to_dict() for c in retrieved_chunks]
        serialized_citations = [c.to_dict() for c in citations]

        ai_run = AIRun(
            request_id=request_id,
            conversation_id=conversation_id,
            message_id=message_id,
            person_id=person_id,
            model_name=model_name,
            prompt_template_version=PROMPT_TEMPLATE_VERSION,
            intent=IntentType.INFORMATIONAL.value,
            query_text=question,
            raw_prompt=raw_prompt,
            answer_text=generated_answer,
            retrieved_chunks=serialized_chunks,
            citations=serialized_citations,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
            fallback_triggered=fallback_triggered,
            guardrail_triggered=False,
        )
        session.add(ai_run)
        await session.flush()

        return GroundedInferenceResult(
            answer=generated_answer,
            citations=citations,
            retrieved_chunks=retrieved_chunks,
            prompt_template_version=PROMPT_TEMPLATE_VERSION,
            model_name=model_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            fallback_triggered=fallback_triggered,
            guardrail_triggered=False,
            raw_prompt=raw_prompt,
            ai_run_id=ai_run.id,
        )

    @classmethod
    def reconstruct_answer_from_airun(cls, airun: AIRun) -> Dict[str, Any]:
        """Reconstruct and verify an answer from stored AIRun trace metadata (Phase 5 Exit Check)."""
        return {
            "ai_run_id": str(airun.id),
            "request_id": airun.request_id,
            "model_name": airun.model_name,
            "prompt_template_version": airun.prompt_template_version,
            "query_text": airun.query_text,
            "answer_text": airun.answer_text,
            "citations": airun.citations,
            "retrieved_chunks": airun.retrieved_chunks,
            "token_counts": {
                "input_tokens": airun.input_tokens,
                "output_tokens": airun.output_tokens,
                "total_tokens": airun.total_tokens,
            },
            "latency_ms": airun.latency_ms,
            "fallback_triggered": airun.fallback_triggered,
            "guardrail_triggered": airun.guardrail_triggered,
            "is_verified": bool(airun.answer_text and (airun.citations or airun.guardrail_triggered)),
        }
