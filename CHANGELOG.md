# Changelog

## Unreleased

- `wikiloop gardener` gives the re-verify session every commit, across all API pages; a
  source it could not read keeps the old `last-verified`.
- `wikiloop lint` checks every tracked file for secrets, with one scanner shared with
  `report-session`: GitHub fine-grained, Google, GitLab and model API tokens, quoted JSON
  fields, PKCS#8 keys. `lint.secret_patterns` adds a company's own token shapes.
- `report-session` redacts the note with the complaint as well as the transcript, and
  removes a private key whole instead of its header line.

## 0.1.0 — 2026-10-29

First release.

- `wikiloop build`: compiles `wikiloop.toml`, guide overrides and the core templates into a
  Claude Code plugin: manifests, hooks, the `wiki-*` skills, the shepherd, CONTRIBUTING.md,
  AGENTS.md, INDEX.md.
- Hooks: the session rule, the Stop hook that asks for a candidate after an investigation, and
  the gate on raw candidate filing; all read the resolved config.
- `wikiloop candidate`: search, file and comment through an inbox adapter (GitHub), with the
  gate checked before anything is sent and a local fallback when the tracker is out of reach.
- `wikiloop lint`, `check`, `inbox`, `pr-lines`, `shepherd`, `apply`, `evals`, `gardener`,
  `report-session`, `session-summary`, `update`, `init`.
- Guides in sections; a wiki overrides one section at a time, and the build warns when the
  core changes a section under an override.
- On-call: the engine, sources, and the Claude Code status line and pane, off by default.
- Claude Code and Codex: the hooks count investigation from hook events (PostToolUse,
  UserPromptSubmit) instead of the transcript, so the same scripts run under both; the build
  writes a Codex manifest and hooks file beside Claude Code's, and an `install.sh` for both.
- Generated skills are split by audience: plugin skills for every session, maintainer skills in
  the wiki repo's `.claude/skills/`.
