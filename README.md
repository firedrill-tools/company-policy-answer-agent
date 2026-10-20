# Company policy answer agent with LangChain and Claude

A LangChain agent searches a fictional company-policy corpus, fetches exact sources and returns a typed answer with citations. Eligibility checks enforce the requested effective date, topic and authority priority. Conflicting sources remain visible. The agent has two local read tools and cannot change policy or contact a business service.

## Simulate with Firedrill

[Firedrill](https://firedrill.run/) is a simulation platform for AI agents.
Start from this repository’s root:

```sh
npx firedrill-run init
```

Sign in and choose your project, then follow the [simulation run guide](firedrill/README.md)
for application dependencies, a preview and the reviewed scenarios. Your agent runs
locally or in your CI; model credentials stay separate from Firedrill sign-in.
The included recipes record outcomes without an automatic quality score or CI gate.

## Run one case

Requires Python 3.12+ and `uv`. Listing, copying data and unsupported/ambiguous-topic clarification need no provider key.

```sh
uv sync --locked --extra test
uv run --locked policy-answer --list-cases
uv run --locked policy-answer --case starter --model claude-sonnet-4-6
```

Set `ANTHROPIC_API_KEY` through your environment/secret manager before a model answer. `--model` or `ANTHROPIC_MODEL` selects an enabled `claude-*` model. Fresh supported questions call Anthropic and incur provider usage. The normal CLI has no scripted answer mode; `.env.example` lists configuration names but is not auto-loaded.

For a question of your own, the default bundled starter corpus works independently of the working directory:

```sh
uv run --locked policy-answer --as-of 2026-10-15 --model claude-sonnet-4-6 \
  'How many remote days can I take per week?'
uv run --locked policy-answer --init-case busy --corpus run-output/policies.json
uv run --locked policy-answer --corpus run-output/policies.json --as-of 2026-10-15 \
  --model claude-sonnet-4-6 'Does a USD 110 office equipment purchase need approval?'
```

`--case` supplies its fixed question/date/source. `--init-case` validates all bundle hashes and creates a private copy exclusively, printing the question/date/identity; it never overwrites. A custom `--corpus` can be an original JSON policy array or a wrapped synthetic snapshot. Its actual byte hash is recorded; an inherited dataset tag alone does not establish manifest qualification. `--output-root DIR` chooses the receipt root.

The provider endpoint defaults explicitly to `https://api.anthropic.com`. `--base-url` or the callable's `base_url` selects an explicit HTTPS endpoint or loopback HTTP endpoint without URL credentials/query/fragment. Provider-global endpoint/gateway variables do not choose it. No real source collection, mailbox or SaaS fallback is configured.

The callable uses the same normal runtime:

```python
from datetime import date
from policy_answer.answer import PolicyAnswerService
from policy_answer.datasets import select

case, corpus, _ = select("starter")
result = await PolicyAnswerService(corpus).ask_async(
    case["question"], date.fromisoformat(case["as_of"]),
    "claude-sonnet-4-6", output_root="run-output/receipts")
```

Synchronous applications use `ask`; callers already in an event loop use `ask_async`. `python -m policy_answer.cli` is the same CLI. Trusted `agent_factory` injection is a lower-level composition/test seam, labeled `caller_injected_agent`; its resources/observations remain caller-owned and are not native provider evidence.

## Source eligibility and authority

| Rule | Application check |
|---|---|
| Topic | Deterministic keyword match; tied/unsupported topics request clarification without a model |
| Read evidence | Every citation must name a source actually fetched through `get_policy` |
| Date | Inclusive effective interval; retired versions can establish historical policy only within their known interval |
| Approval | Draft records are never eligible; retired records require a known historical end date |
| Authority | An answered question must cite at least one highest-priority eligible source; a lower guide cannot replace it |
| Known conflict | Different rule codes among equal highest authorities require conflict status and coverage of all those sources |
| Semantic conflict | Two equal authorities may contradict each other despite matching codes; conflict can still be reported with both sources |

Inactive or unrelated records cannot support citations, including an insufficient answer. `insufficient` may legitimately state that a supported topic lacks the requested fact. The validator establishes source eligibility/coverage, **not that every sentence follows from the cited text**. Semantic contradictions, misleading prose and malicious source instructions require actual model assessment; SDK completion is not a correctness score.

`search_policies` returns matching records with priority/status/date and a short body summary; `get_policy` returns one exact full record or an explicit unknown-ID error. Tools do not expose the manifest, scenario briefs or other topics' full bodies automatically. Source records/indices are immutable in memory. The original file is checked before model work and before answer release; a changed file requires reload/review and leaves failed-run evidence. Input reads are bounded to 4 MiB; malformed/duplicate records, invalid intervals/priorities and blank text fail before model use.

## Native completion, budgets and ownership

Pinned execution uses LangChain **1.4.6**, langchain-anthropic **1.7.6**, Anthropic **1.14.0** and HTTPX2 **2.13.1**; the lock also pins the exercised LangGraph dependency. The real graph uses `create_agent` and [ToolStrategy](https://docs.langchain.com/oss/python/langchain/structured-output), with `handle_errors=False`. A native HTTP probe accepted structured answers marked `max_tokens` and tool output marked `end_turn`. Public HTTP hooks now reject unfinished/inconsistent, malformed, blank, unsupported and mixed answer/read responses before tools or structured output can be released. JSON Messages is qualified; wire SSE is not.

Limits are eight prepared HTTP attempts, 24 source-read calls, four calls per response, 4,096 output tokens, 30-second HTTP phase timeouts and a 120-second cooperative overall deadline. The graph's recursion limit is 12 and can stop earlier. SDK retries are zero and invalid structured output is not automatically repaired. CLI SIGINT/SIGTERM and async caller cancellation close owned clients and retain available observations. Local cancellation does not establish that remote generation/billing stopped.

Each native invocation owns a fresh graph/model, SDK/HTTP client, fetched-source set and receipt. Synchronous source functions also have native async tool implementations, so cancellation does not leave background source-tool threads. Read-only invocations can share an immutable corpus while using independent per-run clients/evidence. A supplied transport is consumed/closed by its run; use independent instances for independent runs. No checkpointer, durable conversation or provider session is configured.

The pinned ChatAnthropic release lacks a client constructor field. A small subclass overrides only its two SDK-access properties to select the owned async client and reject accidental synchronous fallback. Native request building, formatting, tool binding and the agent loop remain inherited. No vendor file or global cache is patched. [Compatibility notes](COMPATIBILITY.md) explain this version-sensitive seam and upgrade checks. See also the [official ChatAnthropic reference](https://reference.langchain.com/python/langchain-anthropic/chat_models/ChatAnthropic) and [Anthropic SDK](https://github.com/anthropics/anthropic-sdk-python).

## Receipts, failure and usage

Every valid invocation begins private schema-1 evidence before model work, under `.runs/<run-id>/receipt.json` in the working directory by default. Run directories are 0700, files 0600; writes stage/flush/fsync and atomically replace. Receipts retain question/date/prompt/source hashes, declared dataset identity, actual installed versions, requested/reported models, original decoded provider bodies/error text/status/request IDs, source-tool IDs/arguments/results, available normalized SDK messages and final result/error causes. Credentials/config objects are not copied.

`completed` means a typed answer passed eligibility checks, or a model-free clarification returned. `failed` includes provider/validation/cancellation/source-change/recording errors. CLI failures exit nonzero; signals exit 130. Callable errors expose `receipt_path` and in-memory `evidence`. Earlier source reads and raw model output remain available after failure, with no successful answer result. Forced termination may leave a running receipt. A persistent final write failure exposes `evidence_error` and cannot claim the last file was updated. Recording failures prevent further reads, network attempts and answer release.

Provider bodies are decoded HTTP response bytes captured before SDK defaults, not compressed wire bytes. The 1 MiB evidence cap applies after HTTP buffering, not to network/memory allocation. Oversized output stops release while retaining truncated content/hash and parseable measurements. A read failure may leave body/usage unavailable. SDK messages are available when the graph returns; raw HTTP observations preserve prior responses even when the graph raises.

`reported_usage` keeps missing/partial/invalid and explicitly reported zero distinct. Input totals combine uncached, cache-creation and cache-read counts; complete totals require all four necessary counters for every observed attempt. Failed attempts retain reported measurements. `usage`/`sdk_messages` separately contain normalized SDK observations and must not be added as extra executions. Cost stays unknown. A prepared request observation is not proof it reached the provider or completed; model-free clarification has no provider attempts and is not a fresh model execution.

Reset for this read-only application means a fresh invocation/receipt, or a fresh private source copy for edited conditions. Stop an owner before replacing its source. Reset does not delete receipts, provider retention/billing or caller resources. Shared immutable source data does not imply shared agent state.

## Data, checks and distribution

`synthetic-policy-cases` version **1** contains eleven hash-bound cases/four profiles: starter, busy, conflicting authorities, contradictory bodies, historical boundary, missing answer, hostile archive, lower authority, future effective date, ambiguous topic and out-of-scope. Busy has **24 policies across eight topics**, each with coherent historical/current/departmental records. All text, dates and amounts are fictional; no model answers or measured usage are seeded. Only the selected question/date and tool records enter the model. [Scenario briefs](scenarios/README.md) and manifest expectations stay outside its context.

```sh
uv run --locked --extra test pytest -q
uv run --locked python scripts/build_fixtures.py
uv build
uv run --locked python scripts/check_distribution.py
```

The 62 offline checks include actual graph/ChatAnthropic/HTTP execution, normal CLI over loopback HTTP, completion/error/SIGTERM, source changes, independent concurrent reads, ownership/startup failure, raw usage, recording failures and data drift. Older injected-agent tests remain separate. Controlled responses verify application boundaries, not Claude judgment, a success rate or measured billing. CI regenerates exact fixture bytes.

Wheel and sdist gates install fresh locked dependencies outside checkout and exercise console/module CLI, eleven private copies, model-free clarification, missing-key failure evidence and actual busy/historical authority operations. Live Claude quality/budget, authenticated persisted Firedrill runs, publication and license choice remain parked. The included Firedrill adapter uses the existing CLI/corpus/receipt seams. Explore the [example catalog](https://github.com/firedrill-tools/firedrill-example-catalog), [Firedrill](https://firedrill.run/) and [official documentation](https://docs.firedrill.run/).

## Current Firedrill connection — 2026-10-19

The [agent-first adapter and recipe](firedrill/README.md) now use exact-pinned CLI/SDK 2.2.2 and the current command envelope. This supersedes earlier notes saying the release was unavailable. Offline validation is distinct from authenticated persisted execution and live model quality, which remain pending.
