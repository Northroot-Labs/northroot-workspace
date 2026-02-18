# Northroot workspaces — org-wide entrypoint

**Purpose:** Single entrypoint for workspace scope and safe hopping. Runtime-enforced modes; not dependent on remembering to sync or local-only state.

## Quick start

```bash
# From workspace root (Northroot-Labs)
./northroot-workspaces/enter.sh <mode> [--sync]
```

- **Modes:** `narrow` | `clearlyops` | `broad` | `full` (defined in `repos/docs/internal/workspace/modes.yaml`).
- **`--sync`:** Before setting scope, pull remotes for repos in that mode (and clone if missing for narrow/clearlyops).

## How it works

1. **Metadata** lives in **repos/docs/internal/workspace/** (topology + modes). That repo is the source of truth for boundaries and scope; clone/sync docs first if missing.
2. **enter.sh** reads the chosen mode, optionally syncs the relevant repos, and writes **WORKSPACE_SCOPE.md** and **scope.json** (machine-readable) at workspace root. Agents and tools read those to stay in scope.
3. **Safe hopping:** Run `enter.sh` with another mode anytime. No reliance on local-only edits or manual sync memory.
4. **Local ↔ remote alignment:** `repos/docs` is the canonical local copy of **Northroot-Labs/docs**. Sync (pull) before work, push from `repos/docs` when done so org topology and docs don’t drift. See `repos/docs/internal/workspace/LOCAL_REMOTE_TOPOLOGY.md`.

## Hard enforcement (exec.sh)

To **enforce** scope (fail closed for out-of-scope paths), run commands via:

```bash
./northroot-workspaces/exec.sh [--] <command> [args...]
```

- **Requires:** Scope must be set (`enter.sh <mode>`); **scope.json** must exist.
- **Checks:** Cwd must be under an in-scope path; any path-like args (e.g. `-C <path>`, `repos/...`) are validated. If any path is out of scope, the script exits 1 and does not run the command.
- **Use when:** CI, scripts, or any runner where scope must be enforced rather than best-effort. Editors/agents can still use WORKSPACE_SCOPE.md for advisory scope; exec.sh is for strict enforcement.

## Baseline policy (annotated tags)

Org-wide pinned baselines are machine-truth in:

- `northroot-workspaces/baselines/registry.json`

Verification tooling:

```bash
./northroot-workspaces/baseline.sh schema
./northroot-workspaces/baseline.sh verify-tags
./northroot-workspaces/baseline.sh check-publish --repo Northroot-Labs/clearlyops --branch main --head HEAD
```

- **Tag integrity:** baseline pins are tag+sha, and tags must be **annotated tags**.
- **Publish gate:** protected branches (`main`, `release/*`) must descend from the repo's required bucket pin (default `checkpoint`).
- **Offline-first:** local development can proceed with local state; collaboration edges (push/CI) run online verification.
- **Local hook template:** `northroot-workspaces/hooks/pre-push.sample`

## Optional auth bootstrap (non-default)

For first-time setup of local signing/session workflow, run explicitly:

```bash
./northroot-workspaces/setup-auth.sh status
./northroot-workspaces/setup-auth.sh bootstrap --workspace-dir "$HOME/Northroot-Labs"
./northroot-workspaces/setup-auth.sh login --workspace-dir "$HOME/Northroot-Labs"
```

- `bootstrap-signing.sh` no longer edits global `~/.gitconfig` unless `--install-global-include` is passed.
- `checkpoint-promote.sh` performs online freshness checks (`fetch --prune --tags`) by default and tags `origin/main` unless overridden with `--target-ref`.

## Signing bootstrap (optional)

Bootstrap workspace-scoped SSH signing (one-time per user/machine, non-default):

```bash
chmod 700 ./northroot-workspaces/bootstrap-signing.sh ./northroot-workspaces/workspace-login.sh ./northroot-workspaces/brokered-tag.sh
./northroot-workspaces/bootstrap-signing.sh --workspace-dir "$HOME/Northroot-Labs"
```

Unlock key and mint workspace session (per login/session):

```bash
./northroot-workspaces/workspace-login.sh --workspace-dir "$HOME/Northroot-Labs" --ttl-hours 8 --session-ttl-hours 8
```

Create signed annotated checkpoint tag with brokered metadata:

```bash
./northroot-workspaces/brokered-tag.sh \
  --tag checkpoint/2026-02-15-main \
  --scope "origin/main checkpoint" \
  --run-id nr-20260215-001 \
  --delegated-by your-user-id \
  --mode human-cosign \
  --co-signed-by "owner@example.com" \
  --title "Checkpoint before release checks"
```

Or perform tag + registry pin + verification in one step:

```bash
./northroot-workspaces/checkpoint-promote.sh \
  --repo Northroot-Labs/hyena-rs \
  --tag checkpoint/2026-02-15-main \
  --run-id nr-20260215-001 \
  --delegated-by your-user-id \
  --mode human-cosign \
  --co-signed-by "owner@example.com" \
  --bucket checkpoint
```

## Local mode overrides

Local overrides live in **modes.local.yaml** at workspace root (gitignored). To add or update a mode without editing `repos/docs`:

```bash
./northroot-workspaces/merge-local-mode.py modes.local.yaml <mode> <path1> [path2 ...] --repos <r1> [r2 ...]
```

Example: `./northroot-workspaces/merge-local-mode.py modes.local.yaml clearlyops repos/docs repos/clearlyops --repos docs clearlyops`. Promoted to canonical modes via `enter.sh <mode> --local` (when implemented) or by copying into `repos/docs/internal/workspace/modes.yaml`.

## Modes (summary)

| Mode        | Focus |
|------------|--------|
| narrow     | Hyena + docs (minimal surface). |
| clearlyops | ClearlyOps control plane, CI, infra; docs for policy. |
| broad      | All currently cloned repos. |
| full       | Full org (clone/sync everything in repos.yaml). |

## Topology and LLM context

- **Topology:** `repos/docs/internal/workspace/topology.yaml` defines repo boundaries and optional `llms_txt` paths per repo for fast traversal and searchability.
- **llms.txt:** Use where it fits (repo root or key dirs). Raw context; other structured files (e.g. NOTES.md, policy YAML) can be used instead when they fit the context. See metadata README.

## Reproducible setup

- List/sync/clone: use **scripts/** at workspace root (`list-repos.sh`, `sync.sh`, `clone-default.sh`).
- To ensure a mode’s repos exist: add them to `default_working_set` in **repos.yaml**, run `./scripts/clone-default.sh`, then `./northroot-workspaces/enter.sh <mode> --sync`.
