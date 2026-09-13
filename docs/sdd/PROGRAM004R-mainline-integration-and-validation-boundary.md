# PROGRAM004R — Mainline Integration and Validation Boundary

**Task:** `PROGRAM004R-MAINLINE-INTEGRATION-SDD` (revised by FIX1)
**Type:** SDD only. No merge, no code, no tests, no CI, no packages, no PR #6.
**Purpose:** the smallest safe contract for merging the Program003 →
Program004 → Program004R stack into `main`, with native, device and human
validation kept separate.

Labels: **FACT** (read from the remote), **DECISION** (frozen), **PROCEDURE**
(executed by the later task), **NOT_RUN** (no evidence, with the reason).

## 1. Remote preflight

**FACT — re-read on 2026-09-13.** Every value matches the accepted starting
state.

| Item | Value |
|------|-------|
| `origin/main` | `ec82f883701e6e7ae4fa94075c6bf541f70ae75c` |
| PR #3 | OPEN · head `a75b6ca1ccde1d2592dc588e9597ee93d0fadd7d` · base `main` @ `ec82f883` · `MERGEABLE` / `CLEAN` |
| PR #4 | OPEN · head `d1d06742a9f5506161559b7f79ee054fb80bf115` · base `main` @ `ec82f883` · `MERGEABLE` / `CLEAN` |
| PR #5 | OPEN · head **moves with each docs commit to this branch** (see §2A) · base `program004/core-adaptive-meditation-sdd` @ `d1d0674` · `MERGEABLE` / `CLEAN` |
| Reviews · merges | 0 reviews, 0 threads on all three; `mergedAt`/`mergeCommit` null — **nothing merged** |

