import uuid
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from app.cases.models import CasePriority


class BaseCaseCommand(BaseModel):
    """Base class for all named case transition commands."""
    command_name: str
    reason: Optional[str] = None

    def to_payload(self) -> Dict[str, Any]:
        """Convert command payload for storage in CaseEvent."""
        data = self.model_dump(mode="json")
        data.pop("command_name", None)
        return data


class TriageCommand(BaseCaseCommand):
    command_name: Literal["Triage"] = "Triage"
    category: str = Field(..., min_length=2, description="Case category (e.g. MOTOR_CLEARANCE)")
    priority: CasePriority = Field(default=CasePriority.NORMAL, description="Assigned priority")
    reason: str = Field(..., min_length=3, description="Triage rationale or assignment note")


class AssignCommand(BaseCaseCommand):
    command_name: Literal["Assign"] = "Assign"
    assignee_id: uuid.UUID = Field(..., description="UUID of the assigned support specialist")
    reason: str = Field(..., min_length=3, description="Reason for assignment")


class RequestInfoCommand(BaseCaseCommand):
    command_name: Literal["RequestInfo"] = "RequestInfo"
    requested_items: List[str] = Field(
        ..., min_length=1, description="List of required documents or details from customer"
    )
    reason: str = Field(..., min_length=3, description="Why additional info is needed")


class CustomerReplyCommand(BaseCaseCommand):
    command_name: Literal["CustomerReply"] = "CustomerReply"
    reply_text: str = Field(..., min_length=1, description="Customer reply content")
    message_id: Optional[uuid.UUID] = Field(None, description="Optional linked Message ID")
    reason: Optional[str] = Field(default="Customer provided response")


class ResolveCommand(BaseCaseCommand):
    command_name: Literal["Resolve"] = "Resolve"
    resolution_summary: str = Field(..., min_length=5, description="Summary of resolution")
    reason: str = Field(..., min_length=3, description="Resolution confirmation reason")


class ReopenCommand(BaseCaseCommand):
    command_name: Literal["Reopen"] = "Reopen"
    reason: str = Field(..., min_length=5, description="Justification for reopening the case")


class CloseCommand(BaseCaseCommand):
    command_name: Literal["Close"] = "Close"
    reason: str = Field(..., min_length=3, description="Closing confirmation notes")


CaseCommandUnion = (
    TriageCommand
    | AssignCommand
    | RequestInfoCommand
    | CustomerReplyCommand
    | ResolveCommand
    | ReopenCommand
    | CloseCommand
)
