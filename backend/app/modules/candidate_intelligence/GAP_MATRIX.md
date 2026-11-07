# Phase 4 audit gap matrix

Audit performed against the current implementation before the next changes. Baseline before closure work: `tests/candidate_intelligence` **8 passed**; latest focused run: **9 passed**; Alembic has one head, `d6f3a810bc42`.

## Workstream-level audit (this pass)

| Item | Spec | Current | Gap | Fix | Test | Status |
|---|---|---|---|---|---|---|
| WS1 scoring pipeline | services load immutable allowlist DTO, evidence→pure scorers→persist; rank reads persisted scores only | generic service currently collects evidence and calculates/persists; formula helpers added but not wired; rank implicitly analyzes | scorer not sole source; no golden DB/sentinel tests; ranking rescores | wire DTO + category scorers and persisted-only rank | scorer integration, sentinel, deterministic repeat | NOT VERIFIED |
| WS2 verification | complete 7×4 matrix and phone/URL requirements | regex phone, partial URL/timeline/completeness checks | no phonenumbers; full status matrix missing | normalized CheckResult contracts, phone library, secure URL client | table-driven matrix + mocked network | NOT VERIFIED |
| WS3 evidence columns | all ScoreEvidence columns and DB constraints | some columns + JSON evidence | many fields only in JSON, checks absent | new migration and model columns/constraints | DB constraint inserts | NOT VERIFIED |
| WS4 schemas/contracts | explicit request/response models and status behavior | ad hoc dictionaries, no response models | schemas, null pre-score, 409/422, masking incomplete | schemas + route contract updates | contract tests | NOT VERIFIED |
| WS5 ranking provenance | run/provider/config fields, append-only trigger, reproducibility | per-application run rows partly present | missing provenance, eligibility, trigger/rederive proof | migration trigger + provenance and tests | raw SQL immutability/reproduce | NOT VERIFIED |
| WS6 pgvector migration test | throwaway Postgres+pgvector full round-trip, seeded legacy DB | d6 head upgrades configured DB; configured server lacks extension | no automated pgvector round trip | add integration compose/test; run if Docker works | integration migration test | NOT VERIFIED |
| WS7 DSPy stall | identify/fix blocking call, offline default test, timeout/socket block | AI suite previously stalled at `test_dspy_engine_returns_typed_validated_output_offline`; no timeout/socket fixture | root cause unproven | reproduce with timeout then stub LM | full AI directory | NOT VERIFIED |
| WS8 quality tools | configured lint/types, fix Phase 4 | no ruff/mypy executables found; pyproject inspected | no lint/type outputs | discover/install only if project declares tools | configured commands | NOT VERIFIED |

