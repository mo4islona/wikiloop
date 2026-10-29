# wikiloop

Turn what agents learn while working into reviewed, shared team knowledge.

## Every session can make the next one smarter

wikiloop turns useful lessons from agent sessions into reviewed skills, grounded in your
team's docs, code, and decisions. Agents start informed by what the team has already learned
and propose new knowledge as they work. Each accepted lesson gives future sessions better
context for the task ahead.

## One shared memory for the whole team

What one agent learns can help everyone. Your team keeps its knowledge in a shared Git
repository, and wikiloop distributes it as a plugin for **Claude Code and Codex**. Lessons
carry across people, projects, and machines, so the team's knowledge grows with its work.

## How it works

The wiki is a collection of **skills**: Markdown instructions that an agent loads when a
task calls for them. A skill can explain a product, describe a workflow, record a decision,
or guide a recurring task. Detailed context and sources live alongside it in reference files.

1. **Use what the team already knows.** A session hook tells the agent to load the relevant
   wiki skill before acting on a subject it covers.
2. **Propose what is missing.** After work involving tools or skills your team has configured,
   and once the user has replied, a hook prompts the agent to check for a useful lesson.
   The agent files a candidate issue explaining the lesson and why it belongs in the wiki,
   or reports that there is nothing new to add.
3. **Review and incorporate it.** A maintainer invokes the shepherd workflow to triage
   candidates, turn accepted lessons into PRs, have a separate agent review them, and merge
   what passes review and CI. Questions the agents cannot verify go to a person.
4. **Keep it useful.** Maintainers run source checks to find knowledge that may have changed
   and trigger evals to check whether real prompts lead agents to the right skills.

For example, an agent learns that two steps in a publishing workflow must happen in a
particular order. It proposes the lesson, a reviewer checks the source, and the accepted
change becomes part of the workflow skill. The next agent following that skill gets the
lesson before starting the task.

The session hooks run automatically after installation and any required hook trust.
Review, source checks, and evals run when a maintainer invokes them; installation does not
schedule them. See [the design](DESIGN.md) for the reasoning behind the loop.

## Start a team wiki

You need Python 3.11+, Git, and the GitHub CLI (`gh`), authenticated with access to the wiki
repository. Running agent workflows also requires Claude Code or Codex as described below.
The Python code uses only the standard library.

Create the wiki, replacing the example identity and repository with your team's:

```sh
git clone https://github.com/mo4islona/wikiloop.git
python3 wikiloop/bin/wikiloop init acme-wiki \
  --plugin acme-wiki --company ACME \
  --domain "ACME products and workflows" --repo acme/ai-wiki
cd acme-wiki
```

The new directory contains a config, two starter skills (`map-product` and `map-infra`),
an eval case, CI, and a copy of wikiloop in `core/`.

Fill the starter skills with enough context to help with a real task. Choose which tools
and skills should trigger contribution prompts in `wikiloop.toml`, then build and check:

```sh
python3 core/bin/wikiloop build
python3 core/bin/wikiloop lint
python3 core/bin/wikiloop check
```

Commit and push this directory to the repository named by `--repo`. For a new GitHub
repository, for example:

```sh
git init -b main
git add .
git commit -m "Create team wiki"
gh repo create acme/ai-wiki --private --source=. --remote=origin --push
gh label create candidate --repo acme/ai-wiki --description "Proposed wiki knowledge"
```

## Install the plugin

From a clone of your team's wiki, run:

```sh
./install.sh --agents claude,codex
```

Use `--agents claude` or `--agents codex` to select one. Add `--check` to report prerequisites
and installation status. The installer checks access, adds the marketplace, and installs and
enables the plugin. Start a new agent session afterwards.

**In Codex, open `/hooks` and trust the wiki's hooks.** Skills are available before
that step; the automatic contribution prompts require hook trust. Codex 0.165 lists the hooks
as new or changed once more on the next start; trust them again then.

| Capability | Claude Code | Codex |
|---|---|---|
| Team knowledge as skills | Yes | Yes |
| Session rules and contribution prompts | Yes | After hook trust |
| Maintainer skills in the wiki checkout | Yes | — |
| Optional on-call status line and pane | Yes | Watcher and text report only |

The hooks and session commands run on Python 3.9+. Building and maintaining the wiki requires
Python 3.11+. Each wiki also gets a `bootstrap.sh` entry point for distributing its installer.

## Maintain the knowledge

Open Claude Code in the wiki checkout and ask it to **“shepherd the wiki”**. The generated
`wiki-shepherd` skill runs the candidate, review, and merge workflow. Its state lives in
GitHub issues and PR comments, so a later session can continue the work.

The CLI also provides commands for checking the wiki:

```sh
python3 core/bin/wikiloop inbox       # open candidates and PRs
python3 core/bin/wikiloop gardener    # skills whose sources changed or need re-verification
python3 core/bin/wikiloop evals       # whether prompts trigger the expected skills
```

`gardener --fix` starts Claude Code sessions to re-verify skills and open PRs.
Trigger evals also use Claude Code. These commands make model calls; the session hooks do
not.

## Adapt it to your team

Your wiki owns the knowledge and configuration. It includes a copy of this repository in
`core/`, so each core update can be reviewed together with the plugin it generates.

| What you want to change | Where it lives |
|---|---|
| Knowledge, procedures, and supporting sources | `skills/` |
| Identity, contribution signals, and validation settings | `wikiloop.toml` |
| The wording of wiki rules | `guides/`, overriding individual core sections |
| Checks specific to your team | `extensions/lint/` |
| Prompts that should load a particular skill | `evals/` |
| Optional on-call sources and presentation | `[oncall]` and `extensions/oncall/` |

Run `python3 core/bin/wikiloop build` after changing configuration or guides. It generates
the plugin manifests, hooks, shared workflow skills, maintainer skills, and wiki index.
The generated CI workflow checks that those files are up to date and that the wiki passes
lint and hook checks.

To update the core to its latest release:

```sh
python3 core/bin/wikiloop update
```

The command replaces the core, applies config migrations, rebuilds, and checks the result.
Review and commit the changes as one PR. See [upgrading](docs/upgrading.md) for guide
overrides and patches across releases.

## Further reading

- [Example wiki](example/) — a fictional team's skills, config, and generated plugin.
- [Design](DESIGN.md) — how contribution prompts, review, and verification fit together.
- [Configuration](docs/config.md) — settings, defaults, and custom lint checks.
- [Guide overrides](template/guides/README.md) — adapt the rules section by section.
- [On-call](docs/oncall.md) — the optional watcher, sources, and Claude Code pane.
- [Session reports](docs/report-session.md) — configure reports for sessions that went wrong.

## License

[MIT](LICENSE). Each vendored core includes its license in `core/LICENSE`; your team's wiki
content and configuration remain your own.
