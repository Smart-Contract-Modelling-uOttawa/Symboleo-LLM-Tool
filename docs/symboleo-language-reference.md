# SymboleoAC — Language Reference

## What this document is for

This is the **input to prompt design**, not a prompt. Its job is to make our guidance *complete* rather than accumulated one production failure at a time.

We had been discovering rules by watching the correction loop stall, writing a bullet, and finding that the bullet over-applied somewhere adjacent. Twice in a row a fix introduced a new bug of the same shape: a rule stating where a construct *belongs* without stating where it does *not*. That is a symptom of not knowing what set of rules we should have. This document is the inventory to be exhaustive against.

**Two oracles, two jobs.** The papers define what the language *is* — use them for completeness and for principles that regenerate rules. The **JAR is the only authority on what validates** — the grammar under-specifies (a date literal is grammatically any string), and roughly half of what the validator enforces lives in Java `@Check` methods with no grammar counterpart. Where they disagree, the JAR wins, because the JAR is what we are graded against.

### Evidence tags

Every claim below carries one:

- **[S]** — *Sourced*: stated in a paper or official doc, with locus.
- **[J]** — *JAR-verified*: executed against `lib/symboleo-cli.jar`, the shipped artifact, built from upstream `SymboleoAC-IDE` `main` at the SHA recorded in its refresh commit. Upstream's `DOC.md` lags its own implementation and documents constructs the JAR rejects — trust the JAR, not that document.
- **[I]** — *Inferred*: our synthesis. Supporting evidence is named. Treat as a teaching device, not a citation.

---

## Sources