| Item | Spec | Current state | Gap | Fix | Test | Status |
|---|---|---|---|---|---|---|
| Email syntax | validator, role/disposable review, absent/disabled unknown | regex pure check | no validator/role list/reason codes/config switch | implement precise check result | matrix cases | NOT VERIFIED |
| Phone format | phonenumbers with region rules and E.164 | generic digit regex | library and region behavior absent | use phonenumbers and config | phone matrix | NOT VERIFIED |
| Resume completeness | configurable section ratio/pass/review/fail/unknown | fixed section presence | thresholds and failed floor absent | configurable ratio | threshold cases | NOT VERIFIED |
| Timeline consistency | malformed/impossible/future failed; overlaps/gaps review-neutral | simple dates; overlap review | current-role and dated-entry rules differ | deterministic pure matrix | timeline table | NOT VERIFIED |
| Duplicate signals | normalized identifiers, same company/job scope | company claims/hash | scope option, normalized E.164 absent | configurable scope + normalization | duplicate scope cases | NOT VERIFIED |
| Portfolio URL | syntax, optional SSRF-safe reachability/redirect rules | syntax plus basic DNS block and HEAD | no 3-hop revalidation/GET fallback | hardened URL checker | SSRF/redirect/timeout | NOT VERIFIED |
| GitHub URL | GitHub host/path validation and optional reachability | profile collector, check shares portfolio syntax | check type/path semantics incomplete | dedicated GitHub verifier | path matrix | NOT VERIFIED |
| Status passed | check ran, data valid | mostly implemented | per-check consistency incomplete | standard result DTO | table-driven | NOT VERIFIED |
| Status needs_review | ambiguous/notable signal | some cases | role/phone/URL behavior missing | complete matrix | table-driven | NOT VERIFIED |
| Status not_verified | absent/disabled/unavailable | partly implemented | disabled checks and reason codes missing | complete matrix | table-driven | NOT VERIFIED |
| Status failed | definitive violation only | regex/date checks | timeline future/start semantics incomplete | complete matrix | table-driven | NOT VERIFIED |
| Overall precedence | failed > review > unknown > passed | helper exists | API response verification embedding inconsistent | common aggregator/schema | endpoint contract | NOT VERIFIED |
| Skills scoring | requirement weighted exact/alias/semantic/zero/unknown | category evidence average | mandatory weighting and extracted-empty distinction absent | requirement-level scorer | fixtures A-D | NOT VERIFIED |
| Experience scoring | merged relevant years + relevance components | generic evidence category mean | no interval merge, required years, component formula | pure scorer + input DTO | fixture E | NOT VERIFIED |
| Projects scoring | top-N mapped relevance | generic category mean | no top-N/id tie handling or project availability state | pure scorer | fixture G | NOT VERIFIED |
| Education scoring | configurable ordinal gap | generic evidence category mean | no degree map/gap/field signal | pure scorer | fixture F | NOT VERIFIED |
| Certifications scoring | weighted normalized matches/expiry | generic evidence category mean | alias/expiry and absent-vs-zero missing | pure scorer | fixture H | NOT VERIFIED |
| Mandatory evaluation | only exact/alias/rule met; unknown otherwise | partially excludes AI evidence | category/data availability logic weak | explicit mandatory evaluator | mandatory cases | NOT VERIFIED |
| Missing-data rule | exclude unknown/N/A, bounds and completeness | renormalize and bounds | bounds currently differ from requested applicable normalization | exact aggregation | fixtures B-D | NOT VERIFIED |
| Rounding/determinism | Decimal, HALF_UP, category 4dp,total 2dp | Decimal mostly | final scale/rounding and score percent shape mismatch | fixed scale at scorer edge | fixture I/property | NOT VERIFIED |
| ScoreEvidence fields | explicit typed persistence and invariants | JSON evidence plus a few columns | many fields only in JSON; no checks/is_proof | expand model/migration/DTO | field/check tests | NOT VERIFIED |
| CandidateScore fields | versions/config/score bounds/data/mandatory/hash/as_of | subset plus recent additions | category_scores/as_of/score precision and persistence incomplete | additive migration | persistence/repro test | NOT VERIFIED |
| RankingHistory fields | one row per app/run with all provider/config provenance | per-app rows now, run JSON duplicated | missing model/prompt/config hashes, eligibility; no append-only DB enforcement | schema + service grouping | immutability/full-fields | NOT VERIFIED |
| Reproducibility | snapshot + inputs reproduce score and order | inputs hash and config snapshot partly stored | no rederive contract | pure config-driven scorer | reproducibility test | NOT VERIFIED |
| Verify response | exact VerifyResponse schema and disclaimer | ad hoc dict | no response_model/schema examples | Pydantic v2 schemas | contract test | NOT VERIFIED |
| Analysis response | exact nested score/evidence/versions schema | ad hoc dict | pre-score null behavior and explicit model absent | schema and no-score pathway | contract test | NOT VERIFIED |
| Rank request/response | typed request, counts/status/versions | query params and ad hoc result | body contract/409/idempotency absent | Pydantic request/response | endpoint tests | NOT VERIFIED |
| Ranking page | stable pages, filters and versions | offset plus some filters | page info/verification filter source incomplete | response DTO and filter validation | endpoint tests | NOT VERIFIED |
| Ranking history page | grouped run summaries/pagination | recent grouping only | counts/provider versions/schema incomplete | typed summary | endpoint tests | NOT VERIFIED |
| POST verify | auth, scope, checks, overall/disclaimer | route uses Phase 2 authorization | response model/403-vs-404 semantics need contract verification | schema + tests | route test | NOT VERIFIED |
| GET analysis | latest verification, null score if absent | computes score on read | violates no-score-before-score contract | separate read/orchestrate behavior | route test | NOT VERIFIED |
| POST rank | per-job scoped, body, 409, versioned | synchronous, query filters | no run lock/body/id selection/force flag | implement request semantics | route test | NOT VERIFIED |
| GET ranking | latest or run id, pages/filters | latest row's embedded array | run selection/filter validation inconsistent | stable query implementation | route test | NOT VERIFIED |
| GET history | paginated immutable run summaries | groups current row records | aggregation and full fields incomplete | typed grouped history | route test | NOT VERIFIED |
| Migration | Postgres pgvector round trip and Phase1-3 data | c4 plus additive d6; PG upgrade reached d6 | downgrade/upgrade roundtrip not run; no real pgvector server | automated marked test; report unavailable honestly | migration test | NOT VERIFIED |