**FACT — synthetic refs, not merges.** `potentialMergeCommit` (#3 `4a37dfbe`,
#4 `727e89f8`, #5 `b9ca2f25`) are check trees GitHub computes; not on any
branch, and they change whenever a base moves.

**FACT — merge settings.** `allow_merge_commit`, `allow_squash_merge` and
`allow_rebase_merge` are all `true`; `delete_branch_on_merge` is `false`;
**`main` is not branch-protected** (404). So merge commits are available, and
expected-head protection must come from the merge command, not from GitHub.

**FACT — CI per head**, by exact SHA:

| Head | push | pull_request |
|------|------|--------------|
| `a75b6ca1` (#3) | `34668439627` success | `34668441620` success |
| `d1d0674` (#4) | `34682972290` success | `34682973745` success |
| `1f19170c` (#5) | `34703156324` success | `34703158637` success |

Kept apart throughout: **branch HEAD**, **`main` HEAD**, **PR base SHA**,
**synthetic merge** (`potentialMergeCommit`), **actual merge commit** (none yet).

## 2. Stack ancestry

**FACT — verified with `git merge-base --is-ancestor`.** Strictly linear:

```
main  ec82f883
  └── a75b6ca1   Program003   (#3)    9 commits over main
        └── d1d0674   Program004   (#4)   10 commits over a75b6ca1
              └── 1f19170c  Program004R  (#5)   16 commits over d1d0674
```

`merge-base(main, 1f19170c)` = `ec82f883`: the stack sits on current `main`
with no divergence. Program004R: `DEVICE_INDEPENDENT_CLOSEOUT = COMPLETE`,
`CODE_MERGE_READINESS = READY`, `STORE_RELEASE_READINESS = BLOCKED`; 563
backend and 217 Flutter tests on `1f19170c` in both runs above.

### 2A. Two heads, deliberately different

Committing this document to PR #5's branch moved the PR head — expected, and
exactly why a merge contract must not hard-code the head it will merge.

**DECISION — `ACCEPTED_EXECUTABLE_HEAD = 1f19170c199a6ab3170669dd37c31228c57e5bdb`.**
The commit whose device-independent behaviour was accepted and CI-green. It is
the reference for executable equivalence, implementation provenance, test
evidence and dependency provenance. It is **not** the expected head of the
future PR #5 merge.

**DECISION — `PR5_INTEGRATION_HEAD`** is the exact remote head of PR #5, read
immediately before I3 and frozen for the rest of I3 and I4:

```
PR5_INTEGRATION_HEAD="$(gh pr view 5 --json headRefOid --jq .headRefOid)"
```

Never written into this document; every I3/I4 assertion uses the captured value.

**PROCEDURE — docs-only delta gate, before I3:**

```
git diff --name-only 1f19170c199a6ab3170669dd37c31228c57e5bdb "$PR5_INTEGRATION_HEAD"
```

At this revision the permitted delta is exactly this document. Production,
tests, assets, dependencies, backend migrations, CI, scripts and contracts must
all be **unchanged**. Anything outside that is inspected and classified, never
merged silently; anything altering accepted executable behaviour stops
integration with exact evidence.

## 3. Evidence self-reference rule

**FACT.** The acceptance artefact on `1f19170c` records the runs that existed
when written; `1f19170c` itself then received push `34703156324` and
pull_request `34703158637`, both success. A commit cannot contain evidence of
a run that starts after it is pushed.

**DECISION.** Not grounds for another evidence-only commit, closure commit or
amendment. **Remote CI state is valid integration evidence in its own right.**
No stage below produces a commit whose only content is a CI result; the
*commit → CI → commit evidence → CI* loop is closed here.

## 4. Merge method

**DECISION — `MERGE_METHOD = merge commit`** for #3, #4 and #5, for the whole
sequence.

Forbidden: squash merge, rebase merge, cherry-pick reconstruction, force push,
history rewrite of any of the three branches.

Reason: the branches are stacked. A merge commit makes each head an
**ancestor of `main`**, so every later PR's diff collapses to its own delta the
moment its prerequisite lands. Squash or rebase would replace those heads with
commits `main` does not share, and each later PR would then present its
prerequisites as fresh, unreviewed work.

**DECISION — expected-head protection on every merge.** `main` is unprotected,
so each merge passes an explicit head (`gh pr merge <n> --merge
--match-head-commit <sha>` or the REST `sha` field). A moved head is refused by
the command, not noticed afterwards.

## 5. Integration sequence

Four stages, strictly ordered; each exit condition is the next entry
condition. **PROCEDURE** throughout.

### I1 — merge Program003 (PR #3)

Preconditions: #3 OPEN; head == `a75b6ca1ccde…`; base == `main`; `MERGEABLE`;
no unresolved blocking review; head CI as in §1.

Action: merge #3 with a merge commit and expected head `a75b6ca1`.

After: read the **actual** merge SHA and new `main`; verify
`merge-base --is-ancestor a75b6ca1 main`; wait for `main` push CI; require
success.

#3's own CI is not re-run for a newer timestamp; the post-merge `main` CI is
the integration proof.

### I2 — merge Program004 (PR #4)

Only after I1's `main` CI is green.

Re-read #4. Required: `a75b6ca1` reachable from `main` (I1), `d1d0674`
descends from `a75b6ca1` (§2), and the effective #4 diff against `main` shows
only Program004's 10 commits — Program003 no longer appears as unintegrated
work.

Action: merge #4 with a merge commit and expected head `d1d0674`.

After: read the actual merge SHA; verify `d1d0674` is an ancestor of `main`;
wait for `main` push CI; require success. The Program004 branch is not
rewritten.

### I3 — retarget Program004R (PR #5)

Only after I2's `main` CI is green.

**DECISION.** #5's base becomes `main` via `gh pr edit 5 --base main` — a
metadata change, no commit. **No replacement PR. No PR #6.**

Before retargeting: capture `PR5_INTEGRATION_HEAD` (§2A) and run the docs-only
delta gate. After retargeting, re-read #5 and require **head ==
`PR5_INTEGRATION_HEAD`** and **base == `main`**. A head that moved during
retargeting is a concurrency blocker, not something to re-capture and continue.

**Merge-base invariant.** After I2, `d1d0674` is an ancestor of both post-I2
`main` and `PR5_INTEGRATION_HEAD`; the I2 merge commit is an ancestor of `main`
only, never inserted into the #5 branch. Therefore:

```
git merge-base "$POST_I2_MAIN" "$PR5_INTEGRATION_HEAD"
```

must equal **`d1d06742a9f5506161559b7f79ee054fb80bf115`**, exactly. A docs-only
descendant of the #5 head does not change it; only a commit that altered #5's
ancestry could, and that is inspected first.

Audit `git diff --stat main..."$PR5_INTEGRATION_HEAD"`: only Program004R's
commits plus this SDD, above the integrated Program003/004 baseline.
Program003 and Program004 must not reappear as fresh changes — the actual
reason merge commits are required (§4).

### I4 — merge Program004R (PR #5)

Only after the retargeted #5 pull_request CI (§6) is green.

Action:

```
gh pr merge 5 --merge --match-head-commit "$PR5_INTEGRATION_HEAD"
```

or the REST equivalent with the same `sha`. A head that moved after capture
is not merged: re-read the delta, classify it. A newer head is never accepted
automatically.

After: read the actual merge SHA and the new `main` SHA; verify
`PR5_INTEGRATION_HEAD` (and therefore `1f19170c`) is an ancestor of `main`;
wait for `main` push CI; require success. **No further evidence-only commit is
required** (§3).

## 6. CI reuse policy

**DECISION — four mandatory integration gates.** Requirements, not a promise
that GitHub creates exactly four runs: platform-generated extras are allowed,
recorded separately, and not a scope violation. No run is created by hand for
a newer timestamp.

| Gate | Required run | Why it is needed |
|------|--------------|------------------|
| G1 | `main` push CI after #3 merges | the merged tree has never run |
| G2 | `main` push CI after #4 merges | same |
| G3 | pull_request CI for #5 against `main`, on `PR5_INTEGRATION_HEAD` | retargeting changes the synthetic merge tree; the old base's run says nothing about a `main`-based merge |
| G4 | `main` push CI after #5 merges | same as G1 |

**FACT — the workflow sets `cancel-in-progress: true`.** A run superseded by a
newer push to the same ref is `cancelled`; that is not a failing candidate.
Acceptance binds to the **latest** required run for the immutable tree or ref,
and cancelled obsolete trees are not re-run.

**Not re-run:** push CI on `a75b6ca1`, `d1d0674` or the captured #5 head —
immutable and already green; a newer timestamp is not newer evidence. No code
is changed merely to trigger a run.

## 7. PR #5 description hygiene

**FACT.** #5's body still describes the pre-closeout PARTIAL state.
**DECISION.** The integration task updates the body — metadata only, no
commit — to state `DEVICE_INDEPENDENT_CLOSEOUT = COMPLETE`,
`CODE_MERGE_READINESS = READY`, push CI `34703156324` SUCCESS, the G3 run id,
the four device/listening axes `NOT_RUN`, `STORE_RELEASE_READINESS = BLOCKED`.
No historical commit is altered to refresh prose.

## 8. Main-tree equivalence audit

Two independent audits. Comparing final `main` against `1f19170c^{tree}` would
be wrong: that equality stopped holding when this document was committed to
PR #5. Merge commits change history, not checked-out content.

**Audit 1 — accepted executable equivalence (before I4).** The range
`ACCEPTED_EXECUTABLE_HEAD → PR5_INTEGRATION_HEAD` contains no executable,
test, asset, dependency, schema or CI change; at this revision it is docs-only
(§2A). This proves the code being integrated is still the accepted one.

**Audit 2 — final merge tree (after I4).** If no unrelated content commit lands
on `main` between I2 validation and the I4 merge:

```
git rev-parse "$PR5_INTEGRATION_HEAD^{tree}" "$FINAL_MAIN^{tree}"   # one hash, twice
```

The final `main` tree legitimately includes this SDD.

**Concurrent `main` change** is not an automatic failure. If `main` moves after
I2: identify the commit, classify its paths, recompute the merge-base, inspect
#5's effective diff, decide whether it conflicts. Non-conflicting with a green
G3 against the new state may continue. Stop only on a merge conflict, a change
to accepted behaviour, an ambiguous delta, a failed gate, or lost expected-head
integrity. Never rewrite history to restore an old tree hash.

## 9. Failure policy

**DECISION.** Proceed conditionally; spawn no planning task. Preconditions
pass → execute, validate, continue. A real conflict, unexpected SHA movement,
unexpected diff, failed gate or blocking review → diagnose; repair only if
bounded and behaviour-preserving. A repair that would alter accepted behaviour
→ **stop with exact evidence** (stage, SHAs, run id, diff). Unavailable device
testing, human listening or store identity block **release**, not
**integration**.

## 10. Native and device validation boundary

**DECISION — the five axes are unchanged and not redefined** (`PASS` / `FAIL` /
`NOT_RUN` / `BLOCKED` each). Integration touches only `CI`, which it
re-establishes on `main`. After a successful I4, absent new evidence:

```
CI                 = PASS        (on the merged main)
NATIVE_INTEGRATION = NOT_RUN     (no simulator or emulator has run the audio path)
ANDROID_DEVICE     = NOT_RUN     (no Android SDK, no device)
IOS_DEVICE         = NOT_RUN     (Command Line Tools only, no device)
HUMAN_LISTENING    = NOT_RUN     (nobody has listened)

CODE_MAINLINE_INTEGRATION = COMPLETE
STORE_RELEASE_READINESS   = BLOCKED
```

Compatible statements: merged code and a shippable release are different
claims with different evidence.

## 11. Minimal future physical-validation contract

**DECISION — defined here, not executed here.** No device farm, hardware lab,
new CI matrix, third-party device service, new package or audio
instrumentation framework. With one physical device per platform, run only the
shipping product path, on Android and on iOS:

1 launch a release-like build · 2 start one audible session · 3 opening bell
audible · 4 speech audible · 5 a real silence interval, scheduled as media ·
6 closing sequence completes · 7 an interruption pauses · 8 its end does
**not** resume · 9 explicit user resume works · 10 lock-screen/background
match policy · 11 completion recorded only after media completion ·
12 feedback saves locally · 13 an offline or failed POST leaves it `pending` ·
14 a later successful foreground POST marks it `synced`.

`HUMAN_LISTENING` covers only the enabled production locale and voice —
`en-US`, device default — recorded by a person, per device, dated. No future
locale matrix is invented.

## 12. Resource budget

**This SDD:** one document; 0 production, test, dependency, workflow or
migration changes. **The later execution:** 0 new PRs, 0 expected code
changes, 0 new CI jobs or platforms, 0 device harnesses; required CI limited
to the four gates in §6.

**DECISION — branches are kept** (`delete_branch_on_merge` is `false`): audit
references until final `main` CI is green, readback is complete and the next
baseline is set. Deleting them later needs no SDD.

## 13. PROGRAM005 baseline rule

**DECISION.**

```
PROGRAM005_BASE = the verified final main after I1 + I2 + I4,
                  with its main push CI green
```

Program005 branches from `main` only after I4's CI is green — never from a
stacked branch, so there is no fourth layer.

## 14. Summary

**FACT.** Ancestry strictly linear; all heads green on both CI events; merge
commits permitted; `main` unprotected; no reviews or threads; nothing merged.

**DECISION.** Merge commits only with expected-head protection;
`ACCEPTED_EXECUTABLE_HEAD` = `1f19170c`, `PR5_INTEGRATION_HEAD` captured at
execution and never hard-coded; I1 → I2 → I3 (retarget, no new PR) → I4; four
mandatory gates, not an exact run count; post-I2 merge-base is exactly
`d1d0674`; final `main` tree equals `PR5_INTEGRATION_HEAD^{tree}`; unrelated
`main` movement is classified, not auto-failed; five axes untouched, four stay
`NOT_RUN`; branches kept; Program005 bases on the verified final `main`.

**Disposition: `PROGRAM004R_MAINLINE_INTEGRATION_SDD_READY_FOR_REVIEW`.**
