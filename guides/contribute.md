<!-- section: intro -->
The wiki has one enemy: context growth. An agent that has to read 2,000 lines to answer
"where does the checkout service run" is slower and worse than one that reads 40. Every rule
below exists to keep the loaded context small while keeping every fact reachable in two hops:
index → skill → one reference file.

<!-- section: layout -->
## 1. Layout

```
skills/<domain>-<topic>/
├── SKILL.md            # router: purpose, invariants, which reference to read when
├── references/*.md     # detail, opened on demand
└── scripts/*           # helpers the skill tells the agent to run
```

The prefix of a skill's name sets its group in `INDEX.md` (`wikiloop.toml`, `skills.groups`).
`wiki-` skills are about the wiki itself, and `wikiloop build` generates them. The ones every
session needs (`wiki-contribute`, `wiki-report-session`) ship in the plugin. The ones that need a
clone of this repo (`wiki-triage`, `wiki-pr-review`, `wiki-shepherd`) live in `.claude/skills/`
and load only in a session opened here, so they cost the other sessions nothing.

A skill is named after a subject, not a question: `debug-checkout`, not
`debug-find-why-checkout-times-out`. The questions are its references, named the way a person
asks them (`latency.md`, `deploys.md`), and `SKILL.md` routes between them. A new question
about a system goes into that system's skill; a new skill is created only for a system that
has none. The `SKILL.md` cap is the split signal: when the router table no longer fits, the
subject is two systems. Target is low tens of skills, growing in depth, not in count.

A skill lives in the repo whose files it edits: a procedure that changes one service's repo
stays in that repo's `.claude/skills/`, and the map links to it. The wiki holds cross-repo
knowledge only.

<!-- section: frontmatter -->
## 2. Frontmatter

```yaml
---
name: debug-checkout                        # equals the folder name
description: >-                             # what it answers + the words people use
  Debug the checkout service: slow or failed payments, 502s, stuck orders ...
owner: jdoe                                 # who to ask; a handle, not an email
last-verified: 2026-01-15                   # bumped whenever someone re-checks the content
sources:                                    # where the truth lives; the wiki is a map of it
  - https://github.com/acme/checkout/tree/main/deploy
---
```

`description` is the only thing loaded for every skill at session start. It decides whether
the agent opens the skill at all, so write it as "what + when": include the words a person
would say when they need it ("slow", "502", "stuck"). Claude Code ignores the custom fields;
`wikiloop lint` enforces them.

<!-- section: caps -->
## 3. Size caps

| Unit | Cap | When exceeded |
|---|---|---|
| `description` | {{lint.description_max}} characters | shorten |
| `SKILL.md` | {{lint.skill_md_max_lines}} lines | move detail into `references/` |
| one reference file | {{lint.reference_max_bytes}} bytes | split by sub-topic, or convert to grep-first |
| one grep-first file | {{lint.grep_first_max_bytes}} bytes | roll the oldest entries into `archive/` |
| one grep-first entry | {{lint.grep_first_entry_max_chars}} characters | keep the mechanism, link the write-up in `archive/` |

CI fails the PR on a breach. Caps are in bytes and characters, not lines: an agent pays per
token, and one 1,000-character line costs as much as twenty short ones. A reference that
needs three times the cap is two topics under one name.

<!-- section: router -->
## 4. `SKILL.md` is a router, not an essay

In order:

1. One paragraph: what question this skill answers.
2. The invariants and traps that change how someone reasons. Three to eight bullets. These
   are the highest-value lines in the wiki: one line that says when a symptom lies saves an
   hour every time it is read.
3. A table: reference file → when to read it.
4. Optional: a five-step quick path with metric names, no explanations.

If a section explains *how something works* in more than ten lines, it is a reference.

<!-- section: links -->
## 5. Link, don't copy

- Point at the file in the owning repo with a full URL or a repo-relative path. Values files,
  chart templates, alert rules and dashboards are the truth; the wiki says where they are and
  what to look for in them.
- Volatile facts never enter the wiki: IP addresses, image versions, replica counts,
  thresholds, provider lists. They rot in weeks and the reader has to re-check anyway.
- Stable facts do: cluster names and their roles, namespace patterns, which repo owns a
  component, how components are wired, metric names and their traps.
- Explanations keep system relationships, observable behaviour and what they mean for an
  operator; internal code structure and defaults stay in the owning repo. Source citations,
  metadata and the exact settings an operator needs are allowed: name a setting with its
  source and what changing it does, and link to its current value instead of copying it.
- No secrets, no tokens, no credentials. Say where the secret is, never what it is.
- `wikiloop lint` rejects IP addresses and home-directory paths. Name the host's role and
  where its address is looked up; use repo-relative paths or URLs.

<!-- section: one-fact -->
## 6. One fact, one place

Write a fact once and link to it with a relative path. `wikiloop lint` fails on dead links.
If two skills need the same paragraph, one of them gets a link.

<!-- section: grep-first -->
## 7. Grep-first files

Some content is naturally a log: incidents and past decisions. Such a file is *grep-first*,
and its cap is {{lint.grep_first_max_bytes}} bytes instead of {{lint.reference_max_bytes}}:

- It is named `incidents.md` or `decisions.md`, and its first lines say `Grep-first file` and
  how to search it.
- One entry per `## YYYY-MM-DD — <symptom>` header, so `grep -n '^## '` is the table of contents.
- Every entry is at most {{lint.grep_first_entry_max_chars}} characters: Symptom / Root cause
  / Fix / Lesson (/ Refs), then a link to the full write-up in `archive/`.
- Append at the bottom, in date order. Never rewrite history. An entry proven wrong later
  keeps its text and gets ` [superseded by YYYY-MM-DD]` at the end of its header; the newer
  entry says what was wrong.

