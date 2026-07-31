# Codex and AGY CLI Workflow

## Purpose

Use coding agents as controlled contributors, not as a single unrestricted builder. The repository documents are the authority.

## Roles

### Codex — implementation owner

Use Codex for bounded code changes, tests, refactors, debugging, migrations, and implementation reports.

### AGY CLI — independent reviewer and research partner

Use AGY for architecture review, documentation research, test-gap analysis, threat review, and independent validation. AGY may implement a separate task only when file ownership is explicitly separated.

## Required session sequence

1. Start from a clean working tree.
2. Create or switch to the approved phase branch.
3. Give the agent the exact prompt under `docs/prompts/`.
4. Require it to read `AGENTS.md`, status, phase contract, relevant master-plan sections, and ADRs.
5. Review its plan before broad edits.
6. Review every artifact/diff.
7. Approve terminal commands individually until the workflow is trusted.
8. Run targeted tests while iterating.
9. Run `uv run python scripts/check.py` before completion.
10. Ask AGY for a read-only independent review.
11. Fix verified findings with Codex.
12. Commit only after the owner reviews the final diff and evidence.

## Permission defaults

### Codex

- Begin in review/approval mode.
- Permit writes only inside the repository.
- Do not permit network access unless needed for dependency resolution or official documentation.
- Do not permit destructive Git operations.
- Do not permit access to home-directory credentials or unrelated projects.

### AGY CLI

- Use `/permissions` and select `request-review` or `strict` for early phases.
- Enable the terminal sandbox in AGY settings.
- Use `/diff` to inspect changes.
- Keep AGY read-only for review prompts unless a separate implementation task is assigned.
- Do not use `always-proceed` for security, infrastructure, device, authentication, approval, backup, or migration work.

## File ownership

- Never let Codex and AGY edit the same files concurrently.
- The implementation agent owns the files listed in its task.
- The reviewer reports findings without editing.
- A second implementation task must use a separate branch or non-overlapping directory.

## Prompt format

Every task prompt should contain:

- Current phase and task ID.
- Goal.
- Allowed files/directories.
- Explicitly forbidden scope.
- Relevant master-plan sections and ADRs.
- Acceptance criteria.
- Required commands.
- Expected completion report.

## Review severity

- **Blocker:** secret leak, architecture contradiction, unsafe permission, data loss, public exposure, or later-phase work.
- **High:** broken acceptance criterion, missing security test, direct framework coupling, or unreliable recovery.
- **Medium:** maintainability, missing edge case, or incomplete documentation.
- **Low:** optional cleanup that does not justify expanding scope.

Only blocker/high findings prevent task acceptance. Medium findings should be fixed when local to the task or recorded. Low findings should not cause scope creep.

## Handoff record

At task completion, save:

- implementation summary;
- changed-file list;
- commands and results;
- reviewer findings and dispositions;
- commit SHA after commit;
- next authorized task.

Store phase-level evidence in `docs/phase_reports/`.
