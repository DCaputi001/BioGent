# Contributing to BioGent

Process notes for working in this repo — written down even for an audience of one, per the reasoning in `ARCHITECTURE.md` (Development & Deployment Workflow).

---

## Branching model

- **`main` is always deployable.** Every commit on it should be something that could ship.
- **All work happens on feature branches**, merged back via pull request — even solo. This is what makes CI meaningful: checks run *on the PR*, before anything touches `main`, not after.
- Branch naming: `feature/short-description` for new work, `fix/short-description` for bug fixes. Examples already in use: `feature/repo-scaffolding`, `feature/gitignore-and-readme`.

### Standard workflow for any change

```powershell
git checkout main
git pull
git checkout -b feature/whatever-this-is
# ...make changes...
git add .
git commit -m "Clear description of what changed"
git push -u origin feature/whatever-this-is
```
Then open a pull request on GitHub, review the diff, and merge.

### Multi-machine workflow (PC + laptop)

- **Push before switching machines. Pull before starting work.**
- Don't leave uncommitted work stranded on one machine — commit (even a rough WIP commit on a feature branch) or stash before switching.
- Folders with no tracked files inside them (nothing committed yet) will **not** survive a fresh `git clone` on another machine — git doesn't track empty directories. If a new service/module directory is created but empty, add a `.gitkeep` placeholder file so it's tracked until real content exists.

---

## Commit messages

Short, plain-English description of what changed and why, if not obvious. No strict format enforced yet — clarity over ceremony at this stage.

---

## Pull requests

- Every PR should have a diff worth reviewing — an empty diff (branch identical to `main`) means there's nothing to merge; check `git log` / `git status` before opening one.
- CI (GitHub Actions) runs automatically on every PR — see `.github/workflows/`. A PR shouldn't be merged with a failing check.
- Squash or regular merge is fine at this stage; no strict policy yet.
- **A PR that modifies files under `tests/` deserves extra scrutiny before merging** — especially if it's the *only* thing that changed (no corresponding implementation change). See "Protecting tests" below for why this matters more once AI coding agents are doing real implementation work here.

---

## Protecting tests from being silently weakened

Once AI agents (Claude Code, etc.) are doing real implementation work in this repo, a real failure mode to guard against: an agent hits a failing test, and instead of fixing the underlying code, "fixes" the test instead — loosens an assertion, deletes a case, or changes an expected value to match new (possibly buggy) behavior. This isn't unique to AI agents (people do this too, under deadline pressure), but it's worth having real mechanisms in place, not just a documented rule (`AGENTS.md` states the rule directly; this section is about backing it with something that isn't just a request).

**What's set up so far:**
- The explicit "don't" rule in `AGENTS.md`'s don't-list, stated as a hard rule with reasoning, not a soft suggestion.
- Tests are structural and check observable behavior (e.g. "the chunks cover the whole input" rather than "line 47 does X"), which makes them harder to game with a superficial edit without it being obvious in review.

**Worth setting up once the repo has more real history/contributors (not blocking right now):**
- GitHub branch protection rule requiring review before merge to `main`, specifically so a PR that touches `tests/` can't be self-merged without a second look.
- A CI check that flags (or blocks) a PR touching only test files with no accompanying source change — a strong signal of exactly the pattern this section is guarding against.

---

## Where design decisions live

Before proposing a change that touches architecture (data layer, LLM cost model, frontend stack, service boundaries, etc.), check `ARCHITECTURE.md` first — many of these are already decided with reasoning documented, not open questions. `PRODUCTION_PLAN.md` has the phased build order and current status.

---

## For AI coding agents

See `AGENTS.md` for repo orientation specifically written for AI agents (Claude Code, etc.) working in this codebase.