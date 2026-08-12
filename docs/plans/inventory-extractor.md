# Plan — fidelity inventory extractor (preliminary, analysis-side)

**Lifecycle:** working plan artifact, the hand-off contract for `/implement`
(invoke as `/implement docs/plans/inventory-extractor.md`). Not durable
documentation — the implementation change deletes this file (absorbing anything
still load-bearing into CLAUDE.md).

**Branch:** `feat/inventory-extractor` (this file's branch; implementation
stacks on it). **Classification: ARCHITECTURAL** — see §7.
**Written:** 2026-08-12, validated against the code at `cf5bcfa`.

---

## 1. Problem and decided constraints (do not re-open)

The fidelity instrument scores a generated contract against a curated clause
inventory (`contracts/inventories/*.yaml`). The judge prompt is
contract-agnostic; all contract-specific knowledge is the checklist, and only
the six benchmark contracts have one — so fidelity is unscorable on any new
contract. The **inventory extractor** is an LLM step that reads *only a source
contract `.txt`* and emits an inventory in the same shape.

Decided in discussion (2026-08-12):

- **Extractor seat: `gpt-5.6-luna`.** Extraction errors are *answer-key*
  errors — they corrupt every score against that contract (the energy.yaml
  incident is the quantified exhibit) — so the strongest model takes the seat
  with the highest cost per mistake. The backup judge (`gpt-4.1-mini`) is
  disqualified for key-writing by its calibration record (misses
  `HappensAssign`-style encodings; over-flags).
- **Residual bias channel, and its detector.** The extractor never sees a
  candidate, so judge-style self-preference doesn't apply; the only channel is
  a *shared blind spot* — clause types luna both fails to extract and fails to
  generate, which would inflate luna's own coverage. The calibration run below
  doubles as the probe: the six curated inventories are hand-written gold, so
  a blind spot surfaces as a recall pattern. No separate bias study.
- **Preliminary, analysis-side cut only.** No pipeline/API/frontend changes,
  no result-model changes, no schema regen, no `fidelity_sweep.py` changes.
- **First use of the built code is the calibration run** (§6): extract the six
  inventoried contracts, compare against curated on recall / precision /
  granularity. Until that passes, coverage computed from an extracted
  checklist is **provisional** — the judge was calibrated against the curated
  `expects` register, and an extracted register may steer verdicts
  differently. Surfacing covers denominator *visibility*, not this.
- **An extracted checklist is always surfaced** — written to a visible file
  and printed, never silently consumed. A wrong denominator is invisible
  inside a coverage number.

## 2. Chosen approach (summary)

Mirror the judge's split exactly. `output/fidelity.py` gains the pure pieces:
an (uncalibrated, clearly marked) `EXTRACTION_INSTRUCTIONS`, a payload
builder, a structural parse, and a single inventory well-formedness validator
shared with the curated-fixture fence. `scripts/inventory_extract.py` is the
thin consumer: one LLM call per contract, output to
`output/inventories_extracted/` (gitignored, structurally incapable of
shadowing `contracts/inventories/` — the sweep reads only its hardcoded
`INVENTORY_DIR`), always printed, with a `--compare` mode that renders
curated-vs-extracted item lists for the manual calibration alignment.

## 3. Design decisions

**D1 — Extend `output/fidelity.py`; no new module.** The file is ~91 lines and
the extractor is the other half of the same instrument — it emits exactly the
item shape `build_payload` serializes and `test_fidelity.py` fences. A
`output/inventory.py` would be a structural mirror splitting "what an
inventory is" across two homes. Accommodation required: the module docstring's
"editing `INSTRUCTIONS` invalidates the judge calibration" warning must be
**scoped to the judge string**, with one sentence marking
`EXTRACTION_INSTRUCTIONS` as not-yet-calibrated (see R1).

**D2 — LLM emits JSON; the script stamps metadata and writes YAML.** The model
returns `{"items": [{"id", "kind", "clause", "expects"}]}` only. The *script*
stamps top-level `contract` and `source` — it knows the real path, and the
sweep keys inventories by `Path(inventory["source"]).stem.lower()`, so a
model-guessed path is a wrong join key. Rejected: YAML directly from the LLM
(fragile multiline scalars; bypasses the existing tested parse tolerance);
model-emitted `contract`/`source`.

