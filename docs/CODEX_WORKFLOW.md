# Codex Workflow

## Operating model

Codex is the default repository implementation specialist. An independent
reviewer is read-only and separate from implementation. Mahmoud is the sole
authority for phase approval, architecture decisions, destructive actions, and
pull-request merges.

## Before editing

1. Confirm the approved branch and working-tree scope.
2. Read `AGENTS.md`, `docs/IMPLEMENTATION_STATUS.md`, the active task
   specification, relevant sections of `docs/MASTER_PLAN.md`, and relevant
   accepted or superseding ADRs.
3. Inspect the affected code, tests, and current repository state.

## Implementation boundaries

- Stay inside the approved task and phase boundary; do not begin a later phase.
- Use bounded permissions and keep side effects explicit.
- Do not weaken security, privacy, approval, testing, or governance controls.
- Do not expose internal services publicly or add required paid/cloud services.
- Consequential or destructive operations require explicit owner approval.
- Never merge a pull request, amend, rebase, force-push, reset published
  history, delete branches, or rewrite history.

## Validation and publication

- Run targeted tests while iterating and the complete required validation suite
  before completion.
- Inspect the complete diff and stage only intended files.
- Push and open a pull request only when the task explicitly authorizes it.
- Independent review is required before Mahmoud may merge a pull request.

## Completion report

Report scope, changed files, commands and actual outcomes, tests added or
changed, security/data impact, remaining blockers or same-phase follow-up, and
confirmation that no later phase was started.
