# AGENTS.md

This file is for agents working in Assistant-OS as an installed project.

You are not in the convention source repository. You are in a target project
that already carries convention files locally. Treat the local files in this
repository as the source of truth for this workspace.

The short convention alias is `awc`, short for `agent-workspace-convention`.

Version control metadata lives in `awc.meta.toon` at the repository root.

## Goal

Provide a simple and stable base so agents can:

- find the conceptual entry point;
- separate contract from progress;
- keep human documentation truthful;
- use an operational workspace without polluting the repository;
- continue work across sessions;
- update the convention in a repeatable way.

## Recommended structure

The convention lives locally in this repository and uses these root-level
entry files:

- `README.md` for humans;
- `project.overview.md` for the agent-facing conceptual map;
- `project.update.md` for update routing;
- `project.migrations.md` for version-by-version updates;
- `agent-start-here.md` for the operational entry point;
- `agent/overview.md`;
- `agent/policy/overview.md`;
- `agent/specs/overview.md`;
- `docs/overview.md`;
- `docs/contracts/overview.md`;
- `docs/policies/overview.md`;
- `docs/reports/overview.md`;
- `docs/plans/overview.md`;
- `docs/guides/overview.md`;
- `docs/decisions/overview.md`;
- `docs/concepts/overview.md`;
- `docs/legacy/overview.md`;
- `.gitignore`;
- `agent/policy/`;
- `agent/specs/`;
- `agent/tmp/.gitkeep`;
- `agent/prints/.gitkeep`;
- `agent/reports/.gitkeep`;
- `agent/scripts/.gitkeep`;
- `agent/test/.gitkeep`;
- `agent/note/.gitkeep`.

When the repository is also used as an Obsidian vault, the recommended graph
profile lives in `.obsidian/graph.json`.

## Local update flow

When the agent receives the update prompt from `README.md`, it should follow
this route:

1. open this `AGENTS.md`;
2. open `project.update.md`;
3. compare the installed convention with `awc.meta.toon`;
4. open `project.migrations.md` and apply the next unapplied row;
5. open `project.overview.md`;
6. open `agent-start-here.md`;
7. follow the phased adequation protocol described in this file and in
   `agent/policy/adequation.policy.md`;
8. ask for approval before organizing, deleting, moving, or consolidating
   structural changes;
9. record relevant progress in `trace_id` and the corresponding `.stat`.

## Safe bootstrap

When applying the convention to another workspace, copy only the conventional
files that belong to the installation and do not copy any repository metadata
that would turn the convention source into a nested dependency.

If the destination already has its own `.gitignore`, merge useful rules instead
of deleting existing project-specific ignores.

## Post-bootstrap: initial adequation

After the bootstrap, the agent should read `agent-start-here.md`, inventory
noise and loose files, classify each item, and ask for approval before
structural changes. Record approved progress in the matching `.stat`.

## Working pattern

1. read `project.overview.md`;
2. read `project.update.md` when the local installation may diverge;
3. read `project.migrations.md` when the change spans versions;
4. read `agent-start-here.md`;
5. read the relevant `.spec`;
6. read the corresponding `.stat`;
7. validate the impact;
8. update progress;
9. update official documentation only if behavior or contract changes;
10. leave the workspace clean.

## Adequation protocol

1. bootstrap the convention;
2. adjust `graph.json` and `.gitignore` for known local noise;
3. inventory artifacts, loose files, and temporary files;
4. ask for approval before organizing or deleting;
5. organize the repository;
6. map documentation that needs to become context, `.spec`, or `.stat`;
7. ask for approval before creating or adjusting contracts;
8. perform linking and consolidation;
9. update `.stat` with the real progress;
10. use `trace_id` to record the relevant change.

## Detailed policy

The full rules live in `agent/policy/`.

This bootstrap only defines the map and the expected use.
