"""Test configuration."""

import os
import sys

# Ensure the project root is in the path
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Set test environment variables
os.environ.setdefault("DATABASE_URL", "sqlite:///test.db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("STORAGE_MODE", "local")
os.environ.setdefault("LOCAL_STORAGE_PATH", "/tmp/compose_test_storage")
os.environ.setdefault("ANTHROPIC_API_KEY", "")
os.environ.setdefault("PEXELS_API_KEY", "")
