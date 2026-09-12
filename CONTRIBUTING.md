# Contributing to Fin·QA

Thanks for taking a look. This is a personal/portfolio project, not a company codebase,
but PRs, issues, and forks are welcome.

## Setup

Follow [README.md's "Getting started"](README.md#getting-started) for install and
building a local dataset — that's the canonical version of these steps, not repeated
here. The short version:

```bash
python -m venv venv && source venv/bin/activate   # or venv\Scripts\activate on Windows
pip install -e ".[anthropic,api,observability]"
python -m finqa_v2.dataset.build            # builds the local dataset (needs network)
python -m finqa_v2.retrieval.build_indexes  # BM25 + embedding indexes
```

For frontend work: `cd dashboard_v2 && npm install`.

## Running the checks before you open a PR

```bash
python -m unittest discover -s finqa_v2
python -m unittest discover -s evaluation
cd dashboard_v2 && npm run lint && npm run build
```

[`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs the same three (plus a
regression-gate check against a small committed fixture) on every push/PR — a red CI run
means one of these didn't pass locally either.

Tests that need the full real dataset, a live LLM key, or Postgres skip themselves
automatically (`unittest.skipUnless`) when those aren't available, so a clean run without
any of that set up is still meaningful, not a false pass.

## Design invariants a change shouldn't break

These are the actual point of the project (see README's "Design principles" for the full
list) — a PR that violates one of these needs a strong reason, not just a passing test:

- **The LLM never computes or invents a number.** All arithmetic goes through the
  deterministic Financial Engine (`finqa_v2/engine/`); an LLM only narrates numbers that
  engine already produced.
- **A metric that isn't cleanly available returns `null` with a stated reason** — never
  `0`, never a substitute period/basis silently swapped in.
- **Every claim traces to a specific evidence id.** If you add a new answer path, it
  needs to go through the Evidence Workspace / Claim Graph (`finqa_v2/evidence/`), not
  bypass it.
- **Verification runs independently after synthesis** (`finqa_v2/verification/`) and
  doesn't trust the synthesizer's own arithmetic or citations — don't special-case around
  it for a new answer type.

## Where things live

`README.md` is the pitch and quick start. [`MANUAL.md`](MANUAL.md) is the full technical
reference — every module, config variable, the API/metrics reference, deployment, and
known limitations. Read the relevant `MANUAL.md` section before touching a subsystem you
haven't worked in yet; it explains *why* things are shaped the way they are, which the
code alone often doesn't.

## Scope note

`archive/` is a frozen, earlier iteration of this project, kept as a runnable reference —
it isn't part of the live system and isn't where new work should go (see the root
README's "two systems live in this repo" note).

## License

MIT — see [`LICENSE`](LICENSE). By contributing, you agree your changes are licensed
under the same terms.
