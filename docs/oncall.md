# On-call watch

The on-call part of wikiloop keeps one rolling report of everything that is broken: every
active alert, plus probes for the failures that no rule sees, folded into problems. A wiki
turns it on with `[oncall] enabled = true` in `wikiloop.toml`; `wikiloop build` then generates
the screen (`hooks/oncall/`) and the `howto-oncall-watch` skill.

It has three layers, and only the first one is the company's:

| Layer | Where | What a wiki changes |
|---|---|---|
| Sources | `[oncall.alertmanager]`, `[[oncall.probes]]`, `[oncall.restarts]`, `extensions/oncall/*.py` | everything: which systems are read, which blind spots are probed |
| Engine | `core/oncall/engine.py`, run by `core/oncall/watch.py` | thresholds and naming only; the rails stay |
| Screen | `hooks/oncall/` generated from `core/oncall/mod/` | command name, title, severities, sections |

## The rails

These hold for every configuration; `validate` refuses a config that would break one.

- **Dedup by subject, not by alert.** Every alert name on one subject and component is one
  problem. One alert name on many subjects that started together is one fleet problem.
- **Resolve only after absence.** A problem resolves after `resolve_after` (1 or more) cycles
  without a signal, and only when every source that reported it answered.
- **A source that is down freezes its problems.** It repeats its last answer; its problems
  neither resolve nor change severity, and a `SOURCE-DOWN` event says so.
- **The report states its freshness.** Its header names the cycle length; the screen warns
  when the last cycle is older than two cycles.
- **A flap is told once.** Stdout drops a repeat of a state it already told; `events.log` and
  the report keep every change.

## Configuration

`oncall/example.toml` is a complete example. The keys, with their defaults:

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `false` | generate the screen and the skill |
| `command`, `title` | `oncall`, `On-call` | the slash command and the pane title; the line under the prompt uses the title in lower case |
| `interval`, `resolve_after`, `heartbeat` | `300`, `2`, `3600` | seconds between cycles; absent cycles before a problem resolves; seconds between `HEARTBEAT` lines |
| `state_dir` | `$HOME/.cache/<plugin>/oncall` | where `state.json`, `report.md` and `events.log` live; must start with `~/` or `/` |
| `severities` | critical, major, minor, info | highest first, each with a terminal color |
| `loud`, `floor` | `major`, `minor` | `loud` and above is named on the line; below `floor` a problem is never new and never streamed |
| `tiers` | `[]` | highest first; a subject's tier orders problems and can raise a probe's severity |
| `thresholds.*` | see `oncall/defaults.py` | windows in seconds: new, chronic, resolved kept, flap quiet, spread, fleet size and gap, stale slack, start guard |
| `subject.*` | `labels = ["service"]` | which labels name the subject, the place of a signal without one, components, variants, tiers and envs by glob |
| `alertmanager.*` | `url = ""` | the alerts endpoint (direct or through a Grafana datasource proxy), the token file or env var, severity mapping, the annotation that holds a web link |
| `prometheus.*` | `url = ""` | the query endpoint the probes, the restarts source and extensions use |
| `[[probes]]` | none | `name`, `description`, `query`, `component`, `severity`, `summary` |
| `restarts.*` | off | kube-state-metrics restarts: window, crash-loop count, excluded namespaces, kube contexts for the last error line |
| `extensions`, `presenter` | none | Python files in the wiki, relative to its root |
| `routes.*` | off | the channel an alert reaches: team label, channel template, URL template |
| `present.strip_prefixes` | `[]` | literal prefixes cut from alert texts on the screen |
| `[[sections]]` | Major, Minor, Resolved, Chronic | the pane and the report, in order |

### Severity specs

A probe's `severity` and each `restarts.severity` entry is a severity name, or a table of
tier to severity with a `default`: `{ default = "minor", core = "major" }`.

### Sections

Each `[[oncall.sections]]` table is one block of the pane and one heading of the report:

| Key | Values | Meaning |
|---|---|---|
| `title` | text | `{resolved_kept}` prints the kept window, such as `6h` |
| `status` | `open`, `resolved` | which problems |
| `min_severity`, `max_severity` | a severity, or `""` | the severity range |
| `chronic`, `new` | `any`, `only`, `exclude` | open longer than `chronic_after`; opened within `new_window` |
| `style` | `full`, `compact`, `inline` | a block per problem, one line per problem, or one wrapped line |
| `color`, `limit`, `empty` | text, number, text | title color when not empty; most items shown (0 is all); text when empty, `""` hides the section |
| `fold_below` | boolean | count the problems under `min_severity` in one line |

The report adds "New and changed this cycle" before the sections and "Other open problems"
after them, so no open problem is missing from it.

## Extensions

A source extension is a Python file with `collect(ctx) -> list`. It builds each signal with
`ctx.signal(labels, component, severity, source, name, summary, started="", link="",
silenced=False)` and can run PromQL with `ctx.query(expr)`. It is a source of its own, named
`ext:<file stem>`, so its failure freezes only its problems. `example/extensions/oncall/regions.py`
is one.

A presenter is a Python file with `present(problem, view) -> dict`: it gets the view the engine
computed (`label`, `what`, `error`, `links`, `tier`) and returns the one to draw.

## How the parts find each other

- `wikiloop build` writes the resolved config to `hooks/wikiloop.json`. The watcher reads it
  from `--config`, else `$CLAUDE_PLUGIN_ROOT/hooks/wikiloop.json`, else the first
  `hooks/wikiloop.json` above the script; it runs on any `python3` from 3.9.
- The watcher writes `view` into every problem in `state.json`. The screen polls that file and
  draws the view; it never parses an alert.
- The screen is generated, not configured at run time: a state reference needs the plugin's
  name as a literal, and a hooks module imports only `.ts` files. `config.ts` carries the rest.

## Tests

```
python3 -m unittest discover -s tests/oncall                         # engine, sources, build, one cycle end to end
WIKILOOP_MOD_TESTS=1 python3 -m unittest discover -s tests/oncall    # plus the screen, through `claude plugin test`
```
