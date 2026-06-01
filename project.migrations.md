# Project Migrations

This ledger records version-to-version changes for AWC installations.
Legacy versions may appear in the `vN` format; the current baseline uses
SemVer.

## How to use

1. Read `awc.meta.toon` and identify the installed version.
2. Open this ledger and find the next applicable migration row.
3. Apply the listed change set.
4. Re-read `awc.meta.toon` and continue until the installed version matches the
   convention version.
5. Use SemVer ordering from the current baseline onward.

## Migration ledger

| From | To | Purpose | Files to review | Main action | Notes |
|------|----|---------|-----------------|-------------|-------|
| v4 | 0.0.1 | align the installed Assistant-OS convention with the current AWC baseline | `AGENTS.md`, `project.overview.md`, `project.update.md`, `project.migrations.md`, `agent-start-here.md`, `README.md`, `awc.meta.toon`, `agent/`, `docs/`, `.obsidian/graph.json`, `.gitignore` | add repo-local update routing, agent overview, migration ledger, and overview-based internal indexes | keep the human root `README.md`; use `overview.md` for internal indexes |

## Update pattern

- use one row at a time;
- do not skip a version if the local installation still depends on it;
- if a project already matches a row, continue to the next one;
- ask for approval before moving, deleting, or consolidating structural files.

## Related

- [project.update.md](project.update.md)
- [project.overview.md](project.overview.md)
- [AGENTS.md](AGENTS.md)
