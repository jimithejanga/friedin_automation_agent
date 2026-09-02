"""Initial schema creating core tables and pgvector extension.

Revision ID: 0001_initial_schema
Revises: 
Create Date: 2026-09-02 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.platform.database import GUID

# revision identifiers, used by Alembic.
revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Conditionally enable pgvector extension in PostgreSQL
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    # 2. Table: persons
    op.create_table(
        "persons",
        sa.Column("id", GUID(), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("phone_number", sa.String(length=64), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("nin_or_bvn", sa.String(length=128), nullable=True),
        sa.Column("contact_preferences", sa.JSON(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_persons_phone_number", "persons", ["phone_number"])
    op.create_index("ix_persons_email", "persons", ["email"])

    # 3. Table: cases
    op.create_table(
        "cases",
        sa.Column("id", GUID(), nullable=False),
        sa.Column("case_number", sa.String(length=64), nullable=False),
        sa.Column("person_id", GUID(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("priority", sa.String(length=32), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("assigned_to", GUID(), nullable=True),
        sa.Column("sla_deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["person_id"], ["persons.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cases_case_number", "cases", ["case_number"], unique=True)
    op.create_index("ix_cases_person_id", "cases", ["person_id"])
    op.create_index("ix_cases_status", "cases", ["status"])
    op.create_index("ix_cases_priority", "cases", ["priority"])
    op.create_index("ix_cases_category", "cases", ["category"])
    op.create_index("ix_cases_assigned_to", "cases", ["assigned_to"])

    # 4. Table: case_events
    op.create_table(
        "case_events",
        sa.Column("id", GUID(), nullable=False),
        sa.Column("case_id", GUID(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("from_status", sa.String(length=32), nullable=True),
        sa.Column("to_status", sa.String(length=32), nullable=True),
        sa.Column("command_name", sa.String(length=64), nullable=True),
        sa.Column("actor_id", GUID(), nullable=True),
        sa.Column("actor_role", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_case_events_case_id", "case_events", ["case_id"])
    op.create_index("ix_case_events_event_type", "case_events", ["event_type"])
    op.create_index("ix_case_events_command_name", "case_events", ["command_name"])
    op.create_index("ix_case_events_actor_id", "case_events", ["actor_id"])
    op.create_index(
        "ix_case_events_case_created", "case_events", ["case_id", "created_at"]
    )

    # 5. Table: conversations
    op.create_table(
        "conversations",
        sa.Column("id", GUID(), nullable=False),
        sa.Column("person_id", GUID(), nullable=False),
        sa.Column("case_id", GUID(), nullable=True),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["person_id"], ["persons.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_conversations_person_id", "conversations", ["person_id"])
    op.create_index("ix_conversations_case_id", "conversations", ["case_id"])

    # 6. Table: messages
    op.create_table(
        "messages",
        sa.Column("id", GUID(), nullable=False),
        sa.Column("conversation_id", GUID(), nullable=False),
        sa.Column("sender_type", sa.String(length=32), nullable=False),
        sa.Column("sender_id", GUID(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("citations", sa.JSON(), nullable=False),
        sa.Column("intent", sa.String(length=64), nullable=True),
        sa.Column("attachments", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"])
    op.create_index(
        "ix_messages_conv_created", "messages", ["conversation_id", "created_at"]
    )

    # 7. Table: extracted_facts
    op.create_table(
        "extracted_facts",
        sa.Column("id", GUID(), nullable=False),
        sa.Column("case_id", GUID(), nullable=False),
        sa.Column("conversation_id", GUID(), nullable=True),
        sa.Column("message_id", GUID(), nullable=True),
        sa.Column("fact_key", sa.String(length=64), nullable=False),
        sa.Column("fact_value", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_extracted_facts_case_id", "extracted_facts", ["case_id"])
    op.create_index(
        "ix_extracted_facts_conversation_id", "extracted_facts", ["conversation_id"]
    )
    op.create_index("ix_extracted_facts_fact_key", "extracted_facts", ["fact_key"])


def downgrade() -> None:
    op.drop_table("extracted_facts")
    op.drop_table("messages")
    op.drop_table("conversations")
    op.drop_table("case_events")
    op.drop_table("cases")
    op.drop_table("persons")
