# Changelog — jobmatch

One line per change, newest first. The `/roadmap-task` skill appends a sentence here after
each completed roadmap task. The plan lives in `ROADMAP.md`; the rationale in `PROJECT.md`.

## 2026-08-08
- Fixed Slovak worktype/employment-type extraction: patterns matched only undeclined
  "práca z domu" and the mis-spelled "úvazok", so everyday phrasings ("ponúkame prácu
  z domu", "plný úväzok") were missed. On the current 2375-job corpus this newly parses
  employment type for 739 jobs and worktype for 131.
- Explicitly partial work-from-home ("50% práce z domu", "občasnú prácu z domu") now
  classifies as hybrid instead of fully remote, and hybrid outranks remote in priority.
  Corpus goes from remote 1354 / hybrid 30 to remote 861 / hybrid 523 — the old split
  was inflating scores, since a remote job also collects a full location score.
- Landed the test suite (51 tests) and the planning docs; added requirements-dev.txt.

## 2026-08-04
- Started this changelog.