**D3 — Parse/validate split.** `parse_extraction(text)` does structural
extraction only — reuse `parse_judge_json` internally (it is content-generic:
fence-strip + outermost-brace + `json.loads`; do **not** rename it, its tests
are pinned) and check the envelope (an `items` list of dicts carrying the four
string keys). `inventory_errors(inventory)` is the **single semantic
validator** — top-level keys present, items non-empty, per-item fields
non-empty strings, ids unique — used by *both* the curated-fixture fence
(refactored onto it) and the script before writing. Script flow: parse →
assemble (stamp `contract`/`source`) → validate → write, or on any failure
write `<stem>.error.txt` carrying the errors and the raw response — never
silent. Id uniqueness is load-bearing beyond hygiene: the judge joins verdicts
to items by `id`, so collisions corrupt verdict matching.

**D4 — Kind vocabulary: guide, don't hard-validate.** The instructions list
the observed vocabulary (`obligation`, `power`, `state`, `access_grant`) but
`inventory_errors` checks only *presence* of `kind` — parity with the existing
fixture fence, and hard-closing the set pre-calibration would silently bias
extraction toward the current taxonomy.

**D5 — Calibration alignment is manual, supported by a shipped renderer.**
Total curated volume is 50 items across 6 contracts (6–13 each): manual
alignment is about an hour, and the human reading *is* the calibration —
split/merge granularity judgment is the finding, not an obstacle to automate.
What ships is `--compare`: for each contract with a curated inventory, render
both item lists (id / kind / clause / **full** `expects` text — truncation
would hide exactly what alignment judges) plus counts. No matching is
attempted in code. Rejected: **LLM-assisted alignment** — puts luna inside the
loop that measures luna's blind spots (correlated error in the bias probe) and
adds a prompt surface needing its own trust story; **programmatic fuzzy
matching** — prose similarity cannot see split/merge, the dominant divergence
mode, and mis-pairs silently corrupt recall/precision.

