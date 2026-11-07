M1 checkpoint
Done: immutable allowlist DTO and pure Decimal helpers for experience, projects, education, certifications, skills and aggregation were added.
Tests run: `pytest -q tests/candidate_intelligence` — 9 passed, including category fixtures and bounds.
Open: ScoringService is not yet the sole persistence writer; category helpers are not fully wired; DB golden/sentinel/reproducibility tests remain.
Next: resume M1 wiring, complete A–I/property/sentinel/DB tests, update matrix with passing evidence, and commit before M2.
