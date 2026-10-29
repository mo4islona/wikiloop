# ${company} wiki

What ${company}'s agents know about ${domain}, and how they add to it. Built with wikiloop:
the core is vendored in `core/`, the settings are in `wikiloop.toml`.

## Install

From a clone, for Claude Code, Codex or both:

```
./install.sh --agents claude,codex
```

In Codex, open `/hooks` once and trust the ${plugin} hooks: until then the skills work and the
wiki loop does not.

## Change it

- Knowledge: `skills/`, through the `wiki-contribute` skill or a candidate issue.
- Settings: `wikiloop.toml`, then `python3 core/bin/wikiloop build`.
- Wording of the rules: `guides/` (see `guides/README.md`).
- The core: `python3 core/bin/wikiloop update`, one PR per release.
