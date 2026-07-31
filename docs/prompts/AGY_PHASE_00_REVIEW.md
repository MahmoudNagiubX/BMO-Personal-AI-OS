# First AGY Prompt — Independent Phase 0 Review

Copy the prompt below into AGY CLI from the repository root after Codex finishes.

---

Perform a **read-only independent review** of Personal AI OS Phase 0.

Read:

1. `AGENTS.md`
2. `docs/IMPLEMENTATION_STATUS.md`
3. `docs/phases/PHASE_00_BOOTSTRAP.md`
4. Relevant sections of `docs/MASTER_PLAN.md`
5. All accepted ADRs
6. The complete current diff and Phase 0 report

Do not modify files or run destructive commands.

Review for:

- contradictions between bootstrap files and the master plan;
- missing agent guardrails;
- accidental later-phase work;
- unsafe environment examples or network defaults;
- secret/personal-data leak paths;
- non-reproducible bootstrap or CI behavior;
- weak test coverage of governance rules;
- invalid Python, YAML, TOML, shell, or PowerShell configuration;
- incorrect OpenJarvis baseline references;
- missing rollback or status evidence.

You may run safe read-only validation commands after requesting approval. Classify each finding as Blocker, High, Medium, or Low. Include the exact file and line, evidence, impact, and smallest recommended fix.

End with one verdict:

- ACCEPT PHASE 0 LOCALLY
- ACCEPT WITH RECORDED MEDIUM/LOW FOLLOW-UPS
- REJECT UNTIL BLOCKER/HIGH FINDINGS ARE FIXED

Do not implement fixes.

---
