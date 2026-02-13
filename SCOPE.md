# Workspace scope

**Current focal point:** **Hyena** (hyena-rs + org convention in docs).

## Narrow (current)

- **default_working_set** in `repos.yaml`: `docs`, `hyena-rs`
- **docs** — Org canon: Hyena convention, agentic bounds, DATE_STANDARD, TESTING_STANDARD, research, model-choice.
- **hyena-rs** — Implementation: Hyena CLI; sole scope for making Hyena useful.

To sync only this set: `./scripts/clone-default.sh` then `./scripts/sync.sh`.

## Widen

Add repo names to `default_working_set` in `repos.yaml`, then run `./scripts/clone-default.sh` (for new clones) and `./scripts/sync.sh`. Full list of org repos is under `repos:` in `repos.yaml`; source of truth is `gh repo list Northroot-Labs`.

## Summary

| Scope   | default_working_set   | Use when                          |
|---------|------------------------|------------------------------------|
| Narrow  | docs, hyena-rs         | Hyena-focused work (current)      |
| Wider   | Add orchard-core, etc. | Cross-repo or product work        |
