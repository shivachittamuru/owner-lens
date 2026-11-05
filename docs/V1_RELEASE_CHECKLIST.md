# OwnerLens — v1.0.0 Freeze and v2 Kickoff Checklist (Windows PowerShell)

**Prepared:** Nov 3, 2026  
**State:** **NOT PERFORMED** on the owner's local repo. This is a safe, concrete procedure. Tagging must occur in the local checkout with the exact verified code and data environment.

## 1. What “v1 stable” honestly means

- Core Features 1–10 and five product cleanups implemented according to developer/user reports.
- Code/test baseline can be reproduced at a Git commit and immutable annotated Git tag.
- Regression tests and static checks run on that code.
- Crucial **read-only** daily research workflows receive real persisted FMP smoke validation.
- Advanced 9C/9D/10 functionality **may remain fixture-tested and not live validated**; disclose this, do not fabricate activity.
- **Git tags are source-code checkpoints, not database snapshots.** Save investment data separately.
- The v1 label does **not** certify investment performance, universal universe coverage, stable external API or investment advice.

## 2. Verify which checkout you are freezing

From **PowerShell inside** `C:\Users\shchitt\Downloads\Projects\owner-lens` (adjust if moved):

```powershell
pwd
git remote -v
git branch --show-current
git status --short
git log -1 --format="%h %ci %s"
git tag --list "v1*"
```

Review any uncommitted implementation work, including the provider-widget warning fix, which was **not confirmed complete in the conversation**. Do not tag until you decide whether it is included in v1. Any untracked real-world data, `.env`, secrets, SQLite files or generated provider snapshots should be appropriately ignored and should **not** be committed as part of the freeze.

**If there is an unfinished large feature, do not rush to include it in v1.** Close/test or deliberately defer it and document the exact baseline.

## 3. Establish and record the release baseline

Run against the chosen local checkout:

```powershell
uv sync
uv run pytest -q
uv run ruff check .
uv run mypy src
git diff --check
```

Record the exact outcome, Python version and commit SHA (do **not** blindly put old reported `1,725 passed` in the release notes; it was last reported after Cleanup 5, not independently rerun for this release):

```powershell
uv run python --version
git rev-parse HEAD
```

Expected historical reference: 1,725 tests passed and Ruff/mypy/whitespace passed after Cleanup 5, **not** a guarantee of the present run. If any command fails, diagnose before tagging. If tests are later added, the new count can legitimately differ.

### Basic production-data read-only smoke checks

Do not mix read-only checks with provider refresh. Ensure the configured store contains the intended FMP S&P 500 data and that Workbench opening does not issue HTTP calls:

```powershell
uv run owner-lens screen --provider fmp
uv run owner-lens screen --provider fmp --detail
uv run owner-lens workbench --provider fmp
```

Inside Workbench:
- **Discover/Screener:** actual current persistable company list, six dimensions, reasons, missing/coverage states and quality gates behave sensibly; distinguish historical data vintage.
- **Company:** choose a completed underwriting such as ADBE, NOW, MSFT or GOOGL; verify frozen price/date, Investment View and Copy Research Context; do not write fake underwriting simply to test.
- **Opportunity Comparison:** select 2–5 eligible companies; check latest complete frozen versions, each hurdle and dates; `Compare this underwriting` handoff preserves identity, no write on browsing.
- **Decision record:** the real META:1 ADD approval previously reported can be inspected but no new dummy real decision should be created.
- **Portfolio/Monitor/Outcomes:** note fixture-only or unvalidated if not actually exercised. Especially **do not paste the synthetic 9D ADBE sample into the real investment store**.
- Note whether `provider` selectbox warning recurs; fix separately if it materially affects the stable baseline, then rerun checks.

Write a short human-readable note about what was checked, what was skipped and what is known to fail. Do not conflate *manual smoke-tested* with *all behavior live validated*.

## 4. Back up the actual local investment store, not just Git

Before release, preserve the configured SQLite data and any external/manual input artifacts needed for reproduction. Identify the store from environment/CLI; the default may be `data/ownerlens.db`, but **do not assume that's the active FMP store**. Do not commit a DB, credentials, raw FMP payloads with licensing restrictions, or personal portfolio data to GitHub.

For a chosen SQLite path, create a consistent Python SQLite backup outside the repository:

```powershell
# Replace the source with the actual configured database path before running.
$Db = "data/ownerlens.db"
$BackupDir = Join-Path $HOME "OwnerLens-backups"
New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$Target = Join-Path $BackupDir "ownerlens-v1-$Stamp.db"
@'
from pathlib import Path
import sqlite3, sys
src, target = map(Path, sys.argv[1:3])
if not src.is_file():
    raise SystemExit(f"No such database: {src}; select the actual active store first")
with sqlite3.connect(src.as_posix()) as a, sqlite3.connect(target.as_posix()) as b:
    a.backup(b)
with sqlite3.connect(target.as_posix()) as b:
    print("Backup integrity:", b.execute("PRAGMA integrity_check").fetchone()[0])
print("Backup:", target)
'@ | uv run python - "$Db" "$Target"
```

