import os
import pytest

# Ensure testing environment and mock LLM provider for all pytest executions
os.environ["ENVIRONMENT"] = "testing"
os.environ["LLM_PROVIDER"] = "mock"

from app.config import get_settings

get_settings.cache_clear()
