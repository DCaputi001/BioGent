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

---

## Where design decisions live

Before proposing a change that touches architecture (data layer, LLM cost model, frontend stack, service boundaries, etc.), check `ARCHITECTURE.md` first — many of these are already decided with reasoning documented, not open questions. `PRODUCTION_PLAN.md` has the phased build order and current status.

---

## For AI coding agents

See `AGENTS.md` for repo orientation specifically written for AI agents (Claude Code, etc.) working in this codebase.