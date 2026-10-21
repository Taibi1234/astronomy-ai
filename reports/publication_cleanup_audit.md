# Publication Cleanup Audit

**Date:** 2026-10-22 · **Scope:** repository hygiene for public release. No scientific change, no commit,
no push, nothing staged.

**Result:** the repository is clean of agent tooling residue and contains no credentials. One decision is
held for your approval: `HOME/` is now **excluded from Git**, but its 22 MB of local agent state is still on
disk. Deleting it is irreversible and it contains this session's transcript, so I did not destroy it.

---

## 1. Inventory change

| | Before | After |
|---|---:|---:|
| Tracked files | 26 | 26 |
| Untracked status entries | 50 | 56 files (all project) |
| Files visible to Git under `HOME/` | 601 | **0** (ignored) |
| Project-local `.claude/` config | untracked (ignored by a *global* rule) | ignored by a *repo* rule |
| Cache directories in tree | 4 | 0 |

`git status --short` no longer lists `HOME/` or `.claude/`. `git ls-files | grep -c HOME` → **0**, so no
home-directory content is tracked.

---

## 2. Deleted

All four were regenerable Python caches, already covered by `.gitignore`, containing no project source:

| Path | Size | Why safe |
|---|---:|---|
| `.pytest_cache/` | 8 KB | pytest run metadata, recreated on next run |
| `.ruff_cache/` | 251 KB | linter cache, recreated on next run |
| `scripts/__pycache__/` | 260 KB | compiled bytecode (`.pyc`) |
| `tests/__pycache__/` | 96 KB | compiled bytecode (`.pyc`) |
| **total** | **615 KB** | |

Nothing else was deleted. No source, test, report, figure, script, dataset, or historical artifact was
removed.

---

## 3. Retained, and why

| Path | Size | Decision |
|---|---:|---|
| `HOME/` (601 files) | 22 MB | **Retained on disk, excluded from Git.** See §4. |
| `.claude/settings.local.json` | 111 B | Local permission allowlist with an absolute path; now repo-ignored, left in place (harmless, machine-specific). |
| `reports/phase6_portfolio_readiness.md`, `reports/phase7_reliability_audit.md` | 55 KB | Historical audit evidence. Retained verbatim per the preservation rules, including their dated errata. |
| `reports/project_audit.md` | 15 KB | Contains the auditor attribution (`Kimi Code, automated audit pass`). Retained deliberately — see §7. |
| `data/processed/*.csv`, `data/raw/` | 12 MB | Unpublished working data, still ignored; publication decision belongs to the earlier manifest review, not to this cleanup. |
| `.venv/` | — | Local environment, ignored. |

---

## 4. `HOME/` — excluded, deletion pending approval

**What it is.** A redirected home directory created by the local assistant tooling, entirely unrelated to
the astronomy project:

```
HOME/.claude-omniroute/{backups, cache, file-history, paste-cache, plugins,
                        projects, session-env, sessions, shell-snapshots, telemetry}
HOME/.claude/omniroute
```

Largest items include a 1.8 MB `projects/C--Users-5CA-astronomy-ai/<uuid>.jsonl` — **this session's
conversation transcript** — plus `paste-cache/*.txt`, `sessions/`, `telemetry/`, and a plugin marketplace
cache.

**Why it is not published.** `.gitignore` now has `HOME/`, verified with
`git check-ignore -q HOME/.claude-omniroute/history.jsonl` → ignored. It cannot enter a commit by
accident through `git add -A`.

**Why it was not deleted.** It is not project data, but it *is* your local record of this session. Deleting
it is irreversible and could break tooling that may still hold open handles. Per the "list ambiguous items
and wait" rule, I stopped here.

**To delete it yourself (any time):**

```powershell
Remove-Item -Recurse -Force C:\Users\5CA\astronomy-ai\HOME
```

If you prefer to keep the history but clean the repo, move it outside the project instead:

```powershell
Move-Item C:\Users\5CA\astronomy-ai\HOME C:\Users\5CA\agent-state-backup
```

Either action leaves the published repository unchanged, because the directory is already ignored.

---

## 5. Ignore rules added

`.gitignore` grew by **13 lines**, no deletions (diff verified: `13 insertions(+)`). Existing rules — data
directories, `.env`, `.venv`, caches — were left intact. `reports/`, `tests/`, `scripts/` and the figures
remain fully committable; nothing scientific is ignored.

```diff
 .ruff_cache/
+.coverage
+htmlcov/
 ...
+# Agent / assistant tooling state (local only — never published)
+HOME/
+.claude/
+.kimi/
+.rea/
+*.code-workspace
+
+# OS / editor noise
+.DS_Store
+Thumbs.db
```

Two details: the file's UTF-8 BOM and its mixed line endings were preserved (the editor dropped the BOM on
first write; it was restored and the stray trailing `\r` normalised, so the diff is additions only), and
`git diff --check` exits **0** with no whitespace errors.

---

## 6. Private-information scan

**Credentials:** scanned 59 project text files (`.py`, `.md`, `.json`, `.toml`, `.txt`, `.example`, `.gitignore`)
for private-key blocks, AWS/GitHub/Slack/OpenAI/Google token formats, bearer headers, `password|secret|api_key=`
assignments and URLs with embedded credentials. **No matches.** No `.env` file exists in the project; the
`.env`/`.env.*` rules were already in place and are unchanged. No secret value appears in this report.

**Personal paths:** found `C:\Users\5CA\…` in five files.