**D6 — One script, flags not subcommands** (matching `fidelity_sweep.py`):
positional `contracts` (`.txt` paths; a directory arg expands to its `*.txt` —
PowerShell doesn't glob, keep the sweep's docstring caveat), `--model`
default `gpt-5.6-luna`, `--provider` default `openai`, `--temperature` default
`None` (reasoning-model omission note, verbatim from the sweep), `--max-tokens`
default 16000, `--out` default `output/inventories_extracted/`, `--force`
(default skip-if-exists — the output file *is* the cache; no separate cache
dir), `--compare`. Sequential, no retry (one failure costs one contract,
printed + error file — same philosophy as the pipeline's failed-call rule).
Written files carry a header comment: extracted by `<model>` on `<date>`, not
curated, do not move into `contracts/inventories/` without review. Always
print the checklist table and the file path, including on cache hit.

**D7 — Promote nothing into the package for the LLM call.** The sweep's
"wrapper" is already just package API (`create_adapter(LLMConfig(...))` +
`.generate(payload).generated_text`, ~6 lines) — copy the idiom.
`output/fidelity.py`'s purity contract ("Nothing here calls an LLM") keeps it
importable/testable without spending calls; an LLM helper there would break
it. A `scripts/_common.py` is not warranted at ~10 duplicated lines — flag
only if a third LLM-calling script appears.

**D8 — Unknown-contract placement policy.** The Counter fence
(`test_every_contract_has_exactly_one_inventory`) makes `contracts/` mean
*curated benchmark membership*: any `.txt` there without an inventory reds the
suite. Policy: **experimental contracts live outside `contracts/`** (the
extractor takes explicit paths, so location is free); joining `contracts/`
requires a reviewed inventory in the same change — the existing fence *is* the
promotion gate, untouched. Copying an extracted file beside a curated one also
reds it (duplicate `source`), so shadowing is double-fenced.

## 4. Touch-list

- `symboleo_llm_tool/output/fidelity.py` (edit):
  - `EXTRACTION_INSTRUCTIONS: str` — draft per §5, explicitly marked
    uncalibrated;
  - `build_extraction_payload(source_text: str) -> str`;
  - `parse_extraction(text: str) -> list[dict[str, Any]] | None` (per D3);
  - `inventory_errors(inventory: dict[str, Any]) -> list[str]` (per D3/D4);
  - docstring: scope the calibration warning to the judge `INSTRUCTIONS`.
- `scripts/inventory_extract.py` (new): `main()` per D6; helpers approx.
  `extract_one(path, adapter, out_dir, force) -> dict | None`,
  `write_inventory(inventory, out_path)` (header comment +
  `yaml.safe_dump(..., sort_keys=False)`), `print_checklist(inventory)`,
  `print_comparison(curated, extracted)`. `--compare` loads curated YAMLs
  directly (a ~5-line loader; do not imitate the sweep's private
  `_source_text` injection).
- `tests/unit/test_fidelity.py` (edit): fences per §8; refactor
  `test_inventories_are_well_formed` onto `inventory_errors` so curated
  fixtures and extracted output share one well-formedness definition.
- CLAUDE.md (edit, same change): update the *Convergence ≠ fidelity* open-path
  paragraph — extractor built, seat = luna with the shared-blind-spot channel
  and its calibration-recall detector, extracted-checklist coverage
  provisional pending calibration.
- Delete this plan file.
- **No changes:** `scripts/fidelity_sweep.py`, `contracts/inventories/*`,
  pipeline/API/frontend, config/result models, generated schemas (⇒ no
  `schema.d.ts` regen obligation).

## 5. `EXTRACTION_INSTRUCTIONS` drafting requirements (high-tier work)

Contract-agnostic; task = enumerate **every normative clause**: obligations,
powers/discretions, state/lifecycle rules, access grants — each with parties,
direction (who owes whom), deontic modality (shall / may / must-not), trigger,
and deadline/temporal constraint. The `expects` prose must match the
**curated register** — naming parties, direction, modality, trigger, deadline,
and enforcement expectations where the text demands them (e.g. "the deadline
must be enforced by a temporal predicate, not merely named in an identifier")
— because the judge was calibrated against that register (see §1,
provisional-coverage constraint). `id`: unique snake_case slug. `clause`: the
source clause reference where one exists. Output: the JSON envelope of D2
only, no prose (parse tolerates fences/prose anyway). The file-wide E501
ignore already covers long instruction lines. **No phrase pins yet** (§8).

## 6. Calibration protocol (session work, after the code lands)

1. Run the extractor over the six curated contracts
   (`python scripts/inventory_extract.py contracts --compare`).
2. Manually align extracted↔curated per contract from the `--compare` output.
   Record per contract: **recall** (curated items with no extracted
   counterpart — each missed item silently inflates every candidate's
   coverage), **precision** (extracted items with no textual basis — these
   deflate it), **granularity** (split/merge divergences — these shift the
   denominator, so extracted-inventory scores are comparable only against
   scores from the *same* inventory).
3. Read the bias probe: are missed items disproportionately the clause types
   luna-generated contracts also fumble (temporal predicates,
   direction-sensitive payment/consequence clauses)?
4. Iterate wording if needed (the instructions are unpinned precisely so this
   loop is cheap), re-extract with `--force`, re-align.

## 7. Classification: ARCHITECTURAL

The script and validator are recipe work, but the risk concentrates exactly
where a cheap fresh context does damage: `EXTRACTION_INSTRUCTIONS` is
judge-adjacent prose whose quality decides the calibration outcome and is
**not fenceable by tests pre-calibration**, and the edit sits beside a
calibrated artifact whose phrase pins must not be disturbed (R1). Implement
high-tier; do not tier down.

## 8. Tests

Ship with the implementation (all in `tests/unit/test_fidelity.py`):

- `inventory_errors`: happy path against a minimal valid inventory; missing
  top-level key; missing/empty item field; duplicate id; empty items list.
- Curated-fixture fence refactored to assert `inventory_errors(inv) == []`.
- `parse_extraction`: fenced/prose-wrapped envelope parses; garbage → `None`;
  valid envelope → items; item missing a key → structural rejection.
- Existing judge pins untouched.

**Deferred to the post-calibration change, deliberately:** phrase pins on
`EXTRACTION_INSTRUCTIONS` *and* a payload-layout pin for
`build_extraction_payload` — the judge's layout pin exists because the layout
was part of what was calibrated; pinning pre-calibration wording would fence
prose the calibration loop (§6.4) is expected to rewrite.

## 9. Post-calibration obligations (recorded here so they survive the session)

1. Add the extraction phrase pins + payload-layout pin in the same change that
   records the calibration outcome (mirroring how the judge's pins landed).
2. CLAUDE.md: the calibration record — per-contract recall/precision/
   granularity, the bias-probe reading, and whether provisional status lifts.
   `output/` is gitignored, so the durable home for the numbers is CLAUDE.md,
   not the artifacts.
3. Only then consider follow-ons: feeding extracted inventories to
   `fidelity_sweep.py` (needs a correct `source` for stem keying), promotion
   of reviewed extractions into `contracts/inventories/`, and the product
   surface (the UI coverage chip), each a separate decision.

## 10. Considered and rejected (roll-up)

New `output/inventory.py` module (D1); YAML or metadata from the LLM (D2);
LLM-assisted or fuzzy-matched calibration alignment (D5); two scripts, or a
subcommand interface (D6); any extracted-output location under `contracts/`
(one `mv` from masquerading as curated — D8 makes `output/` structurally safe
instead); promoting an LLM-call helper into `output/fidelity.py` (breaks its
purity contract — D7); retry/concurrency in the script (six sequential calls;
failure philosophy per D6); closed kind vocabulary (D4); phrase-pinning the
uncalibrated instructions (§8).
