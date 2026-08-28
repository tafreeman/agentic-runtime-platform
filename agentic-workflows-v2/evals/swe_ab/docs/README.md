# Documentation map

Everything written for the ARP SWE-fix A/B campaign, and which document answers
which question. Start at the [kit README](../README.md) for what the experiment
is; start here for where anything lives.

---

## Read this if you are…

### …running the next wave

1. **[TEST-SETUP.md](TEST-SETUP.md)** — preflight, requirements, isolation,
   how to resume mid-campaign. Run §1 before anything else; if it does not say
   `READY`, nothing downstream is trustworthy.
2. **[WAVE-RUNBOOK.md](WAVE-RUNBOOK.md)** — the procedure for one wave, the
   rules that keep waves unionable, and how to verify a result before believing
   it.
3. **[EVIDENCE.md §3](EVIDENCE.md#3-standing-caveats-on-every-number-above)** —
   the caveats that must travel with any number you report.

Dispatching an agent to do it instead: **[SUBAGENT-PROMPT.md](SUBAGENT-PROMPT.md)**
is a self-contained prompt needing no context from the originating session.

### …deciding what to measure, or designing a different eval

**[BEST-PRACTICES.md](BEST-PRACTICES.md)** — the transferable part. Every
practice is stated with the incident that earned it, and every incident is
recorded in EVIDENCE.md §2. This campaign produced two results that were
entirely artefact and looked completely normal in the summary line; that guide
exists so the next one costs less to learn.

### …choosing models, or trying not to spend money

1. **[MODEL-PROBE-GUIDE.md](MODEL-PROBE-GUIDE.md)** — procedure: how to find
   every model this machine can reach and how to tell free from paid. Durable.
2. **[MODEL-INVENTORY-2026-08-27.md](MODEL-INVENTORY-2026-08-27.md)** — the
   snapshot that procedure produced on 2026-08-27. Point-in-time; re-probe
   rather than trusting it.

### …auditing a number someone quoted

**[EVIDENCE.md](EVIDENCE.md)** is the auditable record: every run, every score,
every defect found and fixed, every report on disk including the ones known to
be invalid. It is written so a result can be checked without re-reading a
session transcript.

Then the write-up for the set the number came from, in
**[results/](results/)**.

### …fixing the platform rather than running the eval

**[ARP-IMPROVEMENTS-PROMPT.md](ARP-IMPROVEMENTS-PROMPT.md)** — a self-contained
work order for the gaps this campaign exposed in ARP itself: discovery that
covers four of seven serving paths, no notion of which models cost money, and
failover that walks into paid providers with no off-switch.

---

## Every document

### Operational — how to run the thing

| document | purpose | volatility |
|---|---|---|
| [TEST-SETUP.md](TEST-SETUP.md) | requirements, preflight, isolation, resuming | tracks the campaign |
| [WAVE-RUNBOOK.md](WAVE-RUNBOOK.md) | one wave, start to recorded result | stable |
| [SUBAGENT-PROMPT.md](SUBAGENT-PROMPT.md) | paste-ready prompt for an agent running waves | stable |

### Reference — how to choose

| document | purpose | volatility |
|---|---|---|
| [MODEL-PROBE-GUIDE.md](MODEL-PROBE-GUIDE.md) | finding models, telling free from paid | procedure, durable |
| [MODEL-INVENTORY-2026-08-27.md](MODEL-INVENTORY-2026-08-27.md) | machine snapshot: endpoints, free tiers, GPU precision floor | snapshot, decays |
| [../dataset/CASES.md](../dataset/CASES.md) | the mined case set: schema, layout, what a case must satisfy | stable |

### Findings — what happened, and what it means

| document | purpose | volatility |
|---|---|---|
| [EVIDENCE.md](EVIDENCE.md) | the auditable record: runs, scores, defects | append-only |
| [BEST-PRACTICES.md](BEST-PRACTICES.md) | transferable lessons, each with its incident | grows |
| [results/](results/) | one narrative write-up per case set | append-only |
| [ARP-IMPROVEMENTS-PROMPT.md](ARP-IMPROVEMENTS-PROMPT.md) | work order for the platform gaps found | until done |

### results/

| write-up | set | n | reading |
|---|---|---|---|
| [2026-08-28-swebench-35.md](results/2026-08-28-swebench-35.md) | SWE-bench Verified, oracle retrieval | 35 | A 68.6% · B 60.0% · p = 0.45 |
| [2026-08-27-mutations-132.md](results/2026-08-27-mutations-132.md) | mutations, four repositories | 132 | A 94.7% · B 90.9% · p = 0.23 |
| [2026-08-27-mutations-50.md](results/2026-08-27-mutations-50.md) | mutations, one repository | 50 | A 96.0% · B 90.0% · p = 0.25 |

Write-ups are **not** superseded by later ones and are never rewritten. Each is
the record of what one case set showed; the 132-case run supersedes the 50-case
run's *conclusion*, not its evidence. The current union across all SWE-bench
instances lives in [EVIDENCE.md §1.3](EVIDENCE.md#13-swe-bench-verified-oracle-retrieval),
which is the one place a running total is maintained.

---

## Conventions

**One place per fact.** A number lives in EVIDENCE.md; a procedure lives in the
runbook; a write-up interprets. If a number appears in two documents, one of
them is a quote and says so.

**Dated filenames are snapshots.** `MODEL-INVENTORY-2026-08-27.md` and
everything under `results/` are point-in-time and are never edited after the
fact — corrections are made in a new document that says what it corrects.
Undated filenames are living documents.

**New write-ups** go in `results/` as `YYYY-MM-DD-<slug>.md`, and add a row to
the table above and to EVIDENCE.md §1.

**Caveats are not optional.** No pass rate is quoted anywhere without the four
standing caveats from EVIDENCE.md §3 attached: oracle retrieval, underpowered,
one model / one attempt, contamination-prone.
