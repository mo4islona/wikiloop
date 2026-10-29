---
name: wiki-shepherd
description: >-
  Run the wiki inbox without a person at each step: review open PRs, apply fixes, merge what passes, land accepted candidates, triage new ones. Use for "shepherd the wiki", "clear the PR queue", "run the wiki inbox".
owner: wikiloop
last-verified: {{core.released}}
generated: wikiloop
---

# Shepherd the wiki inbox

Input: the open PRs and `{{inbox.label}}` issues of `{{inbox.repo}}`. Output: each PR that is
not a draft is merged, waits for its next step, or carries `needs-human` with the question
for the person; each accepted candidate is in a PR. One call runs passes (read the state,
act) until only waits are left, then reports once. The rules for content stay in
`wiki-pr-review`, `wiki-contribute` and `wiki-triage`; this skill only orders the steps and
holds the merge gate. Running this loop is the "when asked" that `wiki-pr-review` needs before
a merge, and the confirmation that `wiki-triage` asks per pass.

## Invariants

- **Drafts are never touched.** No review, no comment, no label.
- **The reviewer is not the author.** Each review is a fresh subagent that gets the PR number
  and the prompt in [prompts.md](references/prompts.md), nothing from the session that wrote
  or fixed the PR. It reads only and posts nothing; the run posts its result.
- **State lives on GitHub.** Each review result is a PR comment that starts with
  `<!-- shepherd round=N verdict=V sha=SHA -->`; `needs-human` parks a PR. A new session
  continues from the comments, not from memory.
- **Merge only on `merge` at the current head, with checks green.** At most
  {{shepherd.max_rounds}} review rounds for each head that a person or author pushed; then
  `needs-human`.
- **No history rewrite.** A fix is a new commit on the PR branch; a conflict is a merge of
  `origin/main` into the branch; the PR lands as a squash merge.
- **One owner of the working tree.** While reviewers run, the checkout stays on `main`: they
  grep it as `main`. Fixes, merges and the lander run one at a time, after the reviews.
- **The person decides what a reviewer cannot verify.** `block` (an unsourced claim, a
  contradiction of a sourced wiki sentence, a `description` change with no trigger eval, a fix
  that needs the author's knowledge), `close`, and a fix larger than another author's PR all
  become `needs-human` and one comment that names the decision.

## Procedure

1. Start clean: `git checkout main && git pull --ff-only`, then

   ```
   python3 {{core.path}}/bin/wikiloop shepherd
   ```

   It prints one action per PR or candidate, most urgent first: `merge`, `apply`, `rebase`,
   `review`, `escalate`, `land`, `triage`, then the waits. Do steps 2-7 for the lines that
   apply, then run it again (step 8).

2. **review**: start one reviewer for each `review` line, all in one message, with the round-1
   prompt (round 2 when the plan says so; give it the last shepherd comment). Wait for all.
   Post each result: `gh pr comment N --body-file <file>`, the marker line first, with the
   head SHA that the reviewer read. Verdict `block` or `close`: also
   `gh pr edit N --add-label needs-human`. If the round-1 reviewer still runs in this session,
   send it round 2 instead: it already holds the evidence.

3. **apply** and **rebase**, one PR at a time:
   - `git checkout -B <branch> origin/<branch>`; on a conflict, `git merge origin/main` and
     resolve it as the review says, or keep `main`'s text and add the PR's new sentences.
   - Apply each finding's OLD/NEW exactly: `python3 {{core.path}}/bin/wikiloop apply pairs.json`
     fails unless each OLD matches once.
   - `python3 {{core.path}}/bin/wikiloop build` and `python3 {{core.path}}/bin/wikiloop lint`.
   - Commit the fixes as one commit (subject `wiki(<skill>): <what was wrong>`, a body only
     for the why), `git push`, `git checkout main`. The next pass reviews the new head.

4. **merge**: `gh pr merge N --squash --subject "<PR title> (#N)" --body <trailers>`, with a
   `Co-authored-by:` line for each other author of the PR's commits. After the last merge of
   the pass: `git pull --ff-only`, `wikiloop build --check`, `wikiloop lint`; a red `main`
   stops the run.

5. **escalate**: `needs-human` and one comment with the `verdict=escalate` marker,
   `Decision needed:` and the options in one line each. Do not ask again while the head stays
   the same; a push or a person who removes the label puts the PR back in `review`.

6. **land**: when no PR from the loop is open yet (branch `wiki/land-*`), start one lander
   with the land prompt and every `land` line, plus the defects that reviewers found outside
   their PR. It opens at most {{shepherd.max_land_prs}} PRs grouped by skill and does not merge
   them; they enter `review` at the next pass. Each candidate it skips gets `needs-human` and
   its one-line reason as a comment.

7. **triage**: new candidates go through `wiki-triage` steps 2-5. Apply the labels and closes
   without the per-pass confirmation, then report them.

8. Run the plan again. Continue while it prints an action that is not a wait. For
   `wait-checks`, wait with `gh pr checks N --watch` first. Stop when only `wait-*` lines or
   `nothing to do` are left, or when a pass changed nothing.

9. Report once, at the end: one table with number, action, result, and for `needs-human` the
   decision asked. Then the counts: merged, waiting, parked for a person.

## Pace and cost

A review costs about as much as a manual one; a round-2 check in the same session costs
cents. A run over an empty inbox is one plan call. Under `/loop`, follow a run that ends with
only waits with a long wait (30 minutes or more). Reviewers return only their verdict block,
so the run's own context stays short.
