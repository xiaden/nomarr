# Contracts Ledger Format

The contracts ledger (`CONTRACTS.md`) is a living document updated after every validated plan. Plan subagents receive its content as context.

---

## Template

```markdown
# {Feature} — Contracts Ledger

**Design doc:** `artifacts/designs/pending/DD-{feature}.md`
**Last updated:** {date} (after Plan {letter})

---

## Architectural Rules

{Rules extracted from copilot-instructions.md relevant to this feature. Examples:}

- Workflows take `db: Database`, never services
- Persistence uses `DatabaseLike` from `nomarr.persistence.arango_client`
- Timestamps: `now_ms().value` for int epoch millis
- No upward imports: persistence → components → workflows → services → interfaces

---

## Collections & Methods

### {collection_name} (Plan {letter})

**Document schema:**
{_key, field1, field2, ...}

**Indexes:** {list}

**Operations class:** `{ClassName}` in `{module_path}`

| Method | Signature |
|---|---|
| method_name | `(param: type, ...) -> return_type` |

---

## API Contracts

### {METHOD} {path} (Plan {letter})

- **Auth:** {verify_key | verify_session}
- **Request:** {body model or query params}
- **Response:** {status code + shape}
- **Notes:** {any special behavior}

---

## DTOs Created

| DTO | Module | Fields | Plan |
|---|---|---|---|
| TypedDictName | `nomarr.helpers.dto.xxx_dto` | field1, field2, ... | {letter} |

---

## Decisions Made

| Decision | Rationale | Plan |
|---|---|---|
| {what was decided} | {why} | {letter} |
```

---

## Update Rules

1. **Update after every validated plan**, not after every round
2. **Record full method signatures** — `method(a: str, b: int) -> ReturnType`, not `method()`
3. **Record all fields** for DTOs and document schemas — downstream plans need exact field names
4. **Architectural decisions go in Decisions table** — even if they seem obvious. They prevent the next subagent from re-deriving them differently
5. **Never delete entries** — append only. If a plan changes a prior contract, add a new row and note the change
6. **Date-stamp each update** with the plan letter that produced it
