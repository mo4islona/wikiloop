# Contributing

{{guide:contribute}}

## 12. How the loop runs

The wiki learns from the sessions that use it, through the {{wiki.plugin}} plugin:

- At session start a hook tells the agent: load the skill before you reason about a system it
  maps, and put what you learn into the wiki or a candidate, never into private memory.
- After an investigation, once the user has replied, a hook asks the agent once to file what
  it found as a candidate in `{{inbox.repo}}` (label `{{inbox.label}}`), or to say
  `wiki: nothing new`. It counts {{investigation.threshold}} investigation steps first and asks
  again only after {{investigation.reask}} more.
- A candidate without the gate lines ({{gate.keys}}) is refused before it is filed.
- `wiki-triage` and `wiki-shepherd` (maintainer skills in `.claude/skills/`) turn candidates into PRs, review them and
  merge what passes; a person answers what carries `needs-human`.
- `wikiloop gardener` lists skills whose sources changed since `last-verified`; trigger evals
  in `evals/` check that descriptions still catch how people ask.

The mechanics are in the wikiloop core ({{core.path}}, version {{core.version}}): `DESIGN.md`
explains why each step is shaped the way it is, `docs/config.md` lists every setting.
