# Task: Comprehensive Example Plan

## Problem Statement

This is a reference plan demonstrating all possible formatting elements. Use this as a template when creating new task plans.

The problem being solved: We need to refactor the authentication system to support both session-based (web) and API key (v1) authentication patterns, while maintaining backward compatibility during the transition period.

**Context for fresh models:** The current auth system is split across multiple files with inconsistent patterns. Session auth uses cookies, API key auth uses headers. Both need unified middleware.

## Phases

### Phase 1: Discovery and Analysis

- [x] Run `discover_api` on all auth-related modules
- [x] Map current authentication flow with `trace_endpoint`
- [x] Document all endpoints currently using each auth method
- [ ] Identify shared vs divergent logic between auth methods

**Notes:** Found 3 auth patterns in use: `verify_session`, `verify_key`, and one legacy `check_token` that should be removed. The legacy pattern is only used in `/api/v1/legacy/status` endpoint.

**Warning:** The `check_token` function has no tests. Removing it may break undocumented integrations.

### Phase 2: Design Unified Middleware

- [ ] Create `AuthMiddleware` base class in `nomarr/interfaces/api/middleware/`
- [ ] Implement `SessionAuthMiddleware` subclass
- [ ] Implement `ApiKeyAuthMiddleware` subclass
- [ ] Add configuration for auth bypass routes (health checks, public endpoints)

**Notes:** Decision made to use middleware pattern over dependency injection for auth. Rationale: middleware handles the 401 response consistently, DI would require each endpoint to handle auth failures.

### Phase 3: Migration

- [ ] Update web API routes to use new middleware
- [ ] Update v1 API routes to use new middleware
- [ ] Remove legacy `check_token` function
- [ ] Update tests to use new auth patterns

**Blocked:** Cannot remove `check_token` until we confirm no external consumers. Need to add deprecation logging first and monitor for 2 weeks.

**Warning:** Bulk route updates are high-risk. Run `lint_backend` after each file, not at the end.

### Phase 4: Validation

- [ ] `lint_backend` passes on `nomarr/interfaces`
- [ ] `lint_backend` passes on full `nomarr/`
- [ ] All existing auth tests pass
- [ ] New middleware unit tests pass
- [ ] Manual testing: web login flow works
- [ ] Manual testing: API key authentication works
- [ ] Manual testing: invalid credentials return 401

**Notes:** Add integration test that hits both auth paths in sequence to catch any shared state bugs.

## Completion Criteria

- Zero lint errors in `nomarr/`
- No `# type: ignore` comments added
- All auth flows verified manually
- Legacy `check_token` removed (or deprecated with logging if blocked)
- Documentation updated in `docs/api/authentication.md`

## References

- Related issue: #142
- Architecture discussion: `docs/dev/decisions/ADR-007-auth-middleware.md`
- Previous attempt: `TASK-auth-refactor-v1.md` (abandoned due to scope creep)