`archive/<topic>-<year>.md` in the same skill holds full narratives with their timelines and
numbers. It is not in the router table, has no caps, and is linted only for secrets and
language. The `SKILL.md` that owns a grep-first file tells the agent to grep it, not read it.

<!-- section: freshness -->
## 8. Freshness

`last-verified` older than {{lint.stale_days}} days makes `wikiloop lint --stale` list the
skill. Anyone touching a skill re-checks the facts they can see and bumps the date. Do not
bump without checking: a wrong fact with a fresh date is worse than a stale one.
`wikiloop gardener` lists the skills whose `sources` changed since that date.

<!-- section: loop -->
## 9. Close the loop

The wiki grows from investigations, not from writing sessions. When a session finds something
the wiki did not know, the fix and the wiki change are the same piece of work:

- A mechanism (true with the date stripped) → the reference that owns the subject, next to the
  sentence it corrects. If it changes how one reasons about the system, also a `SKILL.md` bullet.
- A resolved incident → an entry in the skill's `incidents.md`.
- A new component or wiring → a row in the relevant map.
- Never a "gotchas" file: a mechanism filed as a dated story is invisible to the router and
  gets refiled. Placement is by subject, not by shape.

If you cannot tell whether it belongs, file a candidate instead of deciding. Search the open
candidates first; one that already has the fact gets a comment, not a twin:

```
python3 <plugin root>/{{core.path}}/bin/wikiloop candidate search '<keyword>'
python3 <plugin root>/{{core.path}}/bin/wikiloop candidate file -t '<symptom as a person would say it>' <<'EOF'
Symptom: ...
Root cause: ...
Lesson: ...
{{gate.lines}}
EOF
```

A wrong candidate costs a minute at triage; a lost fact costs an incident.

<!-- section: gate -->
Gate, all three must hold:

1. It is about {{wiki.domain}}, in a part the wiki maps. How {{skills.vendor_examples}}
   or another vendor behaves is not; that lives in the vendor's docs.
2. Its home is not a repo. A bug fixed this session, the mechanism of code written this
   session, a procedure in a README or an ADR: it belongs to that repo and is handled as it
   would be without the wiki. The wiki keeps cross-repo traps and invariants only.
3. An agent that starts from that repo and the vendor docs would still reason wrongly without
   it. One-host procedures, volatile values and "it took an hour, not a week" facts fail.

<!-- section: tests -->
Three tests catch what passes the gate by wording alone:

- **Strip the date.** "The alerting config has been broken since April" describes a state;
  read a month later it is either fixed or a new incident. State goes into the owning gap list
  (a `*-migration.md` file) as a row that is deleted when the change lands. An entry records
  the mechanism that made the state possible: "a failed config drops every route it declares".
- **Swap {{wiki.company}} for any other company.** "A Helm release is one opaque resource to a
  Pulumi policy pack" holds for anyone, so it is Pulumi behaviour, whichever of our projects
  it was met in. "On the billing project" is the setting, not the fact. If one line of it is
  ours (which of our endpoints needs the header), keep that line where it is needed and drop
  the rest.
- **Refactor the code.** Imagine internal files, functions and config keys renamed, behaviour
  unchanged. An explanation that would now be false described the implementation; the repo
  already says it, so it stays there ("refused when the scheduler exceeds
  `queue.headroom` in `scheduler.rs`"). Keep what an operator sees from outside and what it
  means ("per pod, never per key; usually slow workers"). Apply this to explanations, not to
  source citations, metadata or the exact settings an operator needs. Verify a rewritten claim
  against its source, and keep its conditions and uncertainty.

Keep correct, clear, properly placed text unchanged. Before proposing an edit, check all
applicable rules and make the smallest change that satisfies them together.

<!-- section: candidate-lines -->
The candidate lines the gate requires:

{{gate.help}}

The first line proves only that the wiki lacks the fact; the second, that the wiki should have
it. A hook refuses a candidate without them. If you cannot write them, the fact is not wiki
material.

<!-- section: language -->
## 10. Language and tone

Write in English only. Be terse. Give the mechanism, not the narrative ("a mutation reserves
free space equal to the whole part; it skips a part that is too large and shows no error").
Put metric names, namespaces and paths in backticks, exactly as the system shows them. Use the
active voice, short sentences and one topic per paragraph; use a vertical list for steps.

Do not change literal text: code, error messages, log lines, and the quoted phrases that a
person types, for example in a `description`. The cases in `evals/` copy how people type.

<!-- section: checks -->
## 11. Checks before you push

```
python3 {{core.path}}/bin/wikiloop build      # regenerates every generated file; commit the result
python3 {{core.path}}/bin/wikiloop lint       # frontmatter, caps, dead links, secrets, language
python3 {{core.path}}/bin/wikiloop check      # the rails still hold with this wiki's config
```

CI runs all three and fails if a generated file is out of date. Generated files say so in
their first lines; edit `wikiloop.toml` or `guides/` instead.

`.claude-plugin/plugin.json` has no `version` field on purpose. For a git marketplace the
updater then keys the cache on the commit of the default branch, so every merged commit is a
release.

<!-- section: review -->
Ten lines is a normal wiki PR. Merging one needs one review and no discussion unless it
contradicts an existing entry, in which case the older entry is corrected, not left beside it.
The review is the `wiki-pr-review` skill in `.claude/skills/`: what the lint cannot judge, line by line.
Keep correct, clear, properly placed text unchanged. Review additions and deletions in
context, check the evidence, and propose the smallest fix that satisfies all applicable rules
in one pass. Wording preferences alone do not block a merge.
