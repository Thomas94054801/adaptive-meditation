# PROGRAM004R — Mainline Integration and Validation Boundary

**Task:** `PROGRAM004R-MAINLINE-INTEGRATION-SDD`
**Type:** SDD only. No merge, no code, no tests, no CI, no packages, no PR #6.
**Purpose:** the smallest safe contract for merging the completed
Program003 → Program004 → Program004R stack into `main`, with native, device and
human validation kept explicitly separate.

Labels: **FACT** (read from the remote this round), **DECISION** (frozen),
**PROCEDURE** (what the later integration task executes), **NOT_RUN** (no
evidence exists, with the reason).

## 1. Remote preflight

**FACT — re-read on 2026-09-13.** Every value matches the accepted starting
state; no head has moved.

| Item | Value |
|------|-------|
| `origin/main` | `ec82f883701e6e7ae4fa94075c6bf541f70ae75c` |
| PR #3 | OPEN · head `a75b6ca1ccde1d2592dc588e9597ee93d0fadd7d` · base `main` @ `ec82f883` · `MERGEABLE` / `CLEAN` |
| PR #4 | OPEN · head `d1d06742a9f5506161559b7f79ee054fb80bf115` · base `main` @ `ec82f883` · `MERGEABLE` / `CLEAN` |
| PR #5 | OPEN · head `1f19170c199a6ab3170669dd37c31228c57e5bdb` · base `program004/core-adaptive-meditation-sdd` @ `d1d0674` · `MERGEABLE` / `CLEAN` |
| Reviews / threads | 0 reviews, 0 review threads, 0 unresolved, on all three |
| `mergedAt` / `mergeCommit` | null on all three — **nothing is merged** |

**FACT — synthetic refs, not merges.** `potentialMergeCommit` is #3 `4a37dfbe`,
#4 `727e89f8`, #5 `b9ca2f25`. These are trees GitHub computes for checks. They
are not on any branch and change whenever a base moves.

**FACT — repository merge settings.** `allow_merge_commit: true`,
`allow_squash_merge: true`, `allow_rebase_merge: true`,
`delete_branch_on_merge: false`. **`main` is not branch-protected**
(`GET /branches/main/protection` → 404). Two consequences: the merge-commit
method is available, and expected-head protection must come from the merge
command itself rather than from GitHub.

**FACT — CI per unchanged head**, by exact SHA:

| Head | push | pull_request |
|------|------|--------------|
| `a75b6ca1` (#3) | `34668439627` success | `34668441620` success |
| `d1d0674` (#4) | `34682972290` success | `34682973745` success |
| `1f19170c` (#5) | `34703156324` success | `34703158637` success |

Five distinct things, kept apart throughout: **branch HEAD** (the commit a PR
points at), **`main` HEAD**, **PR base SHA** (where the base ref was when
GitHub last computed it), **synthetic merge** (`potentialMergeCommit`), and
**actual merge commit** (none exists yet).

## 2. Stack ancestry

**FACT — verified with `git merge-base --is-ancestor`.** Strictly linear:

```
main  ec82f883
  └── a75b6ca1   Program003   (#3)    9 commits over main
        └── d1d0674   Program004   (#4)   10 commits over a75b6ca1
              └── 1f19170c  Program004R  (#5)   16 commits over d1d0674
```

`merge-base(main, 1f19170c)` = `ec82f883` — the whole stack sits on the current
`main` with no divergence. Program004R's device-independent state is
`DEVICE_INDEPENDENT_CLOSEOUT = COMPLETE`, `CODE_MERGE_READINESS = READY`,
`STORE_RELEASE_READINESS = BLOCKED`; 563 backend and 217 Flutter tests on
`1f19170c` in both CI runs above.

## 3. Evidence self-reference rule

**FACT.** The committed acceptance artefact on `1f19170c` records the CI runs
that existed when it was written. `1f19170c` itself then received push
`34703156324` and pull_request `34703158637`, both success. A commit cannot
contain evidence of a run that starts after it is pushed.

**DECISION.** That is not grounds for another evidence-only commit, closure
commit or SDD amendment. **Remote GitHub CI state is valid integration
evidence in its own right.** The loop *commit → CI → commit CI evidence → new
CI → commit again* is closed here: no stage below produces a code or docs
commit whose only content is a CI result.

## 4. Merge method

**DECISION — `MERGE_METHOD = merge commit`** for #3, #4 and #5, for the whole
sequence.

Forbidden: squash merge, rebase merge, cherry-pick reconstruction, force push,
history rewrite of any of the three branches.

Reason: the branches are stacked. A merge commit makes `a75b6ca1`, then
`d1d0674`, then `1f19170c` **ancestors of `main`**, so each later PR's diff
collapses to its own delta the moment its prerequisite lands. Squash or rebase
would replace those heads with new commits `main` does not share, and every
later PR would then present its prerequisites as fresh, unreviewed work.
Linear-looking history is not worth that.

**DECISION — expected-head protection on every merge.** Because `main` is
unprotected, each merge is executed with an explicit head match
(`gh pr merge <n> --merge --match-head-commit <sha>` or the equivalent REST
`sha` field). A merge whose head has moved must be refused by the command, not
noticed afterwards.

## 5. Integration sequence

Four stages, strictly ordered. Each stage's exit condition is the next stage's
entry condition. **PROCEDURE** throughout.

### I1 — merge Program003 (PR #3)

Preconditions: #3 OPEN; head == `a75b6ca1ccde1d2592dc588e9597ee93d0fadd7d`;
base == `main`; `MERGEABLE`; zero unresolved blocking review; head CI as in §1.

Action: merge #3 with a merge commit and expected head `a75b6ca1`.

After: read the **actual** merge SHA and the new `main` SHA; verify
`git merge-base --is-ancestor a75b6ca1 main`; wait for the **`main` push CI**;
require success.

Do not re-run #3's own CI to obtain a newer timestamp — the head is unchanged
and already proven. The `main` CI after the merge is the integration proof.

### I2 — merge Program004 (PR #4)

Only after I1's `main` CI is green.

Re-read #4. Required ancestry: `a75b6ca1` reachable from `main` (I1 did this),
`d1d0674` descends from `a75b6ca1` (§2). Verify the effective #4 diff against
`main` now shows only Program004's 10 commits — Program003 must no longer
appear as unintegrated work.

Action: merge #4 with a merge commit and expected head `d1d0674`.

After: read the actual merge SHA; verify `d1d0674` is an ancestor of `main`;
wait for `main` push CI; require success. Do not rewrite the Program004 branch.

### I3 — retarget Program004R (PR #5)

Only after I2's `main` CI is green.

**DECISION.** #5's base becomes `main`. **No replacement PR. No PR #6.**
Retargeting is a metadata change (`gh pr edit 5 --base main`) and produces no
commit.

After retargeting, verify: #5 head is still exactly `1f19170c`; `d1d0674` is an
ancestor of `main`; `merge-base(main, 1f19170c)` == the post-I2 Program004
boundary (the I2 merge commit or `d1d0674`, depending on how the merge commit's
parents resolve — either is consistent, and anything earlier is not).

Audit the retargeted #5 diff. It must contain **only** Program004R's 16 commits
above the integrated Program003/004 baseline, and must not reintroduce any file
change from #3 or #4 as duplicate work. A clean check:
`git diff --stat main...1f19170c` lists only Program004R's changes.

### I4 — merge Program004R (PR #5)

Only after the retargeted #5 pull_request CI (§6) is green.

Action: merge #5 with a merge commit and expected head
`1f19170c199a6ab3170669dd37c31228c57e5bdb`.

After: read the actual merge SHA and the new `main` SHA; verify `1f19170c` is
an ancestor of `main`; wait for `main` push CI; require success. **No further
evidence-only commit is required** (§3).

## 6. CI reuse policy

**DECISION.** Exactly four new CI executions are caused by integration, and no
others are run without cause:

| Stage | New CI | Why it is needed |
|-------|--------|------------------|
| I1 | `main` push CI after #3 merges | the merged tree has never run |
| I2 | `main` push CI after #4 merges | same |
| I3 | one pull_request CI for #5 against `main` | retargeting changes the synthetic merge tree; `34703158637` proved the *old* base and says nothing about a `main`-based merge |
| I4 | `main` push CI after #5 merges | same as I1 |

**Not re-run:** push CI on `a75b6ca1`, `d1d0674` or `1f19170c`. The heads are
immutable and already green; a newer timestamp is not newer evidence. No code
is changed merely to trigger a run.

## 7. PR #5 description hygiene

**FACT.** #5's body still describes the PARTIAL state from before the closeout.

**DECISION.** The integration task updates the PR body — a metadata edit, no
commit — to state: `DEVICE_INDEPENDENT_CLOSEOUT = COMPLETE`,
`CODE_MERGE_READINESS = READY`, push CI `34703156324` SUCCESS, the new
retargeted pull_request run id, the four device/listening axes `NOT_RUN`, and
`STORE_RELEASE_READINESS = BLOCKED`. Historical commits are not altered to
refresh prose.

## 8. Main-tree equivalence audit

**DECISION.** After I4, if no unrelated commit landed on `main` during the
sequence, the final `main` tree must be **identical** to the accepted #5 tree.
Merge commits add history, not content.

Required check, either form:

```
git diff --exit-code 1f19170c <final-main> --
git rev-parse 1f19170c^{tree} <final-main>^{tree}    # must print one hash twice
```

If the diff is non-empty, an unrelated change landed mid-sequence. **Do not
force through, do not rewrite history.** Recompute ancestry, inspect the actual
diff, and treat it as a legitimate integration blocker until it is understood.

## 9. Failure policy

**DECISION.** The integration task proceeds conditionally and spawns no
planning task. At every stage:

- preconditions pass → execute, validate, continue;
- a real conflict, unexpected SHA movement, unexpected diff, failed `main` CI
  or blocking review → diagnose; repair if the repair is bounded and changes
  no accepted product behaviour;
- a repair that would alter accepted behaviour → **stop with exact evidence**:
  the stage, the SHAs, the run id, the diff.

Not a reason to stop: device testing unavailable, human listening unavailable,
store identity unavailable. Those block **release**, not **integration**.

## 10. Native and device validation boundary

**DECISION — the five axes are unchanged and are not redefined.** `CI`,
`NATIVE_INTEGRATION`, `ANDROID_DEVICE`, `IOS_DEVICE`, `HUMAN_LISTENING`, each
`PASS` / `FAIL` / `NOT_RUN` / `BLOCKED`. Integration touches none of them
except `CI`, which it re-establishes on `main`.

After a successful I4, absent genuinely new evidence:

```
CI                 = PASS        (on the merged main)
NATIVE_INTEGRATION = NOT_RUN     (no simulator or emulator has run the audio path)
ANDROID_DEVICE     = NOT_RUN     (no Android SDK, no device)
IOS_DEVICE         = NOT_RUN     (Command Line Tools only, no device)
HUMAN_LISTENING    = NOT_RUN     (nobody has listened)

CODE_MAINLINE_INTEGRATION = COMPLETE
STORE_RELEASE_READINESS   = BLOCKED
```

These are compatible statements. Merged code on `main` and a shippable release
are different claims with different evidence, and this document does not let
the first be read as the second.

## 11. Minimal future physical-validation contract

**DECISION — defined here, not executed here.** No device farm, no hardware
lab, no new CI matrix, no third-party device service, no new package, no audio
instrumentation framework.

When one physical device per platform exists, run only the shipping product
path, on Android and on iOS:

1. launch a release-like build;
2. start one audible session;
3. opening bell audible;
4. speech guidance audible;
5. a real silence interval occurs, scheduled as media;
6. closing sequence completes;
7. an interruption pauses playback;
8. the interruption ending does **not** resume;
9. an explicit user resume works;
10. lock-screen and background behaviour match the policy;
11. completion is recorded only after media completion;
12. feedback saves locally;
13. an offline or failed POST leaves feedback `pending`;
14. a later successful foreground POST marks it `synced`.

`HUMAN_LISTENING` evidence covers only the currently enabled production
locale and voice — `en-US`, the device default voice — recorded by a person,
per device, dated. No future locale matrix is invented.

## 12. Resource budget

**This SDD:** one new document; 0 production, test, dependency, workflow or
migration changes.

**The later integration execution:** 0 new PRs, 0 expected code changes, 0 new
CI jobs, 0 new CI platforms, 0 device harnesses. New CI executions limited to
the four in §6.

**DECISION — branches are kept.** `program003/store-readiness`,
`program004/core-adaptive-meditation-sdd` and
`program004r/real-audio-durable-playback` are **not** deleted during
integration (`delete_branch_on_merge` is already `false`). They remain as audit
references until final `main` CI is green, the integration readback is
complete and the next program's baseline is established. Deleting them later
needs no SDD.

## 13. PROGRAM005 baseline rule

**DECISION.**

```
PROGRAM005_BASE = the verified final main after I1 + I2 + I4,
                  with its main push CI green
```

Program005 is not designed and not branched from any of the three stacked
branches. It branches from `main` only after I4's CI is green. This prevents a
fourth stacked layer.

## 14. Summary

**FACT.** Heads unchanged; ancestry strictly linear; all three heads green on
both CI events; merge commits permitted; `main` unprotected; no reviews or
threads; nothing merged.

**DECISION.** Merge commits only, with expected-head protection on every merge;
order I1 → I2 → I3 (retarget, no new PR) → I4; four new CI runs and no
re-runs of immutable heads; final tree must equal `1f19170c^{tree}`; failures
stop only when repair would change accepted behaviour; the five axes are
untouched and four stay `NOT_RUN`; branches kept; Program005 bases on the
verified final `main`.

**Disposition: `PROGRAM004R_MAINLINE_INTEGRATION_SDD_READY_FOR_REVIEW`.**
