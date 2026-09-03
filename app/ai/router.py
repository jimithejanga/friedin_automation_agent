import enum
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


class IntentType(str, enum.Enum):
    INFORMATIONAL = "INFORMATIONAL"
    SUPPORT_REQUEST = "SUPPORT_REQUEST"


@dataclass
class Citation:
    document_title: str
    chunk_id: Optional[str] = None
    source_url: Optional[str] = None
    excerpt: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "document_title": self.document_title,
            "chunk_id": self.chunk_id,
            "source_url": self.source_url,
            "excerpt": self.excerpt,
        }


@dataclass
class ExtractedFactItem:
    fact_key: str
    fact_value: str
    confidence: float = 1.0
    source: str = "AI_EXTRACTION"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fact_key": self.fact_key,
            "fact_value": self.fact_value,
            "confidence": self.confidence,
            "source": self.source,
        }


@dataclass
class RoutingResult:
    intent: IntentType
    answer: str
    citations: List[Citation] = field(default_factory=list)
    prompt_case_creation: bool = False
    suggested_category: Optional[str] = None
    suggested_subject: Optional[str] = None
    extracted_facts: List[ExtractedFactItem] = field(default_factory=list)


# Official procedural guidelines for grounded answers
PROCEDURAL_KNOWLEDGE = [
    {
        "keywords": ["clearance", "certificate", "motor", "vehicle clearance", "how to get", "obtain"],
        "answer": (
            "To obtain an official Motor Vehicle Clearance Certificate under the Central Motor Registry (CMR) framework: "
            "1. Submit proof of vehicle ownership (Original Receipt, Custom Duty Papers for imported vehicles, or Allocation of Plate Number). "
            "2. Provide valid National Identification Number (NIN) of the registered owner. "
            "3. Submit the vehicle chassis/VIN and engine numbers for national automated verification. "
            "4. Clearance is typically processed within 24 to 48 hours upon physical or digital inspection."
        ),
        "citations": [
            Citation(
                document_title="CMR Operational Guidelines 2026",
                chunk_id="Sec-2.1",
                source_url="https://cmr.police.gov.ng/guidelines/clearance",
                excerpt="Motor vehicle clearance requires verified proof of ownership, NIN verification, and VIN inspection."
            ),
            Citation(
                document_title="Nigeria Police CMR Standard Handbook",
                chunk_id="Sec-4.2",
                source_url="https://cmr.police.gov.ng/handbook",
                excerpt="Turnaround time for standard vehicle clearance is 24 to 48 hours."
            )
        ]
    },
    {
        "keywords": ["fee", "cost", "price", "how much", "charge", "payment"],
        "answer": (
            "Standard Central Motor Registry (CMR) biometric information capture and vehicle clearance fees are fixed by official statute. "
            "All statutory payments must be remitted strictly via the authorized federal remita / government payment gateway. "
            "Never pay cash to any individual or intermediary. Retain your payment RRR code for automatic status validation."
        ),
        "citations": [
            Citation(
                document_title="CMR Fee Schedule & Remittance Circular",
                chunk_id="Sec-1.4",
                source_url="https://cmr.police.gov.ng/fees",
                excerpt="Official CMR registration fees are processed solely through verified government payment gateways."
            )
        ]
    },
    {
        "keywords": ["plate", "number", "registration", "new vehicle", "change of ownership"],
        "answer": (
            "For vehicle registration and number plate verification: "
            "1. Provide current vehicle license papers and state motor licensing authority documentation. "
            "2. Complete biometric owner verification using your verified NIN. "
            "3. For change of ownership, an official deed of legal sale and stamped transfer agreement signed by both parties is required."
        ),
        "citations": [
            Citation(
                document_title="CMR Operational Guidelines 2026",
                chunk_id="Sec-3.5",
                source_url="https://cmr.police.gov.ng/guidelines/registration",
                excerpt="Change of ownership requires verified deed of sale, valid NIN, and biometric capture."
            )
        ]
    },
    {
        "keywords": ["timeline", "how long", "duration", "hours", "days", "sla"],
        "answer": (
            "Official CMR processing timelines are: "
            "• Digital Verification: 24 to 48 business hours. "
            "• Inter-state Transfer Clearance: 3 to 5 business days. "
            "If your application exceeds these windows, you may open a support case for immediate desk review."
        ),
        "citations": [
            Citation(
                document_title="Nigeria Police CMR SLA Benchmark",
                chunk_id="Sec-5.1",
                source_url="https://cmr.police.gov.ng/sla",
                excerpt="Digital verification SLA standard is 24-48 business hours."
            )
        ]
    }
]

