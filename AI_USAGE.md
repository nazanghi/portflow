# AI_USAGE.md

Tracks every instance of AI-generated code in this project: what was generated,
what decisions were implicit, what was caught and corrected, and what category
of AI failure (if any) each entry represents.

The goal is not to justify using AI — it's to demonstrate that every line was
understood, reviewed, and owned.

---

## Entry format

**Module**: which file  
**What was generated**: brief description  
**Implicit decisions**: choices the AI made that weren't explicitly specified  
**Review outcome**: accepted / corrected / rejected, and why  
**Failure category** (if applicable): see categories below  

---

## Failure categories

| Category | Description |
|---|---|
| Instruction drift | AI ignored or drifted from an explicit requirement |
| Convention blindness | AI applied a common pattern that didn't fit this context |
| Brittle success | Code works for the happy path but breaks on edge cases |
| Confident wrongness | AI stated something incorrect without flagging uncertainty |
| Scope creep | AI added unrequested complexity |
| Error recovery failure | AI's error handling was absent or misleading |
| Grader gaming | AI optimised for looking correct rather than being correct |
| Ambiguity without disclosure | AI resolved ambiguity silently instead of flagging it |

---

## Log

### Session 1 — Schema and connection layer

**Module**: `db.py`  
**What was generated**: Full schema (3 tables), connection factory, `init_db()`, `log_run()` helper  

**Implicit decisions**:
- Used `NUMERIC(12,4)` for prices and `NUMERIC(8,6)` for weights — precision chosen
  without discussion. Price precision is defensible; weight precision to 6 decimal
  places is finer than any real portfolio needs and was not specified.
- `RealDictCursor` chosen as the default cursor factory — means all query results
  return dicts instead of tuples. Convenient, but slightly higher memory overhead.
  Not discussed before generation.
- `log_run()` opens its own connection rather than accepting one as a parameter —
  means every audit log write is a separate connection open/close cycle. Noted as
  a connection exhaustion risk in the three-question review.
- `adj_close` vs `close` both stored — correct decision (adj_close for returns,
  close for reference), but the reason (split/dividend adjustment) was not
  explained before code was generated.

**Review outcome**: Accepted with noted caveats. Implicit decisions were caught
in the three-question review and are understood.  

**Failure category**: Ambiguity without disclosure — several precision and
cursor choices were made silently.

---