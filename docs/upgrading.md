# Upgrading the core

A wiki vendors the core into `core/` at a release. An update is one PR in the wiki repo.

## Versions

Semver tags on this repo (`v0.2.0`). What each level promises:

- **patch**: fixes only; no config change, no guide text change. A wiki may merge it on green CI.
- **minor**: new config keys with defaults, new guide sections, new extension points. A person
  reads the CHANGELOG lines and the regenerated diff.
- **major**: a config key or an extension interface changes. A migration rewrites the config;
  the CHANGELOG says what to check.

Within a major version, guide section IDs do not change and the extension interfaces keep
working.

## The update

```
python3 core/bin/wikiloop update             # the latest tag of core.repo
python3 core/bin/wikiloop update v0.3.0
```

It clones the tag, replaces `core/` whole, applies `core-patches/*.diff`, runs the config
migrations between the two versions (`core/migrations/<version>.py`, each rewrites the TOML
text), then runs the new core's `build` and `check`. Review the diff and open one PR.
Rollback is a revert of that PR.

A scheduled CI job in the wiki can run the same command weekly and open the PR itself.

## Guide overrides across an update

An override records the hash of the core section it was written against:

```
<!-- section: language mode=replace base=bb0f5ac4 -->
```

When an update changes that core section, the build prints a warning with the new core text,
and `build --strict` fails. A person reads the change, folds what matters into the override,
and sets `base` to the hash that `wikiloop guides` prints. An override of a section that the
core removed or renamed fails the build with the section's name: it never disappears silently.

## A hotfix that cannot wait

`core/` is never edited by hand: `wikiloop check` compares its tree hash with the one the last
update recorded, and fails on a difference. For an urgent fix, put a patch in
`core-patches/<name>.diff` (paths relative to the core) and run `wikiloop update` with the
current tag. The update applies it, records it, and reports it on every later update until a
release contains it; then it says the patch is already in the core and the file can go.

## Releasing the core

1. Every change keeps `example/` built and green: `python3 -m unittest discover -s tests -t .`
   runs build, lint and check on it, and on a wiki fresh from `init`.
2. Tag a release candidate (`v0.3.0-rc.1`) and update one real wiki to it first. Watch a week
   of its sessions: how often the Stop hook asks, how often the answer is "nothing new", how
   many candidates the gate refuses.
3. Tag the release; add its CHANGELOG section with a date and update `VERSION`.
