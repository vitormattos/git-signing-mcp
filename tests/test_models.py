import pytest
from pydantic import ValidationError

from git_signing_mcp.models import FileChange


def test_upsert_requires_content():
    with pytest.raises(ValidationError):
        FileChange(path="README.md", operation="upsert")


def test_delete_rejects_content():
    with pytest.raises(ValidationError):
        FileChange(path="README.md", operation="delete", content="x")
