"""Read-only policy corpus and deterministic evidence checks."""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from pydantic import BaseModel, Field


class Policy(BaseModel):
    id: str
    topic: str
    title: str
    keywords: list[str]
    status: str
    effective_from: date
    effective_until: date | None
    priority: int
    rule_code: str
    body: str

    def active(self, as_of: date) -> bool:
        return self.status == "current" and self.effective_from <= as_of and (
            self.effective_until is None or as_of <= self.effective_until
        )


class PolicyCorpus:
    def __init__(self, path: str | Path):
        raw = json.loads(Path(path).read_text())
        self.documents = [Policy.model_validate(item) for item in raw]
        self.by_id = {item.id: item for item in self.documents}
        if len(self.documents) != len(self.by_id):
            raise ValueError("duplicate policy id")

    def topic_for(self, question: str) -> str | None:
        text = question.casefold()
        scores: dict[str, int] = {}
        for doc in self.documents:
            score = sum(1 for term in doc.keywords if re.search(r"\b" + re.escape(term.casefold()) + r"\b", text))
            scores[doc.topic] = max(scores.get(doc.topic, 0), score)
        maximum = max(scores.values(), default=0)
        winners = [topic for topic, score in scores.items() if score == maximum and score > 0]
        return winners[0] if len(winners) == 1 else None

    def search(self, topic: str, as_of: date) -> list[dict]:
        docs = [doc for doc in self.documents if doc.topic == topic]
        docs.sort(key=lambda doc: (not doc.active(as_of), -doc.priority, doc.id))
        return [{
            "id": doc.id, "title": doc.title, "active": doc.active(as_of),
            "effective_from": doc.effective_from.isoformat(),
            "effective_until": doc.effective_until.isoformat() if doc.effective_until else None,
            "summary": doc.body[:150],
        } for doc in docs]

    def fetch(self, policy_id: str) -> dict:
        doc = self.by_id.get(policy_id)
        if doc is None:
            raise KeyError(f"unknown policy: {policy_id}")
        return doc.model_dump(mode="json")

    def active_authorities(self, topic: str, as_of: date) -> list[Policy]:
        active = [doc for doc in self.documents if doc.topic == topic and doc.active(as_of)]
        if not active:
            return []
        highest = max(doc.priority for doc in active)
        return [doc for doc in active if doc.priority == highest]

    def has_conflict(self, topic: str, as_of: date) -> bool:
        return len({doc.rule_code for doc in self.active_authorities(topic, as_of)}) > 1
