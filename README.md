# Company policy answer agent

A standalone LangChain/Anthropic agent answers employee policy questions from a small fictional document corpus. It searches for policy records, fetches full sources, returns a structured answer with exact IDs, and rejects unfetched, retired or irrelevant citations. Equal-priority current policies that disagree must be reported as a conflict.

## Run

Requires Python 3.12+, `uv`, an Anthropic API key and an enabled model name for live answers.

```sh
uv sync --extra test
uv run pytest -q
ANTHROPIC_API_KEY=... ANTHROPIC_MODEL=... uv run policy-answer \
  --as-of 2026-10-15 'How many remote days can I take per week?'
```

Questions outside the corpus return `insufficient` without a model call. The `--corpus` flag selects a different JSON corpus. No network or SaaS tool is needed apart from the model call. The agent has only two read-only local tools: list the topic's policy records and fetch a full record by ID.

The answer validator confirms that each citation was fetched and active for the requested date. It also detects conflicts among active highest-priority records for the topic. These checks establish source eligibility, not that every sentence of a live answer is entailed by a source. The model is instructed to ignore instruction-like text inside policy bodies; its behavior on that attack remains a live scenario to verify.

## Scenarios and evidence

[Scenario briefs](scenarios/README.md) cover current versus retired versions, equal-authority conflict, ordinary expenses, missing topics and a document-borne instruction. Seven offline tests pass using an injected answer path; they do not make an Anthropic call. Provider quality and usage remain unmeasured until a key is available.

This application is independent of Firedrill. The thin Firedrill adapter and persisted live scenario evidence wait for the released new interface. The repository is private and has no selected public license.

Implementation references: [LangChain agents](https://docs.langchain.com/oss/python/langchain/agents), [structured output](https://docs.langchain.com/oss/python/langchain/structured-output), [ChatAnthropic](https://docs.langchain.com/oss/python/integrations/chat/anthropic).
