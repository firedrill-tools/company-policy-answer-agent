# Simulate this agent with Firedrill

Firedrill is a simulation platform for AI agents. Your coding agent can prepare
and operate these simulations; the application and its model run in your own
repository or CI.

Start in the repository root, not inside `firedrill/`:

```sh
npx firedrill-run init
```

Authorize Firedrill and select a project/environment. Installation choices are
optional; skip them when using the locked `firedrill/` toolchain below. This setup
does not invoke the target agent or grant it access to real business accounts.

Released CLI and TypeScript SDK **2.2.2**, verified October 19, 2026, are exact-pinned in this separate optional toolchain. It requires Node 22+ and leaves the application's Python/framework dependencies unchanged. This is a supported command target; no Firedrill SDK import is added to the agent itself.

## Prepare

From the repository root, run `uv sync --locked --extra test` with `uv` on PATH. Then:

```sh
npm ci --prefix firedrill --ignore-scripts --no-audit --no-fund
firedrill_cli=firedrill/node_modules/@firedrill-run/cli/bin/firedrill.mjs
node "$firedrill_cli" validate firedrill/scenario.json --json --non-interactive
```

The offline checks cover the released recipe validator, current invocation envelope, real application missing-credential failure, subprocess cancellation and retained partial errors. No model response or saved Firedrill report is fabricated.

## Select scope and execute

Run `npx firedrill-run init` in a human terminal to authorize and select the actual project/environment. Automation supplies `FIREDRILL_TOKEN`, `FIREDRILL_PROJECT_ID` and `FIREDRILL_ENVIRONMENT_ID` through its secret store. The application independently needs `ANTHROPIC_API_KEY` and an enabled model; its ordinary model configuration remains in the main README. Tokens never belong in recipes or source.

With an authorized model budget:

```sh
node firedrill/simulate.mjs --preview
node "$firedrill_cli" simulate firedrill/scenario.json --scenario starter --json --non-interactive
```

The selected case invokes the real `policy-answer --case` entry point and actual LangChain/Anthropic runtime. The full recipe has two reviewed cases, one repetition and concurrency one. `node firedrill/simulate.mjs` executes that full recipe using the SDK. An optional `configuration.parameters.model` selects an enabled model. Existing per-application request/deadline bounds apply; they are not provider billing guarantees. No synthetic Firedrill Tool is required for these read-only inputs.

The adapter accepts invocation version `2026-10-17-target-invocation.1`, ID-only scenario context and explicit case input. Controller checks/rubrics and unsupported Tool bindings are rejected. It returns actual application JSON; nonzero application status retains partial stdout/stderr as failure evidence. Operator/CI credentials are removed from the child environment. Every invocation uses the application's fresh runtime over immutable/read-only selected source; retain its private receipts. Independent source edits require fresh case copies. Resetting inputs cannot erase provider retention or billing.

## MCP, recovery and CI

Use the remote OAuth MCP endpoint **https://mcp.firedrill.run/mcp** with the [host-specific setup](https://docs.firedrill.run/guides/coding-agents); no local MCP package is required. MCP host OAuth and CLI/SDK login are separate. MCP can prepare, queue and inspect; the local runner executes. Attach an existing batch with `node firedrill/simulate.mjs --run BATCH_ID`.

Preserve operation IDs and private journals after uncertainty. Use `--resume OPERATION_ID` to recover the exact execution and `--result BATCH_ID` to read retained results. A fresh simulation is new work. Runner exit codes preserve pending execution/assessment, errors and optional gates; completed execution is not correctness. This observation-only recipe requests no evaluation or gate.

Existing CI runs offline checks. Configure actual scope, protected secrets and model budgets before using the released [live CI generator](https://docs.firedrill.run/guides/ci). Authenticated persisted happy/negative runs, live Anthropic quality/cost, public release and licensing remain separate gates.

References: [SDK](https://docs.firedrill.run/sdk/typescript), [command contract](https://docs.firedrill.run/guides/callbacks), [CLI](https://docs.firedrill.run/cli/overview), [operator MCP](https://docs.firedrill.run/guides/control-mcp).

## Offline verification

After installing the application dependencies and locked integration toolchain,
run `npm test --prefix firedrill` to exercise the adapter checks. These checks are
optional for first use and call no paid model. The Node 22+ requirement above is
for the Firedrill clients; it does not lower any application runtime requirement
in the root README.
