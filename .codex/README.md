# Codex migration

This directory contains the reusable configuration migrated from `.claude/`.

- `skills/` is a direct, portable copy of the Claude skills. References to `CLAUDE.md` and
  `.claude/...` have been updated to `AGENTS.md` and `.codex/...`.
- `agents/` preserves the former role prompts as reference playbooks. Codex does not automatically
  register Claude-style agent frontmatter, so use the appropriate playbook when delegating work.
- `AGENTS.md` at the repository root is the Codex instruction file.

The Claude permission allow-list was intentionally not migrated: Codex permissions are determined
by the active environment and user approvals. `.claude/worktrees/` was also intentionally omitted
because it is generated runtime state rather than reusable project configuration.

`.claude/` is retained unchanged so both tools can be used with the same repository.
