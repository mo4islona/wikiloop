---
name: wiki-contribute
description: >-
  Add or update knowledge in the {{wiki.company}} wiki after an investigation, incident or infra change: where it goes, size caps, grep-first entry format, lint. Use when asked to write something to the wiki or document what was found.
owner: wikiloop
last-verified: {{core.released}}
generated: wikiloop
---

# Contribute to the wiki

Input: something learned. Output: the smallest diff that lets the next agent find it in two
hops. The full rules are in [CONTRIBUTING.md](../../CONTRIBUTING.md); this is the procedure.

## 1. Decide where it goes

Placement is by subject, not by shape. Ask in order; the first yes decides.

| What you learned | Where it lands |
|---|---|
| A mechanism, true with the date stripped: how components are wired, what a series means, where something runs, which tool ships it | the reference that owns the subject (`architecture.md`, `metrics.md`, a map file), next to the sentence it corrects or extends; a new bullet or row when there is none |
| The same, and it changes how one reasons about the whole system | also a bullet in the owning skill's `SKILL.md` invariants, max 8, pointing at the reference |
| A resolved incident: symptom, cause, fix, with a date | an entry in the owning skill's `references/incidents.md` (grep-first), plus one sentence at the mechanism's home when the mechanism was new |
| A sequence of checks | the skill's `playbook.md`; a procedure that edits one repo is a skill in that repo's `.claude/skills/`, linked from the map |
| A new component, namespace, repo or wiring | a table row in a map skill's references |
| A new question about a system that has a skill | a reference file in that skill plus a row in its router table |
| A system with no skill yet | a new `debug-<system>` skill; copy the shape of an existing one |

There is no "gotchas" destination. A mechanism filed as a dated story hides from the router
and gets refiled by the next session; a fact that fits no reference means the subject has no
sentence yet, so add one to the closest reference. If the fact already exists somewhere,
correct it in place; never add a second version. A fact that proves an incident entry wrong:
mark the old header ` [superseded by <date>]` and add the new entry; never delete history.

{{guide:contribute#gate}}

{{guide:contribute#tests}}

Not sure it belongs, or no time for a PR? File a candidate; triage takes them in batches.
Search the open ones first: if one has the fact, comment what it lacks instead of filing again.

```
python3 <plugin root>/{{core.path}}/bin/wikiloop candidate search '<keyword>'
python3 <plugin root>/{{core.path}}/bin/wikiloop candidate file -t '<symptom as a person would say it>' <<'EOF'
Symptom: ...
Root cause: ...
Lesson: ...
{{gate.lines}}
EOF
```

{{guide:contribute#candidate-lines}}

## 2. Write the entry

Grep-first entry, at the bottom of the file, at most {{lint.grep_first_entry_max_chars}} characters:

```
## YYYY-MM-DD — <symptom as a person would say it>
**Symptom:** what was seen, one or two sentences.
**Root cause:** the mechanism, with exact metric names, namespaces, error codes.
**Fix:** the lever; a tracker link (PR, issue, gap-list row) where one exists.
**Lesson:** the reusable takeaway. The most important line.
**Refs:** PRs, alert names, tickets (optional).
```

Tense: past for what was true at the time. Never "open", "done <date>", "now", "still" or
"since <date>": a reader a year later takes them as today. Status goes in a tracker link
where one exists, and nowhere otherwise.

Style: the language section of [CONTRIBUTING.md](../../CONTRIBUTING.md). No IPs, versions,
replica counts, thresholds or secrets; point at the file that holds them. The full narrative
with its timeline and numbers goes to the skill's `archive/<topic>-<year>.md`; the entry
links to it.

## 3. Bump and verify

- Set `last-verified` in the skill's frontmatter to today only if you checked the rest of the
  skill still holds. Otherwise leave it.
- Run from the wiki's root; all must pass, and the build's output is committed:

```
python3 {{core.path}}/bin/wikiloop build
python3 {{core.path}}/bin/wikiloop lint
```

## 4. Open the PR

Title: `wiki(<skill>): <what was learned>`. Body: one sentence on where the fact came from
(incident, PR, ticket), and `Closes #N` for each candidate it absorbs. A wiki PR gets one
review through `wiki-pr-review`, a maintainer skill in the wiki repo's `.claude/skills/`.