**Only after verifying the path and backup integrity**, record the backed-up source path, backup file name and date in private release notes. Consider encrypted/offline storage for sensitive real portfolio data.

## 5. Commit code and tag the exact tested commit

**Option A — current code already committed and clean:** use its `HEAD` as v1 baseline.  
**Option B — uncommitted v1 fixes remain:** review the diff, stage only intended source/docs/tests, commit, **rerun checks on that commit**, then tag.

```powershell
# Inspect before making any commit.
git status --short
git diff --stat
git diff --check

# If there are intended, reviewed v1 changes:
# git add <specific-source-or-test-paths>
# git commit -m "chore: finalize OwnerLens v1 baseline"

# Must be clean for a transparent release.
git status --porcelain
git rev-parse HEAD
git tag --list "v1.0.0"
```

**Do not force-update or overwrite an existing `v1.0.0` tag.** If that name exists, inspect it, compare SHA to intended baseline, and choose a new appropriate patch release (e.g., `v1.0.1`) only after deciding what changed.

If no v1 tag exists and the baseline is verified:

```powershell
$Baseline = git rev-parse HEAD
git tag -a v1.0.0 $Baseline -m "OwnerLens v1 - verified research foundation and product cleanups"
git show --no-patch --format=fuller v1.0.0
git push origin HEAD
git push origin refs/tags/v1.0.0
```

Review Git remote permissions and branch protection before push. An annotated tag points at **a code commit**, not the unsaved/ignored local SQLite store.

## 6. Where the new v2 documents belong relative to the tag

**Preferred clean history:**

1. Freeze/tag the tested v1 code baseline (as above).
2. Copy the files from this handoff package into your repo's `docs/` directory and put the package root README in a suitable repo docs entry point (e.g., `docs/OWNERLENS_V2_START_HERE.md`).
3. Review that the docs reflect the actual frozen commit; adjust any stale paths/counts.
4. Commit the documentation as the **first v2 planning-only commit**. Do not fold new discovery engine code into it.
5. Start the new thread and run the read-only Discovery Audit.

This keeps `v1.0.0` a pure baseline. It is also reasonable to include reviewed release documentation inside the tag if you choose that boundary *before* tagging; whichever approach is chosen, record it explicitly and don't silently move tags.

Example v2 kickoff after tag:

```powershell
# Copy docs from the downloaded package first.
git status --short
git add docs/PRODUCT_CONTEXT.md docs/ROADMAP_V2.md docs/INVESTMENT_DECISION_PLAYBOOK.md docs/DECISIONS_AND_BACKLOG.md docs/V1_RELEASE_CHECKLIST.md docs/DISCOVERY_AUDIT_BRIEF.md docs/V2_WORKING_PROMPT.md
git diff --cached --stat
git diff --cached --check
git commit -m "docs: establish OwnerLens v2 discovery-first strategy"
git push origin HEAD
```

The docs-only commit does not itself establish v2.0.0. No permanent `v2` branch required; use small short-lived branches for actual experiments as appropriate.

## 7. Release note template (fill from real outputs)

```text
OwnerLens v1.0.0 baseline
Date (local): <YYYY-MM-DD>
Git ref: <full SHA>
Tag: <name and SHA>
Branch / origin remote: <...>
Python / uv: <...>
Tests: <exact passed/failed/skipped> (run on ref above)
Ruff: <result>
Mypy: <result>
Diff whitespace: <result>
FMP store: <path, provider data vintage, company count, not checked into Git>
SQLite backup: <private path and integrity check>

Live smoke tested:
- Feature 7 Screener: <...>
- Company Investment View: <...>
- Underwriting JSON-first / exact retry: <...>
- Opportunity Comparison: <...>
- 9B real decision receipt: <...>

Not independently live validated:
- Full 9C sizing workflow: <...>
- 9D condition-event approval: <...>
- Feature 10 outcome/calibration/attribution: <...>

Open known issues:
- Streamlit provider widget warning: <fixed/unfixed/not checked>
- 9D generic sample JSON vs exact frozen condition: input authoring friction (deferred)
- Dense comparison and UI glossary: deferred

Next milestone: read-only Discovery Audit; no new features approved yet.
```

## 8. Verification and recovery

```powershell
git rev-parse v1.0.0^{commit}
git ls-remote --tags origin "v1.0.0*"
git status --short
```

PowerShell may treat the `^{commit}` syntax unexpectedly in some contexts; quote it if necessary: `git rev-parse 'v1.0.0^{commit}'`.

If something fails after tagging, do **not** rewrite a published annotated tag. Fix on a new commit and make a versioned patch tag or document the known issue transparently. Your SQLite backup is distinct from the Git rollback mechanism.

## 9. Start v2

Open a new conversation named **OwnerLens-v2**. Attach or link the docs and paste `V2_WORKING_PROMPT.md`. Make the first task the **read-only Discovery Audit** in `DISCOVERY_AUDIT_BRIEF.md`.

**Stop point:** Do not implement M2 screening changes, broaden FMP companies, migrate React or build new portfolio monitoring until the audit reveals a concrete high-value hypothesis.
