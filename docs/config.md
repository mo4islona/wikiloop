# wikiloop.toml

Every key, its default and what it does. Only `[wiki]` is required; everything else has a
default. An unknown key fails the build, so a typo never silently does nothing.
`wikiloop build` writes the resolved config to `hooks/wikiloop.json`, which the hooks read.

## [wiki]

| Key | Default | Meaning |
|---|---|---|
| `plugin` | required | the plugin name; skills are invoked as `<plugin>:<skill>`. Lowercase, digits, hyphens |
| `company` | required | used in the rules: "swap `<company>` for any other company" |
| `domain` | required | what the wiki is the single store for, e.g. `"ACME systems"` |
| `repo` | required | `<owner>/<name>` of the wiki repo: PRs, and the default inbox |
| `description` | derived | the plugin's description in the marketplace |
| `owner` | `company` | the marketplace owner name |

## [inbox]

| Key | Default | Meaning |
|---|---|---|
| `kind` | `"github"` | the tracker adapter; this version has GitHub issues |
| `repo` | `wiki.repo` | where candidates are filed |
| `label` | `"candidate"` | the label that marks a candidate |

## [gate]

`required` is a list of lines every candidate must carry, each `{ key, help }`. The default is
the two lines below; a wiki may reword them or add one, but not remove them all.

```toml
[[gate.required]]
key = "Why the wiki"
help = "where an agent would look first, and why it would not find the fact there"

[[gate.required]]
key = "Not repo or vendor"
help = "which repo and which vendor docs you checked, and why neither is the fact's home"
```

## [investigation]

What the Stop hook counts as investigating a live system.

| Key | Default | Meaning |
|---|---|---|
| `debug_skills` | `["debug-*"]` | globs over this plugin's skill names; one load weighs `threshold` steps |
| `commands` | `["kubectl"]` | command words; each shell call that contains one counts one step |
| `patterns` | `[]` | regexes over the shell command, e.g. an internal API host |
| `mcp_tools` | `[]` | globs over MCP tool names, e.g. `"mcp__grafana__query_*"` |
| `threshold` | `5` | steps since the session started before the hook asks; 1 or more |
| `reask` | `20` | further steps before it asks again; not below `threshold` |

At least one of the four signal lists must be non-empty.

## [skills]

| Key | Default | Meaning |
|---|---|---|
| `groups` | maps, debug, howto, wiki | `INDEX.md` sections by name prefix: `[{ prefix, title }]`, in order |
| `vendor_examples` | `"Kubernetes, Docker, BigQuery"` | the vendors the rules name as examples of what is not wiki material |

`INDEX.footer.md` in the wiki root, if present, is appended to `INDEX.md` verbatim: the place
to list skills that live in other repos.

## [lint]

| Key | Default | Meaning |
|---|---|---|
| `description_max` | `250` | characters in a skill's `description` |
| `skill_md_max_lines` | `150` | lines in a `SKILL.md` |
| `reference_max_bytes` | `12000` | bytes in one reference file |
| `grep_first_max_bytes` | `32000` | bytes in `incidents.md` / `decisions.md` |
| `grep_first_entry_max_chars` | `1500` | characters in one grep-first entry |
| `stale_days` | `90` | `last-verified` older than this is listed by `lint --stale` and the gardener |
| `required_fields` | `name, description, owner, last-verified` | frontmatter every skill carries |
| `english_only` | `true` | refuse non-Latin scripts in skills and docs |
| `allowed_home_paths` | `[]` | `~/` paths a skill may name, e.g. `[".grafana"]` for a token file; `~/.cache` is always allowed |

### Extensions

A wiki adds its own lint checks as `extensions/lint/*.py`, each with a `check(ctx)` function.
`ctx.root` and `ctx.skills` are paths, `ctx.cfg` is the resolved config, and
`ctx.err(path, msg)` / `ctx.warn(path, msg)` report. The example wiki's
`extensions/lint/cluster_names.py` checks that every cluster a skill names is in the map.

## [report_session]

| Key | Default | Meaning |
|---|---|---|
| `kind` | `"none"` | `gcs`, `s3`, or `none` (no `wiki-report-session` skill is generated) |
| `bucket` | `""` | `gs://...` or `s3://...`; required unless `none` |
| `ttl_days` | `30` | what the skill tells users; the lifecycle rule on the bucket enforces it |

Bucket setup: [report-session.md](report-session.md).

## [shepherd]

| Key | Default | Meaning |
|---|---|---|
| `max_rounds` | `2` | review rounds per pushed head before the PR goes to a person |
| `max_land_prs` | `2` | PRs one landing run may open |

## [evals]

| Key | Default | Meaning |
|---|---|---|
| `model` | `""` | pin the model for trigger evals; triggering differs per model |
| `threshold` | `0.66` | the share of runs a case must pass |
| `runs` | `3` | runs per case when the case does not say |

## [install]

What the generated `install.sh` checks besides the agent CLIs, git and `gh`.

| Key | Default | Meaning |
|---|---|---|
| `access_hint` | `"ask a maintainer of the wiki for access"` | what a person without access to the wiki repo should do |
| `checks` | `[]` | the wiki's own checks: `{ name, check, hint, tier }`, `tier` is `recommended` (default) or `optional` |

A `check` is a shell snippet; the installer provides `have <cmd>`, `has_kube_context <name>`
and `has_mcp <name>`. A failed check prints its hint and never blocks the install.

```toml
[install]
checks = [
  { name = "kubectl", check = "have kubectl", hint = "brew install kubernetes-cli" },
  { name = "kube context acme-prod-eu", check = "has_kube_context acme-prod-eu", hint = "see skills/map-infra" },
]
```

## [core]

| Key | Default | Meaning |
|---|---|---|
| `repo` | `"mo4islona/wikiloop"` | where `wikiloop update` fetches releases |

## [oncall]

Off by default. The schema, the sources and the pane: [oncall.md](oncall.md).
