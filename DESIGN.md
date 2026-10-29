# Design

The wiki learns from the sessions that use it. This document explains why it is fed the way it
is, what each mechanism is for, and which parts a company can tune and which it cannot.

## The problem

Documentation dies because writing it is a separate task from the work that produces the
knowledge. Asking people to remember does not work. Asking them at the end of a session, when
they want to stop, gets "nothing new" almost every time. So the wiki does not rely on anyone
remembering: each mechanism below runs without anyone starting it, and each is built to cost
the person as close to zero decisions as possible.

## The loop

1. A session starts with the plugin. Its context carries one rule: check the wiki before you
   reason about a system it maps, and put what you learn back into it.
2. The agent investigates: it loads a debug skill, runs `kubectl`, queries metrics.
3. Once the user has answered the finding, a hook notices the investigation and asks once: did
   this session find something the wiki lacks? If so, file it as a candidate. If not, say so.
4. The shepherd triages candidates, lands the accepted ones as small PRs, has an independent
   reviewer check each PR, applies the fixes and merges what passes. A person answers only the
   questions a reviewer cannot verify.
5. The content is checked for drift: descriptions against real prompts, facts against commits
   in the repos they describe.

Every step lowers the cost of the next one. The rule at session start makes the agent grep the
wiki, so it knows what is already there. The hook fires only after real investigation, so it
does not nag. Filing a candidate needs no decision about where the fact belongs, so the agent
does it. Review and merge are automated, so the loop does not stall on one maintainer.

## The mechanisms

### The session starts with the rule

A SessionStart hook adds one paragraph to every session's context. The point is the delivery
channel, not the text: a rule in one person's `CLAUDE.md` reaches only that person; a rule in
the plugin reaches every machine that has it, in every repo, and changes for all of them when
the plugin updates. That is what makes the wiki the single copy of a fact.

### The plugin asks at the end of an investigation

Two small hooks log the session as it goes: after each tool call, a step if the call is one
the wiki's config names (a debug skill load, a shell command, an MCP query); after each prompt,
a reply if a person typed it. A Stop hook reads that log and weighs the steps. Below a
threshold it stays silent. Above it, once per burst and only after the user has typed something
since the last step, it holds the turn and gives the agent one instruction: grep the wiki and
the open candidates, then file a candidate or answer `wiki: nothing new`.

- **It asks for a candidate, not a PR.** A PR needs a decision about which skill, which file,
  what wording. A candidate needs a symptom, a cause and a lesson; the agent has all three at
  that moment and none of the judgement.
- **It asks with a gate.** The hook counts `kubectl` calls, so it fires on deploying your own
  service as readily as on debugging someone else's. Without a filter every session files the
  bug it just fixed. So the candidate must say why the wiki should hold the fact, and which
  repo and vendor docs the filer checked; `wikiloop candidate` refuses a body without those
  lines, and a hook refuses the raw tracker command that skips it.
- **It asks after the user has answered.** The turn that produces a finding ends before anyone
  has read it. A finding the user has read and not challenged is the closest thing to a
  reviewed fact the loop can get without a person in it. The same guard keeps it quiet in
  one-shot runs (`claude -p`, `codex exec`): nobody replies after the steps.
- **It asks once.** A hook that fires on every stop gets ignored. It waits for a much larger
  burst before it asks again, and a resumed session counts from the moment it resumed, not
  from days of earlier work.
- **It counts events, not transcripts.** Claude Code and Codex send the same hook fields,
  and neither promises a stable transcript format. The log is the one input the hooks own, so
  the same scripts run under both agents.
- **It makes no network or model calls.** It reads a file and counts. A few milliseconds,
  nothing that can fail in a way that blocks the user.

### The shepherd closes the loop

Candidates that nobody triages are worse than none: they look like a working loop. The
shepherd runs triage, landing, review and merge as one pass. Its rails: the reviewer is never
the author (a fresh subagent with only the PR number), state lives in PR comments so any later
session continues the run, a merge needs the reviewer's `merge` verdict on the current head and
green checks, and anything unverifiable becomes `needs-human` with the one decision named.

### Descriptions are tested against real prompts

A skill's description is the only thing an agent sees before it decides to open the skill. A
description that misses the words people use makes the skill invisible, and nothing fails. So
each wiki keeps prompts people really typed and the skill each must trigger; `wikiloop evals`
runs them. The core adds negative prompts that no wiki skill may catch.

### A gardener re-verifies what may have gone stale

Every skill names its sources and the date it was last verified. The gardener lists skills
whose sources have commits since that date, and can start one session per skill that checks it
sentence by sentence and opens a PR that edits only what is now false.

## Who sees which skill

A skill's description is in every session's context, so a skill that a session cannot use
is pure cost. The generated skills are split by what they need:

- `wiki-contribute` and `wiki-report-session` work from any repo: they ship in the plugin.
- `wiki-triage`, `wiki-pr-review` and `wiki-shepherd` need a clone of the wiki (they read its
  inbox, its PRs, its files): they live in the wiki repo's `.claude/skills/` and load only in a
  session opened there.
- A feature brings its own skill: `howto-oncall-watch` exists only when `[oncall]` is enabled.

## Core and content

wikiloop splits the system along one line: what is true of any team that uses agents (the
loop, the gate, the review rules, the on-call engine) is the core; what is true of one company
(its systems, its words, its tools, its alert sources) is content and config.

| Tunable by a wiki | Fixed by the core |
|---|---|
| plugin name, company, domain, repos | the shape of the loop |
| which tools and skills count as investigation | ask only after the user replied |
| thresholds and the re-ask interval | ask once per burst; never outside the interactive CLI |
| the gate lines and their help | a candidate without them is refused |
| the wording of every rule, section by section | no hook makes a network or model call |
| size caps, stale age, allowed home paths | a session never edits the wiki directly |
| on-call sources, probes, routing, pane sections | a source that is down freezes its problems, never resolves them |

`wikiloop check` turns the right column into tests that run against each wiki's own config.

The core is vendored into each wiki at a release, not installed beside it. Claude Code loads
hooks and the on-call pane from the plugin that declares them, so the core and the content
must be one plugin; vendoring also means a core update is one reviewed PR, built and checked
against that wiki's content before it reaches anyone.

## What is deliberately not automated

- **No direct wiki edits from a working session.** A session files a candidate. A wrong
  candidate costs a minute; a wrong fact in the wiki costs an incident.
- **No model call inside the hooks.** They must be free and must never block a session.
- **No transcript leaves the company.** A bad session goes to the company's own bucket. A fault
  in the rails goes upstream to wikiloop as an issue a person writes, with no transcript and no
  wiki content in it.

## What a healthy loop looks like

Candidates arrive a few times a week and are triaged within days. Most land as PRs of ten
lines or fewer; some are closed with one line saying why. The `needs-human` queue is short and
answered. Descriptions change when an eval case fails.

The signs that it is broken: candidates older than a month; agents reasoning wrongly about a
system the wiki maps; wiki knowledge turning up in someone's private memory or a repo-local
note; the Stop hook answered with `wiki: nothing new` almost every time, which means the
investigation signals are too broad.
