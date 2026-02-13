# Northroot-Labs org workspace

**Source of truth:** GitHub org [Northroot-Labs](https://github.com/Northroot-Labs). This directory is the formal local workspace for org-wide work and agent-driven workflows.

## Layout

| Path | Purpose |
|------|--------|
| `repos/` | Local clones of org repos. One dir per repo (e.g. `repos/docs`, `repos/orchard-data`). |
| `repos.yaml` | Manifest: default working set and repo list. Align with `gh repo list Northroot-Labs`. |
| `scripts/` | Reproducible workflows: list, clone default set, sync (pull). |
| `WORKSPACE.md` | This file. |
| `.cursorrules` | Agent instructions for working across repos in this workspace. |

## Workflows

- **List org repos and local status**  
  `./scripts/list-repos.sh`  
  Shows GitHub repo list and, for each clone in `repos/`, branch and short status.

- **Clone default working set**  
  `./scripts/clone-default.sh`  
  Clones the repos listed under `default_working_set` in `repos.yaml` into `repos/`. Idempotent (skips existing).

- **Sync local mirror with GitHub**  
  `./scripts/sync.sh`  
  `git fetch --prune` and `git pull` in every repo under `repos/`. If `repos/` is empty, runs `clone-default.sh` first.

Run from this directory, or set `NORTHROOT_WORKSPACE` to this path.

## Opening in Cursor

Open this folder as the workspace root: **File → Open Folder → `Northroot-Labs`**.  
All repos under `repos/` are then in the same workspace; agents can read and edit any of them. Before a session, run `./scripts/sync.sh` so the mirror is up to date.

## Adding or changing repos

- **Add a repo to the default working set:** Edit `default_working_set` in `repos.yaml`, then run `./scripts/clone-default.sh`.
- **Clone a repo not in the default set:**  
  `gh repo clone Northroot-Labs/<repo> repos/<repo>`  
  or add it to `default_working_set` and run `clone-default.sh`.
- **Refresh manifest from GitHub:**  
  `gh repo list Northroot-Labs --limit 100`  
  Update `repos` in `repos.yaml` if you track descriptions.
