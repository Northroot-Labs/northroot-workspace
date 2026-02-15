# Workspace scope

**Scoped context (runtime):** Defined in **WORKSPACE_SCOPE.md** at the workspace root. That file is editor-agnostic and is the single source of truth for "what's in scope right now." Agents and tools read it at session start.

**To change scope (runtime-enforced):** Run `./northroot-workspaces/enter.sh <mode> [--sync]`. Modes and topology live in **repos/docs/internal/workspace/** (modes.yaml, topology.yaml). See **northroot-workspaces/README.md**.

## Modes (summary)

| Mode        | Use when |
|------------|----------|
| narrow     | Hyena + docs (minimal surface). default_working_set: docs, hyena-rs. |
| clearlyops | ClearlyOps control plane, CI, infra; docs for policy. |
| broad      | All currently cloned repos; cross-repo work. |
| full       | Full org; clone/sync everything in repos.yaml. |

## Widen / add repos

Add repo names to `default_working_set` in `repos.yaml`, then run `./scripts/clone-default.sh` and `./scripts/sync.sh`. Add a corresponding mode in `repos/docs/internal/workspace/modes.yaml` if you want a dedicated scope. Full list of org repos is in `repos.yaml`; source of truth is `gh repo list Northroot-Labs`.
