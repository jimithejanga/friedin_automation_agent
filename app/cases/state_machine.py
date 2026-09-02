from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid

from fastapi import HTTPException, status

from app.cases.models import Case, CasePriority, CaseStatus


HTTP_422 = getattr(
    status, "HTTP_422_UNPROCESSABLE_CONTENT", status.HTTP_422_UNPROCESSABLE_ENTITY
)


class IllegalStateTransitionError(HTTPException):
    """Raised when a command cannot be applied from the current case status (HTTP 422)."""

    def __init__(
        self,
        current_status: CaseStatus | str,
        command_name: str,
        allowed_commands: List[str],
    ):
        status_val = (
            current_status.value
            if isinstance(current_status, CaseStatus)
            else str(current_status)
        )
        super().__init__(
            status_code=HTTP_422,
            detail={
                "error": "ILLEGAL_STATE_TRANSITION",
                "message": f"Cannot execute command '{command_name}' when case status is '{status_val}'.",
                "current_status": status_val,
                "attempted_command": command_name,
                "allowed_commands": allowed_commands,
            },
        )


class UnauthorizedCommandError(HTTPException):
    """Raised when an actor role is not permitted to execute a command (HTTP 403)."""

    def __init__(self, command_name: str, actor_role: str, allowed_roles: List[str]):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "UNAUTHORIZED_COMMAND",
                "message": f"Role '{actor_role}' is not authorized to execute command '{command_name}'.",
                "command": command_name,
                "actor_role": actor_role,
                "allowed_roles": allowed_roles,
            },
        )


class CaseStateMachine:
    """Strict transition engine for Case lifecycle.
    Transitions: NEW -> TRIAGED -> WAITING <-> IN_REVIEW -> RESOLVED -> CLOSED.
    Reopening from RESOLVED or CLOSED returns to IN_REVIEW.
    """

    # Transition Mapping: (current_status, command_name) -> next_status
    TRANSITION_MAP: Dict[tuple[CaseStatus, str], CaseStatus] = {
        (CaseStatus.NEW, "Triage"): CaseStatus.TRIAGED,
        (CaseStatus.TRIAGED, "Assign"): CaseStatus.IN_REVIEW,
        (CaseStatus.IN_REVIEW, "RequestInfo"): CaseStatus.WAITING,
        (CaseStatus.WAITING, "CustomerReply"): CaseStatus.IN_REVIEW,
        (CaseStatus.IN_REVIEW, "Resolve"): CaseStatus.RESOLVED,
        (CaseStatus.RESOLVED, "Close"): CaseStatus.CLOSED,
        (CaseStatus.RESOLVED, "Reopen"): CaseStatus.IN_REVIEW,
        (CaseStatus.CLOSED, "Reopen"): CaseStatus.IN_REVIEW,
    }

    # Role Permissions per command
    COMMAND_ROLES: Dict[str, List[str]] = {
        "Triage": ["support", "supervisor", "admin"],
        "Assign": ["support", "supervisor", "admin"],
        "RequestInfo": ["support", "supervisor", "admin"],
        "CustomerReply": ["customer", "system"],
        "Resolve": ["support", "supervisor", "admin"],
        "Close": ["support", "supervisor", "admin", "system"],
        "Reopen": ["customer", "support", "supervisor", "admin"],
    }

    @classmethod
    def get_allowed_commands(cls, current_status: CaseStatus) -> List[str]:
        """Return list of valid command names for the given status."""
        return [cmd for (st, cmd) in cls.TRANSITION_MAP.keys() if st == current_status]

    @classmethod
    def validate_transition(
        cls,
        case: Case,
        command_name: str,
        actor_role: str,
    ) -> CaseStatus:
        """Validate command existence, role authorization, and state transition.
        Raises UnauthorizedCommandError (403) or IllegalStateTransitionError (422).
        """
        if command_name not in cls.COMMAND_ROLES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown command: '{command_name}'. Valid commands: {list(cls.COMMAND_ROLES.keys())}",
            )

        # Check role authorization
        allowed_roles = cls.COMMAND_ROLES[command_name]
        if actor_role.lower() not in [r.lower() for r in allowed_roles]:
            raise UnauthorizedCommandError(command_name, actor_role, allowed_roles)

        # Check state transition
        current_status = (
            case.status
            if isinstance(case.status, CaseStatus)
            else CaseStatus(case.status)
        )
        transition_key = (current_status, command_name)

        if transition_key not in cls.TRANSITION_MAP:
            allowed_cmds = cls.get_allowed_commands(current_status)
            raise IllegalStateTransitionError(current_status, command_name, allowed_cmds)

        return cls.TRANSITION_MAP[transition_key]

    @classmethod
    def apply_transition(
        cls,
        case: Case,
        command_name: str,
        actor_role: str,
        payload: Dict[str, Any],
    ) -> tuple[CaseStatus, CaseStatus]:
        """Validate and mutate case attributes based on command.
        Returns (from_status, to_status).
        """
        from_status = (
            case.status
            if isinstance(case.status, CaseStatus)
            else CaseStatus(case.status)
        )
        to_status = cls.validate_transition(case, command_name, actor_role)

        # Mutate case status
        case.status = to_status
        now_utc = datetime.now(timezone.utc)
        case.updated_at = now_utc

        # Command-specific field mutations
        if command_name == "Triage":
            if "category" in payload and payload["category"]:
                case.category = payload["category"]
            if "priority" in payload and payload["priority"]:
                p = payload["priority"]
                case.priority = p if isinstance(p, CasePriority) else CasePriority(p)

        elif command_name == "Assign":
            if "assignee_id" in payload and payload["assignee_id"]:
                raw_id = payload["assignee_id"]
                case.assigned_to = (
                    raw_id if isinstance(raw_id, uuid.UUID) else uuid.UUID(str(raw_id))
                )

        elif command_name == "Resolve":
            case.resolved_at = now_utc

        elif command_name == "Close":
            case.closed_at = now_utc

        elif command_name == "Reopen":
            # Reopening returns to IN_REVIEW. Historical timestamps remain recorded in CaseEvents.
            case.resolved_at = None
            case.closed_at = None

        return from_status, to_status
