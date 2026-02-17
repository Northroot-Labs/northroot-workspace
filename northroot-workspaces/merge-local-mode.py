#!/usr/bin/env python3
"""Update or add a single mode in modes.local.yaml (workspace root).
Reads existing file if present; replaces one mode block; writes back.
Usage: merge-local-mode.py <path-to-modes.local.yaml> <mode> <path1> [path2 ...] --repos r1 [r2 ...]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


def main() -> int:
    args = list(sys.argv[1:])
    if len(args) < 4 or "--repos" not in args:
        print(
            "Usage: merge-local-mode.py <modes.local.yaml> <mode> <path1> [path2 ...] --repos r1 [r2 ...]",
            file=sys.stderr,
        )
        return 1
    yaml_path = Path(args.pop(0))
    mode_name = args.pop(0)
    paths = []
    while args and args[0] != "--repos":
        paths.append(args.pop(0))
    args.pop(0)  # --repos
    repos = list(args)

    # Build new mode block
    block_lines = [
        f"  {mode_name}:",
        '    focus: "(local override)"',
        "    in_scope_paths:",
    ]
    for p in paths:
        block_lines.append(f'      - "{p}"')
    block_lines.append("    repos:")
    for r in repos:
        block_lines.append(f"      - {r}")
    new_block = "\n".join(block_lines)

    # Parse existing: find mode blocks (  name: ... until next   name: or EOF)
    existing = ""
    if yaml_path.exists():
        existing = yaml_path.read_text()

    header = "# Local mode overrides (gitignored). Promoted with: enter.sh <mode> --local\n# Same structure as repos/docs/internal/workspace/modes.yaml\n\nmodes:\n"
    other_blocks = []
    if existing:
        # Split into blocks: lines starting with "  word:" (exactly two spaces)
        block_start = re.compile(r"^  ([a-z][a-z0-9_-]*):\s*$")
        current = []
        in_other = False
        for line in existing.splitlines():
            m = block_start.match(line)
            if m:
                if current and in_other:
                    other_blocks.append("\n".join(current))
                in_other = m.group(1) != mode_name
                current = [line]
            elif current:
                current.append(line)
        if current and in_other:
            other_blocks.append("\n".join(current))

    out = header + new_block + "\n"
    if other_blocks:
        out += "\n".join(other_blocks) + "\n"
    yaml_path.parent.mkdir(parents=True, exist_ok=True)
    yaml_path.write_text(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
