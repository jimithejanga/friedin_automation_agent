from typing import Any, List, Optional
from sqlalchemy.types import JSON, TypeDecorator

try:
    from pgvector.sqlalchemy import Vector
except ImportError:
    Vector = None


class PgVectorType(TypeDecorator):
    """Platform-independent Vector type.
    Uses pgvector's Vector type when running on PostgreSQL,
    and falls back to JSON-serialized float arrays on SQLite / other engines.
    """

    impl = JSON
    cache_ok = True

    def __init__(self, dim: int = 1536):
        super().__init__()
        self.dim = dim

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql" and Vector is not None:
            return dialect.type_descriptor(Vector(self.dim))
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return value
        if dialect.name == "postgresql":
            # pgvector accepts list of floats directly or Vector objects
            return value
        # In SQLite / JSON fallback, store as a python list
        if isinstance(value, (list, tuple)):
            return [float(x) for x in value]
        return list(value)

    def process_result_value(self, value: Any, dialect: Any) -> Optional[List[float]]:
        if value is None:
            return value
        if isinstance(value, list):
            return [float(x) for x in value]
        try:
            # Handle numpy arrays or pgvector objects if returned
            return [float(x) for x in value]
        except Exception:
            return value