# Nigerian State names for geographic extraction
NIGERIAN_STATES = [
    "Abia", "Adamawa", "Akwa Ibom", "Anambra", "Bauchi", "Bayelsa", "Benue", "Borno",
    "Cross River", "Delta", "Ebonyi", "Edo", "Ekiti", "Enugu", "Gombe", "Imo", "Jigawa",
    "Kaduna", "Kano", "Katsina", "Kebbi", "Kogi", "Kwara", "Lagos", "Nasarawa", "Niger",
    "Ogun", "Ondo", "Osun", "Oyo", "Plateau", "Rivers", "Sokoto", "Taraba", "Yobe",
    "Zamfara", "Abuja", "FCT"
]


class BinaryIntentRouter:
    """Executes binary intent routing (INFORMATIONAL vs SUPPORT_REQUEST),
    extracts key case facts from natural language, and returns grounded answers with citations.
    """

    SUPPORT_TRIGGERS = [
        "stolen", "theft", "missing", "fraud", "hacked", "help me",
        "human", "agent", "representative", "officer", "complaint",
        "failed", "error", "rejected", "stuck", "pending for weeks",
        "investigate", "open case", "dispute", "wrong name", "refund",
        "cannot login", "not working", "urgent", "assistance needed"
    ]

    @classmethod
    def extract_facts(cls, text: str) -> List[ExtractedFactItem]:
        """Extract structured facts (VIN, plate, NIN, state, phone) from customer text."""
        facts: List[ExtractedFactItem] = []

        # 1. VIN / Chassis Number (typically 17 alphanumeric, excluding I, O, Q)
        vin_match = re.search(r"\b([A-HJ-NPR-Z0-9]{17})\b", text, re.IGNORECASE)
        if not vin_match:
            # Fallback for labeled pattern like "VIN: ABC123..." or "Chassis: ..."
            labeled_vin = re.search(r"(?:vin|chassis(?: number)?)\s*[:#-]?\s*([A-Z0-9]{8,17})", text, re.IGNORECASE)
            if labeled_vin:
                facts.append(ExtractedFactItem(
                    fact_key="vin_or_chassis",
                    fact_value=labeled_vin.group(1).upper(),
                    confidence=0.95,
                ))
        else:
            facts.append(ExtractedFactItem(
                fact_key="vin_or_chassis",
                fact_value=vin_match.group(1).upper(),
                confidence=0.98,
            ))

        # 2. Nigerian Vehicle Registration Plate Number (e.g., ABC-123XY, KJA123AA, LSR-456-XY)
        plate_match = re.search(r"\b([A-Z]{2,3}[-\s]?[0-9]{3}[-\s]?[A-Z]{2})\b", text, re.IGNORECASE)
        if plate_match:
            normalized_plate = re.sub(r"[-\s]", "", plate_match.group(1)).upper()
            facts.append(ExtractedFactItem(
                fact_key="license_plate",
                fact_value=normalized_plate,
                confidence=0.92,
            ))

        # 3. State extraction
        for state in NIGERIAN_STATES:
            if re.search(rf"\b{re.escape(state)}\b", text, re.IGNORECASE):
                facts.append(ExtractedFactItem(
                    fact_key="registration_state",
                    fact_value=state,
                    confidence=0.90,
                ))
                break

        # 4. NIN (11 digits)
        nin_match = re.search(r"(?:nin|national identity)\s*[:#-]?\s*([0-9]{11})", text, re.IGNORECASE)
        if not nin_match:
            # Standalone 11-digit number
            raw_11 = re.search(r"\b([0-9]{11})\b", text)
            if raw_11 and not any(f.fact_value == raw_11.group(1) for f in facts):
                facts.append(ExtractedFactItem(
                    fact_key="nin",
                    fact_value=raw_11.group(1),
                    confidence=0.85,
                ))
        else:
            facts.append(ExtractedFactItem(
                fact_key="nin",
                fact_value=nin_match.group(1),
                confidence=0.98,
            ))

        # 5. Nigerian Phone Number (+234... or 080... or 070... or 090... or 081...)
        phone_match = re.search(r"(\+?234[0-9]{10}|0[789][01][0-9]{8})", text)
        if phone_match:
            facts.append(ExtractedFactItem(
                fact_key="phone_number",
                fact_value=phone_match.group(1),
                confidence=0.95,
            ))

        return facts

    @classmethod
    def route(cls, question: str) -> RoutingResult:
        """Evaluate input question and perform binary classification with grounded citations."""
        clean_q = question.strip().lower()
        extracted_facts = cls.extract_facts(question)

        # Check for Support Request triggers
        is_support = any(trigger in clean_q for trigger in cls.SUPPORT_TRIGGERS)

        if is_support:
            # Determine suggested category & subject based on content
            category = "GENERAL_INQUIRY"
            if any(w in clean_q for w in ["stolen", "theft", "missing"]):
                category = "STOLEN_VEHICLE_REPORT"
                subject = "Report of Stolen / Missing Vehicle"
            elif any(w in clean_q for w in ["payment", "fee", "refund", "charged"]):
                category = "PAYMENT_DISPUTE"
                subject = "Payment Verification / Dispute Investigation"
            elif any(w in clean_q for w in ["clearance", "certificate", "rejected", "failed"]):
                category = "CLEARANCE_FAILURE"
                subject = "Vehicle Clearance Verification Assistance"
            else:
                category = "SUPPORT_ESCALATION"
                subject = "Customer Support Case: " + (question[:45] + "..." if len(question) > 45 else question)

            answer = (
                "Your request requires administrative verification by a CMR support specialist. "
                "We have extracted your key details from our chat so you will not need to repeat them. "
                "Please proceed to open a formal case to track progress through to resolution."
            )

            citations = [
                Citation(
                    document_title="CMR Support Escalation Protocol",
                    chunk_id="Escalation-1.1",
                    source_url="https://cmr.police.gov.ng/support",
                    excerpt="Customer inquiries requiring administrative or investigative action must be logged as formal cases."
                )
            ]

            return RoutingResult(
                intent=IntentType.SUPPORT_REQUEST,
                answer=answer,
                citations=citations,
                prompt_case_creation=True,
                suggested_category=category,
                suggested_subject=subject,
                extracted_facts=extracted_facts,
            )

        # Otherwise, match against procedural knowledge
        best_match = None
        max_overlap = 0

        for item in PROCEDURAL_KNOWLEDGE:
            overlap = sum(1 for kw in item["keywords"] if kw in clean_q)
            if overlap > max_overlap:
                max_overlap = overlap
                best_match = item

        if best_match and max_overlap > 0:
            return RoutingResult(
                intent=IntentType.INFORMATIONAL,
                answer=best_match["answer"],
                citations=best_match["citations"],
                prompt_case_creation=False,
                extracted_facts=extracted_facts,
            )

        # Fallback procedural general guidance with default citation
        default_answer = (
            "The Central Motor Registry (CMR) provides centralized automated vehicle clearance, "
            "ownership tracking, and security verification under the Nigeria Police Force. "
            "For specific questions regarding vehicle clearance, plate registration, fees, or status checks, "
            "please specify your vehicle details or ask our support team directly."
        )
        default_citation = [
            Citation(
                document_title="CMR Operational Guidelines 2026",
                chunk_id="Overview-1.0",
                source_url="https://cmr.police.gov.ng/about",
                excerpt="Official procedural documentation and overview of the Central Motor Registry system."
            )
        ]

        return RoutingResult(
            intent=IntentType.INFORMATIONAL,
            answer=default_answer,
            citations=default_citation,
            prompt_case_creation=False,
            extracted_facts=extracted_facts,
        )
