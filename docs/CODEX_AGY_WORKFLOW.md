# Coding Agent Workflow — AGY CLI and Codex

## Purpose

Use coding agents as controlled, permission-bounded contributors. AGY CLI is the default implementation agent for normal bounded tasks. Codex is the escalation agent for major architectural, security-sensitive, complex debugging, and cross-cutting implementation tasks. The repository documents remain the authority.

## Roles

### AGY CLI — default implementation agent

AGY CLI is the default agent for:

- normal bounded implementation tasks
- documentation
- repository maintenance
- test implementation
- small and medium bug fixes
- configuration changes
- infrastructure scripts
- runbooks
- phase reports
- local validation
- structured refactoring within one approved boundary
- creating the requested commit after all checks pass

### Codex — escalation and major-work agent

Codex is used when:

- a blocker or high-severity issue exists
- authentication or authorization is affected
- device identity or credential handling is affected
- permissions or approvals are affected
- secrets, encryption, or security boundaries are affected
- a database migration or rollback strategy is required
- concurrency or distributed-state logic is involved
- streaming or process lifecycle behavior is involved
- a framework compatibility problem changes an adapter contract
- a major architectural feature is being implemented
- a major refactor is required
- the root cause is uncertain
- AGY has attempted two narrow fixes and the same failure remains
- the change could cause data loss, public exposure, or weakened safety

Codex receives a narrow escalation handoff and must not widen the task scope.

### Independent reviewer

Every accepted implementation task must receive an independent review before phase acceptance:

- AGY reviewing Codex work
- Codex reviewing AGY work
- another explicitly assigned read-only reviewer

The reviewer reports findings without editing the same files concurrently.

Findings classification:

- **Blocker:** secret leak, architecture contradiction, unsafe permission, data loss, public exposure, or later-phase work.
- **High:** broken acceptance criterion, missing security test, direct framework coupling, or unreliable recovery.
- **Medium:** maintainability, missing edge case, or incomplete documentation.
- **Low:** optional cleanup that does not justify expanding scope.

Blocker and High findings prevent task acceptance. Medium findings should be fixed when local to the task or recorded. Low findings must not cause scope expansion.

### Mahmoud — owner and approval authority

Mahmoud is sole authority for:

- authorizing phases and exact next tasks
- approving privileged or destructive commands
- reviewing final diffs
- deciding whether to push to GitHub or merge pull requests
- accepting security and privacy impact
- approving architecture changes or new dependencies

## Agent Escalation Rule and Handoff Template

AGY must stop instead of improvising when:

- authorization is missing
- a task crosses a forbidden phase boundary
- a blocker or high-severity issue is discovered
- security implications are uncertain
- required data may be lost
- public exposure may be introduced
- a migration cannot be safely rolled back
- a framework adapter contract must change
- the root cause remains unclear after investigation
- two narrow repair attempts fail

When stopping, AGY must output the exact escalation handoff template:

```text
## Codex Escalation Handoff

Task ID:
Current branch:
Current commit:
Goal:
Observed failure:
Reproduction commands:
Exit codes:
Expected behavior:
Actual behavior:
Relevant files:
Current diff:
Security/data impact:
Attempts already made:
Constraints:
Recommended narrow next action:
Required commit message:
```

## Required Task Sequence

1. Confirm the approved branch.
2. Confirm the working tree state is clean.
3. Read `AGENTS.md`.
4. Read `docs/MASTER_PLAN.md`.
5. Read `docs/IMPLEMENTATION_STATUS.md`.
6. Read the active phase contract.
7. Read relevant ADRs and security/privacy documents.
8. Inspect the current code and tests before editing.
9. Present a concise implementation plan.
10. Implement only the approved task.
11. Run targeted tests during development.
12. Run full phase checks before completion (`uv run python scripts/check.py`, pre-commit).
13. Update documentation and status only with verified facts.
14. Inspect the complete diff.
15. Stage only intended files using explicit file paths.
16. Commit using the task's exact commit message.
17. Stop before starting the next task.
18. Do not push unless explicitly authorized.
19. Obtain an independent review before phase acceptance.

## File Ownership and Concurrency

- AGY and Codex must never edit the same files at the same time.
- One implementation agent owns the files listed in the current task prompt.
- Reviewers remain strictly read-only.
- A separate implementation task must use a separate branch or non-overlapping files and directories.
- An agent must stop if unexpected concurrent changes appear.
- An agent must not overwrite changes it did not create or understand.

## Permission Defaults

### AGY CLI

- Use `request-review` or `strict` mode.
- Enable the terminal sandbox.
- Repository-only file access; no unrestricted access to the home directory.
- No automatic approval for sudo or destructive commands.
- No automatic network access unless explicitly required.
- No `always-proceed` mode for security, infrastructure, identity, databases, migrations, backups, or device control.

### Codex

- Begin in review/approval mode.
- Repository-only write access; no access to unrelated projects or home-directory credentials.
- Network access only for dependency resolution or official documentation when approved.
- No destructive Git operations.
- No push unless explicitly authorized.

## Git and Commit Rules

- **Branch naming:** `phase-XX/short-description`
- **Commit format:** `<type>(phase-XX): <clear imperative summary>`
- **Allowed commit types:** `chore`, `docs`, `feat`, `fix`, `test`, `security`, `infra`, `ops`, `perf`, `refactor`, `ui`, `release`.

Agents must not:

- commit directly to `main`
- use `git add .` or `git add -A` when files outside task scope may exist
- force-push, amend, rebase, reset, or delete branches
- merge pull requests or rewrite history
- silently revert user changes
- push unless the task explicitly allows it

## Standard Completion Report

Every implementation response must include:

- Scope completed.
- Files changed.
- Commands run and actual outcomes.
- Tests added or changed.
- Security/data impact.
- Remaining blockers or follow-up within the same phase.
- Confirmation that no later phase was started.
