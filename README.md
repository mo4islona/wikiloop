# wikiloop

A team wiki that coding agents read before they act and add to when they learn something.
wikiloop is the core: the hooks, rules, review loop and on-call screen. A company brings the
content and a config file, and gets a plugin of its own for Claude Code and Codex.

## What it does

Documentation dies because writing it is a separate task from the work that produces the
knowledge. Someone debugs a service for two hours, finds the trap, fixes it, and moves on. Six
months later an agent spends the same two hours.

wikiloop does not rely on anyone remembering. With the plugin installed:

1. Every session starts with one rule: load the wiki's skill before you reason about a system
   it maps, and put what you learn back into the wiki, never into private memory.
2. After an investigation, once the user has replied, a hook asks the agent once whether the
   session found something the wiki lacks. If so, the agent files a *candidate*: symptom, root
   cause, lesson, and two lines that say why it belongs in the wiki at all. Otherwise it says
   `wiki: nothing new`.
3. A shepherd skill triages candidates, lands them as small PRs, has an independent agent
   review each PR, applies the fixes and merges what passes. What it cannot verify goes to a
   person as one question.
4. A gardener re-checks skills whose sources changed; trigger evals check that skill
   descriptions still catch the words people use.

[DESIGN.md](DESIGN.md) explains why each step is shaped the way it is.

## What a company repo looks like

```
acme-wiki/
  wikiloop.toml         # identity, inbox, investigation signals, gate, lint caps, on-call
  guides/               # overrides of the core's rule sections, one section at a time
  extensions/           # own lint checks and on-call sources, in Python
  skills/               # the knowledge: maps, debug skills, procedures
  evals/                # real prompts and the skill each must load
  core/                 # this repo, vendored at a release; never edited by hand
  .claude-plugin/ hooks/ skills/wiki-*/ CONTRIBUTING.md INDEX.md ...   # generated
```

`wikiloop build` compiles the config, the guides and the core's templates into the plugin.
Generated files say so in their first lines; CI fails when they are out of date.

## Start a wiki

```
git clone git@github.com:mo4islona/wikiloop.git
python3 wikiloop/bin/wikiloop init acme-wiki --plugin acme-wiki --company ACME \
  --domain "ACME systems" --repo acme/ai-wiki
```

Then fill the two map skills it creates, push, and install the plugin from the wiki repo:

```
./install.sh --agents claude,codex     # or one of them; --check reports without installing
```

The installer checks prerequisites (and the wiki's own, from `[install] checks`), adds the
marketplace, installs and enables the plugin. In Claude Code that is the whole setup. Codex
runs plugin hooks only after a person trusts them: open `/hooks` in a Codex session once.
`bootstrap.sh` is the one-line entry point for a private wiki repo.

| | Claude Code | Codex |
|---|---|---|
| skills | yes | yes |
| session rule, candidate prompt, gate | yes | yes, after `/hooks` trust |
| on-call status line and pane | yes | no; the watcher and its report work |
| maintainer skills (`.claude/skills/`) | yes | no |

Python 3.11+ for the maintainer commands (`build`, `lint`, `check`); the hooks and the
commands a session runs work on any `python3` from 3.9. Nothing to install: stdlib only.

## Make it yours

| To change | Edit | Reference |
|---|---|---|
| names, inbox, what counts as investigating, gate lines, caps | `wikiloop.toml` | [docs/config.md](docs/config.md) |
| the wording of a rule, a new rule | `guides/<guide>.md`, one section | [guides/](guides/) and the skeleton's `guides/README.md` |
| a lint check of your own | `extensions/lint/*.py` | [docs/config.md](docs/config.md#extensions) |
| the on-call screen and its sources | `[oncall]`, `extensions/oncall/*.py` | [docs/oncall.md](docs/oncall.md) |

What the config cannot do is switch the loop off: a zero threshold, an empty gate or a
signal-less investigation table fails the build, and `wikiloop check` runs the real hooks
against the wiki's own config to prove they still ask, once, after the user replied.

## Update

```
python3 core/bin/wikiloop update            # the latest release
```

One PR per release: the core is replaced whole, config migrations run, everything is rebuilt
and checked. [docs/upgrading.md](docs/upgrading.md) has the details, including how a guide
override learns that the core changed the section under it.

## This repo

| Path | What |
|---|---|
| `bin/wikiloop`, `wikiloop/` | the CLI |
| `hooks/` | SessionStart, Stop and candidate-gate hooks |
| `guides/` | the rules, in sections a wiki can override |
| `templates/plugin/` | skills every session with the plugin gets: `wiki-contribute`, `wiki-report-session` |
| `templates/maintainer/` | skills that need a clone of the wiki, generated into its `.claude/skills/`: `wiki-triage`, `wiki-pr-review`, `wiki-shepherd` |
| `templates/repo/` | the wiki repo's CONTRIBUTING.md and AGENTS.md |
| `oncall/` | the on-call engine, sources, its skill and the Claude Code pane |
| `templates/repo/install.sh` | the installer each wiki gets, for Claude Code and Codex |
| `template/` | the skeleton `wikiloop init` copies |
| `example/` | ACME, a fictional wiki every change is built and checked against |
| `evals/negative/` | prompts no wiki skill may catch, run with every wiki's evals |
| `tests/` | `python3 -m unittest discover -s tests -t .` |

## License

MIT, see [LICENSE](LICENSE). A vendored core keeps its copy in `core/LICENSE`; the content and
config of a wiki are its company's own.
