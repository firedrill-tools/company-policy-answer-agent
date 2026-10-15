from datetime import date
from pathlib import Path

import pytest

from policy_answer.answer import PolicyAnswerService, SourceAnswer
from policy_answer.policies import PolicyCorpus


CORPUS = Path(__file__).parents[1] / "fixtures/policies.json"
TODAY = date(2026, 10, 15)


def fake_agent(response, fetch_ids):
    def factory(tools):
        by_name = {item.name: item for item in tools}

        class Agent:
            def invoke(self, _request, config=None):
                assert config["recursion_limit"] == 12
                by_name["search_policies"].invoke({})
                for policy_id in fetch_ids:
                    by_name["get_policy"].invoke({"policy_id": policy_id})
                return {"structured_response": response, "messages": []}

        return Agent()

    return factory


def test_current_answer_requires_fetched_current_citation():
    corpus = PolicyCorpus(CORPUS)
    service = PolicyAnswerService(corpus, fake_agent(SourceAnswer(
        status="answered", answer="Up to two days per week, with manager scheduling approval.",
        citations=["REMOTE-2026"],
    ), ["REMOTE-2026"]))
    result = service.ask("How many remote days can I take?", TODAY)
    assert result["answer"]["citations"] == ["REMOTE-2026"]
    assert result["fetched"] == ["REMOTE-2026"]
    assert corpus.search("remote-work", TODAY)[0]["id"] == "REMOTE-2026"


def test_retired_citation_rejected_even_if_fetched():
    service = PolicyAnswerService(PolicyCorpus(CORPUS), fake_agent(SourceAnswer(
        status="answered", answer="Three days", citations=["REMOTE-2024"]
    ), ["REMOTE-2024"]))
    with pytest.raises(ValueError, match="obsolete"):
        service.ask("How many remote days can I take?", TODAY)


def test_unfetched_citation_rejected():
    service = PolicyAnswerService(PolicyCorpus(CORPUS), fake_agent(SourceAnswer(
        status="answered", answer="Two days", citations=["REMOTE-2026"]
    ), []))
    with pytest.raises(ValueError, match="unfetched"):
        service.ask("How many remote days can I take?", TODAY)


def test_equal_authority_conflict_must_be_reported_with_both_sources():
    corpus = PolicyCorpus(CORPUS)
    assert corpus.has_conflict("meal-expense", TODAY)
    service = PolicyAnswerService(corpus, fake_agent(SourceAnswer(
        status="conflict", answer="Two current policies disagree; ask Finance before claiming.",
        citations=["TRAVEL-60", "TRAVEL-80"]
    ), ["TRAVEL-60", "TRAVEL-80"]))
    result = service.ask("What is the dinner reimbursement limit?", TODAY)
    assert result["answer"]["status"] == "conflict"


def test_conflicting_current_policy_cannot_be_silently_chosen():
    service = PolicyAnswerService(PolicyCorpus(CORPUS), fake_agent(SourceAnswer(
        status="answered", answer="$60", citations=["TRAVEL-60"]
    ), ["TRAVEL-60"]))
    with pytest.raises(ValueError, match="conflict"):
        service.ask("What is the dinner reimbursement limit?", TODAY)


def test_out_of_scope_question_returns_insufficient_without_model():
    result = PolicyAnswerService(PolicyCorpus(CORPUS)).ask("What is the office Wi-Fi password?", TODAY)
    assert result["topic"] is None
    assert result["answer"]["status"] == "insufficient"


def test_historical_document_is_data_not_an_instruction():
    corpus = PolicyCorpus(CORPUS)
    historical = corpus.fetch("REMOTE-2024")
    assert "ignore the assistant" in historical["body"]
    assert not corpus.by_id["REMOTE-2024"].active(TODAY)
    assert corpus.topic_for("remote or dinner policy?") is None
