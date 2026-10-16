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


def extended_corpus(tmp_path,updates):
    import json
    rows=json.loads(CORPUS.read_text());rows.extend(updates)
    file=tmp_path/'corpus.json';file.write_text(json.dumps(rows));return PolicyCorpus(file)


def test_lower_priority_source_cannot_replace_the_current_authority(tmp_path):
    from policy_answer.answer import validate_answer
    lower=PolicyCorpus(CORPUS).by_id['REMOTE-2026'].model_dump(mode='json')
    lower.update(id='REMOTE-LOCAL',priority=1,rule_code='five-days',body='Local guide allows five days.')
    corpus=extended_corpus(tmp_path,[lower])
    with pytest.raises(ValueError,match='highest-priority'):
        validate_answer(SourceAnswer(status='answered',answer='Five days.',citations=['REMOTE-LOCAL']),corpus,'remote-work',TODAY,{'REMOTE-LOCAL'})
    with pytest.raises(ValueError,match='equally highest'):
        validate_answer(SourceAnswer(status='conflict',answer='The two guides conflict.',citations=['REMOTE-2026','REMOTE-LOCAL']),corpus,'remote-work',TODAY,{'REMOTE-2026','REMOTE-LOCAL'})
    validate_answer(SourceAnswer(status='answered',answer='Two days; the local guide has lower authority.',citations=['REMOTE-2026','REMOTE-LOCAL']),corpus,'remote-work',TODAY,{'REMOTE-2026','REMOTE-LOCAL'})


def test_historical_authority_uses_requested_date_and_inclusive_boundaries():
    corpus=PolicyCorpus(CORPUS)
    assert [p.id for p in corpus.active_authorities('remote-work',date(2025,12,31))]==['REMOTE-2024']
    assert [p.id for p in corpus.active_authorities('remote-work',date(2026,1,1))]==['REMOTE-2026']
    from policy_answer.answer import validate_answer
    validate_answer(SourceAnswer(status='answered',answer='Three days in 2024.',citations=['REMOTE-2024']),corpus,'remote-work',date(2024,6,1),{'REMOTE-2024'})


def test_corpus_is_byte_identified_and_records_cannot_be_mutated():
    import hashlib
    from pydantic import ValidationError
    corpus=PolicyCorpus(CORPUS)
    assert corpus.sha256==hashlib.sha256(CORPUS.read_bytes()).hexdigest()
    with pytest.raises(ValidationError):corpus.by_id['REMOTE-2026'].priority=1
    with pytest.raises(TypeError):corpus.by_id['wrong']=corpus.documents[0]


@pytest.mark.parametrize('change',[{'priority':True},{'effective_until':'2023-01-01'},{'keywords':['remote','REMOTE']},{'body':'  '},{'status':'unsupported'}])
def test_malformed_policy_records_fail_before_model(tmp_path,change):
    from pydantic import ValidationError
    item=PolicyCorpus(CORPUS).documents[0].model_dump(mode='json');item.update(id='invalid',**change)
    with pytest.raises(ValidationError):extended_corpus(tmp_path,[item])


def test_same_rule_code_does_not_hide_a_legitimate_body_conflict(tmp_path):
    from policy_answer.answer import validate_answer
    other=PolicyCorpus(CORPUS).by_id['REMOTE-2026'].model_dump(mode='json')
    other.update(id='REMOTE-CIRCULAR',body='Employees may work remotely without any weekly limit or manager approval.')
    corpus=extended_corpus(tmp_path,[other])
    validate_answer(SourceAnswer(status='conflict',answer='The two equal authorities say different things despite matching codes.',citations=['REMOTE-2026','REMOTE-CIRCULAR']),corpus,'remote-work',TODAY,{'REMOTE-2026','REMOTE-CIRCULAR'})


def test_oversized_source_is_rejected_before_parsing_or_model_work(tmp_path):
    file=tmp_path/'large.json';file.write_bytes(b' '*(4_194_304+1))
    with pytest.raises(ValueError,match='exceeds 4 MiB'):PolicyCorpus(file)