| Ref | Work | Access |
|---|---|---|
| **THESIS** | Parvizimosaed, A. (2022). *Symboleo: Specification and Verification of Legal Contracts*. PhD thesis, uOttawa. [RUOR](https://ruor.uottawa.ca/items/bb41b2ef-3709-46b1-be30-bc44469a7e85) | Full text (202 pp). **Richest source** — Ch. 4 ontology, Ch. 5 language + statecharts, App. A grammar, App. B 41 axioms |
| **RE20** | Sharifi, Parvizimosaed, Amyot, Logrippo, Mylopoulos (2020). *Symboleo: Towards a Specification Language for Legal Contracts*. IEEE RE'20, 364–369. [PDF](https://cyberjustice.openum.ca/files/sites/102/1.-Symboleo-Towards-a-Specification-Language-for-Legal-Contracts.pdf) | Full text |
| **LLMGEN** | Zitouni, Anda, Rajpal, Amyot, Mylopoulos (2025). *Towards the LLM-Based Generation of Formal Specifications from Natural-Language Contracts*. RAISE@ICSE 2025. [arXiv 2411.15898](https://arxiv.org/pdf/2411.15898) | Full text. **Directly on-point** — same research group grading 38 LLM-generated specs |
| **ACABS** | Alfuhaid, Anda, Amyot, Roveri, Mylopoulos (2024). *SymboleoAC: An Access Control Model for Legal Contracts*. PoEM 2024, LNBIP 538. [HAL hal-05008329](https://inria.hal.science/hal-05008329/) | **Abstract only** — see Gaps |

**Not accessible** (stated so the gap is visible rather than silently filled):
- SoSyM 2022, *Specification and analysis of legal contracts with Symboleo*, [doi:10.1007/s10270-022-01053-6](https://doi.org/10.1007/s10270-022-01053-6) — paywalled. The canonical journal overview; largely superseded for our purposes by THESIS (four shared authors, same material at greater length), but unverified against it.
- SymboleoAC PoEM 2024 **full text** — open-access PDF exists at HAL but the host is behind an anti-bot challenge. Abstract retrieved verbatim via the HAL REST API.
- SymboleoAC SoSyM 2025, [doi:10.1007/s10270-025-01327-9](https://doi.org/10.1007/s10270-025-01327-9) — paywalled.

**Consequence:** Part 4 (access control) rests on the abstract plus the shipped grammar and samples. It is the layer we actually target and the layer we have least primary material for.

---

## Part 1 — What Symboleo is

### 1.1 The organizing principle: monitorability

The ontology draws on Hohfeld's eight legal positions, UFO-L, and analysis of 50+ real contracts **[S: THESIS §4.4]**. Of Hohfeld's eight, Symboleo keeps **two** — obligation and power — and states the criterion outright:

> *"of the eight correlative and opposite Hohfeldian legal concepts only two are used, power and obligation, since only these two are **monitorable**."* **[S: THESIS §4.4]**

The same filter was applied to contract text: *"We analyzed sample contracts and excluded non-monitorable terms and conditions such as warranty or dispute resolution clauses."* **[S: THESIS §4.4]**

**[I]** This is the single most useful fact about the language. Everything downstream follows from it: if a clause cannot be observed as an event stream, it does not become a norm. A model that forces warranty or dispute-resolution prose into an obligation is making a category error, not a syntax error.

### 1.2 The concepts

**[S: THESIS §4.4 Fig. 4.5; RE20 §II]**

| Concept | Definition (condensed from source) |
|---|---|
| **Contract** | "a set of legal positions (i.e., obligations and powers) defined to bind at least two parties" |
| **Party** | "a legal agent who owns an asset and undertakes some responsibilities or rights" — natural or artificial persons; bound to roles at runtime |
| **Role** | "a characterization of the obligations and powers a party participates in" — the design-time placeholder |
| **Asset** | "an owned (tangible or intangible) item of value" |
| **Obligation** | "A legal duty of a party against a counterparty to bring about a legal situation, called *consequent*, when a prerequisite legal situation, called *antecedent*, holds" |
| **Power** | "a legal power (i.e., a type of right) to create, change or terminate a legal position for a party" |
| **Legal Situation** | "states of affairs… A situation occurs during a time **interval** T, and holds during any subinterval of T" |
| **Event** | "a happening that occurs at a time**point**, and cannot change. Events have pre-state and post-state situations" |

**Why powers exist at all** — the distinguishing feature of contracts:

> *"contracts fundamentally differ from business processes in that they can change during their execution through the exertion of powers."* **[S: RE20 §II]**

### 1.3 Lifecycle states

The state names are writable literals in the grammar, so this list is authoritative for what a contract may reference **[S: THESIS App. A; J: confirmed identical in the shipped grammar]**:

- **Obligation**: `Create` `Discharge` `Active` `InEffect` `Suspension` `Violation` `Fulfillment` `UnsuccessfulTermination`
- **Power**: `Create` `UnsuccessfulTermination` `Active` `InEffect` `Suspension` `SuccessfulTermination`
- **Contract**: `Form` `UnAssign` `InEffect` `Suspension` `Rescission` `SuccessfulTermination` `UnsuccessfulTermination` `Active`

`Active` is a **superstate**, not a sibling: an obligation is active when it is either `InEffect` or suspended **[S: THESIS App. B axioms B.4, B.5]**.

Two distinctions the papers call out explicitly:

- **Discharge ≠ UnsuccessfulTermination.** *"In the case of antecedent expiration, the obligation is discharged, since there is no possibility for it to become true after it has expired. Discharged obligations are **cancelled** obligations rather than unsuccessfully terminated ones."* **[S: THESIS §5.2]**
- **Violation is not an end state.** A violation *"may trigger a power that entitles its creditor to suspend, terminate, or discharge one or more InEffect obligation instances, or may trigger another obligation"* — the **contrary-to-duty (CTD)** pattern **[S: THESIS §5.2]**.

**[I]** A power has no `Violation` or `Fulfillment` state — it terminates *successfully* when exerted and *unsuccessfully* when it expires. Nobody is obliged to exert a power, so it cannot be violated. If a model wants to "violate a power," the modelling is wrong.

---

## Part 2 — Generative principles

**This is the part that matters.** Each principle below *regenerates* rules that would otherwise have to be memorized individually — and memorized facts are the ones that get over-applied.

### P1. Slot 1 is the party who acts

```
O(debtor,   creditor, antecedent, consequent)
P(creditor, debtor,   antecedent, consequent)
```

The usual framing — "the party order is reversed" — is a fact to memorize and therefore a fact to get wrong. The generative version:

**Creditor and debtor never change meaning.** In both forms the *creditor* is the right-holder and the *debtor* is the bound party (duty-bearer for an obligation, liability-bearer for a power) — straight Hohfeld: duty↔right, power↔liability **[S: THESIS §4.2]**. What changes is **who acts**: in an obligation the bound party performs; in a power the right-holder exerts.

> *"the debtor and creditor are **initial performers of obligations and powers respectively**"* **[S: THESIS §5.3.4]**

> *"A power **entitles the creditor** to bring about the consequent."* **[S: THESIS §5.1]**

**[I]** So the rule is: **slot 1 is always the party who acts.** That regenerates the order rather than requiring recall of which way it flips.

It also connects to `performer`: an event in an **obligation's** consequent must have `performer` = the obligation's **debtor**; an event in a **power's** consequent must have `performer` = the power's **creditor** **[S: THESIS App. B axioms B.32/B.33, B.40/B.41]**. Slot 1 and the consequent event's performer are the same party — one rule, two places.

⚠️ **The validator cannot catch a swap.** Both slots are type-checked as Role instances **[J]**, so `O(creditor, debtor, …)` validates clean and is silently wrong. This is the only semantic rule in this document with *no* JAR feedback, which is exactly why it needs stating.

### P2. `-ed` is a point; a noun is an interval

Symboleo's type system is fundamentally point-vs-interval: events occur at a timepoint, situations hold over an interval **[S: THESIS §4.4]**. The language then allows *"events to be used in place of points, and situations in place of intervals"* **[S: THESIS §5.1; RE20 §IV]**, and the predicate signatures fix which slot takes which.

**[I]** The naming follows a morphological pattern that predicts the entire event/state matrix:

| Form | Denotes | Legal in |
|---|---|---|
| **past participle** — `Violated` `Suspended` `Fulfilled` `Discharged` `Terminated` `Activated` `Expired` `Triggered` `Resumed` | the **instant** it changed | `Happens(...)`, and Point slots (`WhappensBefore`, `ShappensBefore`, `HappensAfter`) |
| **noun** — `Violation` `Suspension` `Fulfillment` `Discharge` `Active` `InEffect` `Create` | the **span** it stayed | Interval slots (`HappensWithin`, `Occurs`) |

**[J]** Verified in both directions, 12/12 cells: `Happens(Violated(obligations.x))` legal / `Happens(Violation(obligations.x))` illegal; `HappensWithin(e, Suspension(obligations.x))` legal / `HappensWithin(e, Suspended(obligations.x))` illegal. Same for the Fulfilled/Fulfillment and Discharged/Discharge pairs.

The canonical `MeatSale` sample uses both, one line apart **[S: SymboleoAC-IDE samples]**:

```symboleo
latePayment:    Happens(Violated(obligations.payment)) -> ...
                       ^ EVENT — the moment payment was violated (a point)
resumeDelivery: HappensWithin(paidLate, Suspension(obligations.delivery)) -> ...
                                        ^ STATE — the stretch delivery was suspended (an interval)
```

Near-homographs that make this a live trap: `Suspended`/`Suspension`, `Discharged`/`Discharge`, `Violated`/`Violation`, `Fulfilled`/`Fulfillment`. Some exist on one side only — `Activated`/`Expired` are events with no same-root state; `Create`/`Active` are states with no same-root event.

### P3. A power never makes something happen — it only moves another norm's state machine

A power's whole purpose is *"to create, change or terminate a legal position"* **[S: THESIS §4.4]**. That is why its consequent is not an arbitrary proposition but a closed set **[S: THESIS App. A; J: verified exhaustively]**:

```
Suspended(obligations.X)   Resumed(obligations.X)   Discharged(obligations.X)
Terminated(obligations.X)  Triggered(obligations.X)
Suspended(self)            Resumed(self)            Terminated(self)
```

**[J]** Everything else is rejected, including `Happens(...)`, `true`, any `and`/`or` combination, `Assign(...)`, and `Suspended(powers.X)`.

**This is a documented LLM failure mode**, with the fix stated by the language's own authors **[S: LLMGEN §IV.B]**:

```symboleo
// generated (wrong)
reducePrice: ... -> P(customer, store, true, Happens(priceReduced) and Happens(paidAfterReduction));
// corrected
reducePrice: ... -> P(customer, store, true, Triggered(obligations.oReducePrice));
```

> *"the correction involves removing the condition from the power and instead **triggering** the oReducePrice obligation"* **[S: LLMGEN §IV.B]**

**[I]** The repair rule: if the text says a party *may do X* where X is a real-world act, model a power that **triggers an obligation** whose consequent is X — never a power whose consequent is X.

### P4. `trigger` gates existence; `antecedent` gates activation

> *"Obligations become InEffect when their antecedents become true. Suspensive Obligations require a trigger to be created… **If there are no triggers mentioned in the specification, an obligation will be instantiated but will take effect only when its antecedent becomes true.**"* **[S: THESIS §5.1; RE20 §III]**

```
            trigger                     antecedent
(nothing) ──────────► Create ─────────────────────► InEffect ──consequent──► Fulfillment
                        │                                    ──deadline───► Violation
                        └── antecedent deadline ──► Discharge
```

- **trigger** — *does this duty exist at all?* (instantiation)
- **antecedent** — *given that it exists, is it live yet?* (activation)

**[I]** So: a remedial or contrary-to-duty condition ("if the buyer fails to pay, the buyer shall pay interest") belongs **left of `->`**. A precondition of an already-existing duty ("after unloading, pay within N days") belongs in the **antecedent**. An unconditional obligation takes a literal `true` antecedent — the form is always 4-ary, never 3.

### P5. Contracts observe occurrences; they do not store state

**[S: LLMGEN §IV.B]** documents this as a top error class. Generated (wrong):

```symboleo
Declarations
  deposit: Number;  remainingPayment: Number;  deliveryDate: Date;  lateDelivery: Boolean := false;
```

> *"The correction involves updating the data types to **events**… Paid is a domain data type and should be defined as an event in the domain section, together with an amount attribute that will be dynamically provided at runtime as an **environment variable**."* **[S: LLMGEN §IV.B]**

**[I]** Root cause: the model reaches for *program variables* where Symboleo wants *monitorable occurrences* — a direct violation of §1.1. A payment is not a number the contract stores; it is an event the contract observes. A boolean flag like `lateDelivery` is almost always a situation expressed as a predicate, not stored state.

**[J]** The implementation enforces this structurally: a `Declarations` variable's type **must** be a RegularType — base types, enumerations, and aliases are all rejected there, though all three are legal as *contract parameters*.

### P6. `performer` exists for event authenticity — and it is base-language, not access control

> *"Symboleo semantically filters events triggered by eligible performers, e.g., a paid event affects a payment obligation in case the event generator is the performer of the obligation. Therefore, any other payment events are invalid from the contract perspective. To this aim, **the performer is a mandatory attribute of events in Symboleo's domain concept**, and its value is assigned at run time."* **[S: THESIS §5.3.4]**

**[I]** This corrects a misattribution in our own notes: `performer` is not an AC-layer requirement. It is base-language soundness — without it, an obligation cannot tell whether an event discharges it or is an unrelated party's act. That justification is more useful to a model than "the AC validator wants it."

---

## Part 3 — Construct reference (JAR-verified)

All **[J]** unless noted. Contrast pairs are marked ⚡ — those are the constructs that look alike and behave differently, and they are where our guidance has failed.

### 3.1 Document structure

Sections may appear **only** in this order; any deviation is a hard parse error:

```
Domain … endDomain
[TimeGranularity is <unit>]
Contract <Name> ( ≥2 params )
[Declarations] [Preconditions] [Postconditions]
Obligations                        ← required header, may be empty
[Surviving Obligations] [Powers] [ACPolicy …] [Constraints]
endContract
```

- **≥ 2 contract parameters** — the grammar's `(P ',')+ P` forces at least one comma. One parameter fails with `required (...)+ loop did not match anything`.
- The `Obligations` **header is mandatory** even for a powers-only contract; a header with zero entries is clean.
- `Domain` needs ≥1 type.
- Comments: `//` and `/* */`. `#` is not a comment.

### 3.2 Domain types — three categories, three article rules ⚡

| Category | Form | Article | `with` attrs |
|---|---|---|---|
| **Alias** | `Money isA Number;` | **`isA` only** | never |
| **Enumeration** | `Q isAn Enumeration(A, B);` | **`isAn` only** | never |
| **RegularType** | `Buyer isA Role [thirdParty] [with a: T]` | **either** | optional |

The article is **not** tied to the vowel: `Buyer isAn Role` is clean. But `Money isAn Number` and `Q isA Enumeration` are both errors.

Base types: `Number` `String` `Date` `Boolean` (case-sensitive). Ontology types: `Asset` `Event` `Role` `Contract` `DataTransfer`; `Resource` is separate.

Forward references are fine — a type may be used before it is declared. Inheritance chains are fine; cycles error. **Duplicate domain type names are not checked** (surprising — every other namespace is).

### 3.3 Enumerations — bare at declaration, qualified at use ⚡

| Position | Form | |
|---|---|---|
| Declaration | `Q isAn Enumeration(PRIME, AAA);` | bare, comma-separated, no trailing comma |
| Any use | `goods.q == Q(PRIME)` / `q := Q(PRIME)` | **call syntax** `Type(MEMBER)` |

Illegal: `Enumeration(Q.PRIME, …)` at declaration; bare `PRIME` at use; `Q.PRIME` anywhere — the dot form is never legal.

*This pair caused a production regression: a rule saying only "qualify enum values" was applied to the declaration.*

### 3.4 Separators ⚡

**Semicolons appear in exactly two places.** Everything else is comma-separated.

| Construct | Separator |
|---|---|
| Statement terminator (every section) | `;` |
| `Assign(a := x; b := y)` / `HappensAssign(e, a := x; b := y)` | **`;`** |
| Domain `with a: T, b: U` | `,` |
| Declaration `with a := x, b := y` | `,` |
| Enumeration members | `,` |
| Contract parameters | `,` |
| ACPolicy controller list | `,` |

*This pair caused the second production regression: a rule giving `Assign`'s semicolon without scoping it was applied to declaration `with` lists.*

### 3.5 Norms

```
name : [trigger ->] (O|Obligation)(debtor, creditor, antecedent, consequent) [with Controller r] ;
name : [trigger ->] (P|Power)     (creditor, debtor, antecedent, consequent) [with Controller r] ;
```

`O`/`Obligation` and `P`/`Power` are interchangeable. Exactly 4 arguments; the trigger arrow is `->` only. Norm names must start lowercase and share one namespace across obligations + surviving obligations + powers.

**Consequent grammars differ by norm type** ⚡ — an obligation's consequent is a full `Proposition`; a **power's consequent is a `PowerFunction`** (the closed set in P3) and admits no `and`/`or`/`not`, no `Happens`, no `true`, no `Assign`.

`obligations.` and `powers.` are **single tokens including the dot** — `obligations . x` with spaces fails.

### 3.6 Predicates

| Form | Notes |
|---|---|
| `Happens(Event)` | |
| `WhappensBefore(Event, Point)` / `ShappensBefore` / `HappensAfter` | `W`/`S` prefixes are load-bearing |
| `WhappensBeforeE(Event, Event)` / `ShappensBeforeE` | trailing `E` = event-to-event |
| `HappensWithin(Event, Interval)` | |
| `Occurs(Situation, Interval)` | first arg is a **Situation** |
| `Assign(a := x; b := y)` / `HappensAssign(e, a := x; b := y)` | |
| `IsEqual(ID, ID)` / `IsOwner(ID, ID)` / `CannotBeAssigned(ID)` | **bare IDs — dots rejected** ⚡ |

**`HappensBefore` does not exist** despite appearing in the stale `DOC.md`. Math/String functions are **not** propositions — legal in bindings and `Assign` values, rejected in a consequent.

### 3.7 Dates and time ⚡

`Date.add(<date>, <amount>, <timeUnit>)` is the only date arithmetic. `<timeUnit>` is a bare keyword: `seconds` `minutes` `hours` `days` `weeks` `months` `years`.

**Three positions, three different grammars:**

| Position | Legal? | Note |
|---|---|---|
| Declaration binding / `Assign` value | ✅ | second arg accepts a full expression (`n + 1`) |
| Point slot (`WhappensBefore` etc.) | ✅ | second arg accepts **only** an INT or dot-expression — `n + 1` fails here |
| Inside a comparison (`x == Date.add(...)`) | ❌ | bind it in `Declarations` first, compare against the attribute |

**Date literal**: `Date("yyyy/MM/dd HH:mm:ss")` — slashes, time required, enforced by a value converter not the grammar. A `Date(...)` literal is **not** legal in a Point slot; a Date-typed parameter is. `Date(existingDateValue)` is not a wrapper — it produces a parse error plus a validator crash.

**Point vs Interval vocabularies do not overlap** ⚡: every event name is a legal Point and an illegal Interval; every state name is the reverse.

### 3.8 Assignments ⚡

| | Declaration `with` | `Assign(...)` |
|---|---|---|
| LHS | bare attribute name | dot-expression (`goods.owner`) |
| Separator | `,` | `;` |
| Type-checked | **yes** | **no** |
| May assign an `Env` attribute | **no** | **yes** |

Both use `:=`; `=` fails in either. **Aliases are nominal**: a `Money isA Number` value is not assignable to a `Number` attribute.

---

## Part 4 — Access control

⚠️ **Weakest-sourced section.** The PoEM 2024 full text was inaccessible; this rests on the verbatim abstract **[S: ACABS]** plus the shipped grammar and samples **[J]**.

**[S: ACABS]** SymboleoAC is a **role-based access control model** that treats *"all contract elements as resources"*, with two layers: **controller rules** (who may authorize access to a resource) and **pre-authorization rules** (who has access to what).

**[J]** Requirements the validator enforces:
- Every `Role` must declare `name`, `org`, `dept`.
- Every `Event` must declare a Role-typed attribute named exactly `performer`. `DataTransfer` does **not** require one, despite being event-like elsewhere.

**[I]** `name`/`org`/`dept` is the standard RBAC subject-identity triple — a principal that cannot be identified cannot be the subject of an access decision. `thirdParty` marks a role with AC standing but no legal-position standing (assessor, regulator, carrier).

**[J]** Policy syntax, with fixed and asymmetric casing:

```
ACPolicy with Controller <role> [, <role>]*
  <name> : (Grant|Revoke) (read|write|all|transfer) To <role> On <Resource> by <role> ;
```

`Grant`/`Revoke` capitalised, permissions lowercase, `To` and `On` capitalised, **`by` lowercase**. (The JAR's own message says "after `'By'`" — the message is wrong; the grammar requires lowercase.)

**[S: samples]** Defaults, per the sample's own comments: an asset's controller is its owner; a norm's controller is its performer — debtor for an obligation, creditor for a power. **[I]** That is P1 reused as the AC default; AC did not invent a new authority notion.

---

## Part 5 — Traps

Ordered by how badly they mislead.

1. **Silent-accept: `Happens(<undefined> <dotExpr>)` validates clean** **[J]**. The `DataTransfer` event production is `name=ID variable=VariableDotExpression` with **no cross-reference on `name`**, so `Happens(nope paid.amount)` is accepted. A dropped comma or a typo can produce a *valid* contract that means nothing, and **nothing in a correction loop will ever surface it**. This is the most dangerous item in this document.
2. **Reserved words, two classes** **[J]**. *Grammar keywords* (`Asset`, `Event`, `Role`, `Suspension`, `Date`, `self`, … ~102 derivable from the grammar) produce opaque failures like `mismatched input 'Asset' expecting 'endDomain'` that name neither the identifier nor the rule — historically an unrecoverable plateau. *JS/Java collisions* (`Party`, `Object`, `Map`, `state`, `class`, …) produce a clear, actionable message and are fixed in one iteration. The second class is **not** derivable from the grammar.
3. **Prose or a markdown fence before the code fails at line 1**, and a top-of-file parse error suppresses all validation below it **[J]**. Error counts from such a run are meaningless, not merely inflated.
4. **`Assign(...)` is entirely untyped** while declaration bindings are strictly typed — including writing to an `Env` attribute, which declarations forbid **[J]**.
5. **`Env` is accepted on `Resource`** even though the error message says "only … Event (or DataTransfer)" **[J]**.
6. **Duplicate domain type names are not checked** while parameters/variables, norms, and AC rules all are **[J]**.
7. **Unary minus does not exist**: `-1` fails everywhere; binary `a - 1` is fine **[J]**.
8. **Single-quoted strings work** (Xtext's `STRING` terminal) but should not be relied on **[J]**.

---

## Part 6 — Empirical findings on LLM generation

From the language authors' own study of 38 generated specs **[S: LLMGEN]**. These bear directly on our prompt strategy.

**The dominant error classes.** *"the most significant challenges ChatGPT encounters are adhering to the grammar, correctly identifying environment variables, and maintaining correct syntax. They composed **49%** of the total number of violated metrics"* **[S: LLMGEN §IV.B]**.

**More rules can make output worse.** *"providing the grammar alone prompted ChatGPT to generate more complex code, leading to more errors due to incorrect or incomplete application of the rules"* **[S: LLMGEN §IV.B]**. Their grammar+theory-without-examples condition scored **worse than providing nothing at all**.

**Semantic explanations trade error classes rather than removing them** — complex-expression errors largely disappeared, but *"new errors emerged unrelated to the grammar, such as issues with the implementation of the theoretical concepts"* **[S: LLMGEN §IV.B]**.

**Example composition is not neutral.** A few-shot scenario that omitted environment variables caused the model to *"omit environment variables altogether, even though they had been identified and utilized in the more detailed examples"* **[S: LLMGEN §IV.B]**.

**Inventing unsourced content** is a named error class — the model added attributes and an enumeration *"even though these details were not specified in the original contract description"* **[S: LLMGEN §IV.B]**. This independently confirms the anti-pattern recorded in our own fidelity audit.

**[I]** Read together, these argue that the marginal *rule* is now low- or negative-value for us, and that effort is better spent on example quality and on principles (Part 2) that regenerate rules rather than adding them.

---

## Part 7 — Gaps

Stated explicitly so they are not silently filled later.

- **Three papers inaccessible** (SoSyM 2022, PoEM 2024 full text, SymboleoAC SoSyM 2025). Part 4 is the weakest section as a result.
- **The JS/Java reserved-word list is not enumerable** from the JAR without decompiling; ~73 candidates were sampled.
- **Runtime and code-generation semantics are out of scope** here — everything in Part 3 is parse + `@Check` only.
- **The statecharts (THESIS Fig. 5.1) were not readable** as images; transitions in §1.3 come from the axioms and prose.
- **Two principles in Part 2 are our synthesis**, not stated rules: the `-ed`/noun morphology (P2) and the "slot 1 acts" framing (P1). Both are strongly supported — P2 by 12/12 JAR cells, P1 by axioms B.30/B.31 — but a future reader should know they are teaching devices we constructed.

---

## Using this document

- **Prompt rules** should be traceable to Part 2 (a principle) or Part 3 (a verified construct). A rule that is neither is a guess.
- **Every prompt rule must name the site where it does *not* apply.** Both production regressions to date were one-sided rules over-applied to an adjacent construct; the ⚡ pairs in Part 3 are the known adjacency map.
- **The JAR is the oracle.** New claims get a probe in `tests/integration/test_placement_rules.py` before they ship.
- **Part 6 is a caution against the obvious move.** Adding rules has measurable diminishing and sometimes negative returns; prefer principles, and treat example quality as a first-class lever.
