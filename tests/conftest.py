import pytest


@pytest.fixture(autouse=True)
def isolated_output(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv('ANTHROPIC_API_KEY',raising=False)
    monkeypatch.delenv('ANTHROPIC_MODEL',raising=False)
    monkeypatch.setenv('LANGSMITH_TRACING','false')
    monkeypatch.setenv('LANGCHAIN_TRACING_V2','false')
