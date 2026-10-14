"""M08 测试 conftest。"""
import tempfile
import pytest


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as td:
        yield td