| File | Action |
|---|---|
| `README.md` (2 lines) | Generalised to `cd C:\path\to\astronomy-ai` |
| `docs/reproducibility.md` (2 lines) | Path generalised; the hard-coded ruff binary location reworded to "installed outside `.venv`" |
| `.claude/settings.local.json` | Ignored, not published |
| `reports/phase6_portfolio_readiness.md:105`, `reports/phase7_reliability_audit.md:144` | **Retained** — historical audit output (`ruff` path, temp-dir path). Editing them would alter dated evidence for a cosmetic gain. Residual exposure is a local username fragment, no credential. |

**Local environment data:** `.venv/` ignored; no `.env`, no shell history, no logs, no agent session data
outside `HOME/`.

---

## 7. Remaining agent-tool references — classification

| Location | Content | Class |
|---|---|---|
| `reports/project_audit.md:4` | "Auditor: Kimi Code (automated audit pass, Phase 1)" | **(b) legitimate evidence.** Authorship/tooling disclosure. Removing it would misrepresent how the project was produced. |
| `reports/phase6_portfolio_readiness.md:35` | Notes that `HOME/` is an untracked tooling cache | **(b) legitimate** — historical observation of exactly the issue fixed here |
| `reports/final_repository_readiness.md` §1.2 | Documents why `HOME/` must not be committed | **(b) legitimate** — this is the audit that found it |
| `.claude/settings.local.json` | Local permission config | **(a) residue** — ignored, not published |
| `HOME/…` | Session state, plugin cache, transcripts | **(a) residue** — ignored, not published |

No scratch prompts, agent logs, temporary scaffolds, or tool-generated files remain inside the tracked or
committable set. No legitimate evidence was removed to eliminate mentions of AI tooling.

---

## 8. Preservation verification

Re-hashed after cleanup. **No mismatches.**

| Artifact | SHA-256 (first 16) | Status |
|---|---|---|
| `reports/results/phase3_transit_analysis.json` | `045073e20b7dcbfc` | unchanged |
| `reports/results/phase4_block_bootstrap.json` | `d4e2de41a674c7c8` | unchanged |
| `reports/results/phase4_injection_recovery.json` | `57b67864f5fd5187` | unchanged |
| `reports/results/phase4_model_comparison.json` | `a8183377dfe7443a` | unchanged |
| `reports/phase5_dataset.json` | `f8ad47fb2a404b41` | unchanged |
| `reports/phase5_features.csv` | `a2886bf9a47f2325` | unchanged |
| `reports/phase5_feature_config.json` | `417d614c5609aef7` | unchanged |
| `reports/phase5_results.json` | `a22734583ecc36fc` | unchanged |
| `reports/phase5_results.md` | `8443a7b5cf1de2a2` | unchanged |
| `reports/phase5_audit.md` | `b1b5e2cc467ed509` | unchanged |

Publication CSVs (still ignored, unpublished): all 5 match the Phase 7 manifest hashes.

Test suite after cleanup: **28 passed**, exit 0.

---

## 9. Git state

```
 M .gitignore                     (+13 lines: agent state, coverage, OS noise)
 M requirements-lock.txt          (Phase 6 batman-package pin, unchanged here)
?? README.md   ?? docs/   ?? tests/
?? reports/… (33 files incl. figures, results, phase 3–8 reports)
?? scripts/…  (17 files)
```

- **Staged:** nothing (`git diff --cached` empty).
- **HEAD:** `21bf6e2` — unchanged, two commits total.
- **`git diff --check`:** exit 0, no whitespace errors (one benign `LF will be replaced by CRLF` notice from
  `core.autocrlf=true`).
- **`HOME/` contents staged:** none. **Private credentials staged:** none.

---

## 10. Remaining risks

| # | Risk | Severity | Status |
|---|---|---|---|
| P1 | `HOME/` still occupies 22 MB on disk and contains this session's transcript | **Medium** (privacy, not publication) | Excluded from Git; deletion awaits your approval (§4) |
| P2 | Historical reports expose a local username fragment in two paths | **Low** | Documented; left for evidence integrity |
| P3 | `pytest` at repo root still exits 2 (`pyproject.toml` is protected, `testpaths` not added) | **Medium** (first impression) | Outside this task; two-line manual fix |
| P4 | Processed CSVs remain unpublished; redistribution terms unconfirmed | **Medium** | Deliberate; separate decision |
| P5 | `scripts/statistical_validation.py` still calls four undefined helpers | **Low** | Dead code, documented in Phase 7/8 audits |

None of these requires changing a scientific result or deleting evidence.

---

## 11. Recommendation

**Ready to publish the code, docs and reports** — the committable set is free of agent state, credentials and
machine paths, and every scientific artifact is byte-identical to its audited value.

**Before the first commit:** approve `HOME/` disposition (§4) and add the two-line pytest `testpaths` block.
The ignore rule already prevents the worst outcome (`HOME/` in a public repo); the remaining steps are
hygiene, not risk mitigation.

**Stopped for review.** Nothing staged, committed, or pushed. No ambiguous file was deleted.

---

### Appendix — proposed committable scope

57 files, ≈2.36 MB: 2 modified tracked files (`.gitignore`, `requirements-lock.txt`), 17 scripts, 3 test
files, 2 docs, `README.md`, and 34 report/result/figure files (10 of them Phase 3 figures, 2.0 MB).
Complete listing: `git ls-files --others --exclude-standard`
