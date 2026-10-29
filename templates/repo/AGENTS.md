# For agents opening this repo directly

This repo is a set of skills, built by wikiloop. Do not read it top to bottom.

1. Open `INDEX.md` and pick the skill whose description matches the task.
2. Read that skill's `SKILL.md` only. It tells you which `references/` file to open next.
3. Never read a file marked *grep-first* end to end: grep its `## ` headers, read one entry.
4. Adding knowledge: follow `skills/wiki-contribute/SKILL.md`, then run
   `python3 {{core.path}}/bin/wikiloop build` and `python3 {{core.path}}/bin/wikiloop lint`.
5. Do not edit generated files (they say so in their first lines) or anything under
   `{{core.path}}/`. Change `wikiloop.toml` or `guides/` and rebuild.
