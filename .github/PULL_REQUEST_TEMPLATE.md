# Pull Request

## Description

Provide a clear and concise description of what this PR does.

**Fixes:** # (issue number, if applicable)
**Related:** # (related issues or PRs)

## Type of Change

- [ ] Bug fix (non-breaking change which fixes an issue)
- [ ] New feature (non-breaking change which adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to not work as expected)
- [ ] Documentation update
- [ ] Refactoring (no functional changes)
- [ ] Performance improvement
- [ ] Test coverage improvement

## Changes Made

List the key changes:

- 
- 
- 

## Architecture Impact

Which layers are affected? (Check all that apply)

- [ ] `nomarr/interfaces/` - FastAPI routes, DI
- [ ] `nomarr/services/` - Service layer
- [ ] `nomarr/workflows/` - Multi-step orchestration
- [ ] `nomarr/components/` - Reusable domain logic
- [ ] `nomarr/persistence/` - Database access
- [ ] `nomarr/helpers/` - Utility functions
- [ ] `frontend/` - React UI
- [ ] `docs/` - Documentation only
- [ ] Other: _____

**Layer boundary violations?**

- [ ] No - all imports follow the architecture rules
- [ ] Yes - see explanation below (requires discussion)

## Testing

**How has this been tested?**

- [ ] Manual testing (describe below)
- [ ] Unit tests added/updated
- [ ] Integration tests added/updated
- [ ] End-to-end tests (Playwright)
- [ ] Tested in Docker environment

**Test environment:**
- OS: 
- Docker version: 
- GPU: 

**Test scenarios:**

1. 
2. 
3. 

## Checklist

**Code Quality:**

- [ ] Python code passes `ruff check` with zero errors
- [ ] Python code passes `mypy` with zero errors
- [ ] Python code passes `import-linter` (layer boundaries)
- [ ] Frontend code passes `npm run lint` (if applicable)
- [ ] All tests pass
- [ ] Code follows existing patterns and conventions

**Documentation:**

- [ ] Docstrings added/updated for public APIs
- [ ] README.md updated (if user-facing changes)
- [ ] CONTRIBUTING.md updated (if process changes)
- [ ] Architecture docs updated (if structural changes)
- [ ] Inline comments added for complex logic

**Breaking Changes:**

- [ ] This PR introduces breaking changes (explain below)
- [ ] Migration guide provided (if breaking changes)
- [ ] Pre-alpha policy acknowledged (breaking changes are acceptable)

## ML Model Changes

**(Required if modifying model processing logic)**

- [ ] N/A - No ML model changes
- [ ] Consulted with Music Technology Group, UPF (CC BY-NC-SA 4.0 ShareAlike compliance)
- [ ] Changes do not create derivative works of Essentia models
- [ ] Changes explained below:

## Screenshots/Videos

**(If UI changes)**

Before:

After:

## Performance Impact

- [ ] No performance impact
- [ ] Performance improvement (describe below)
- [ ] Potential performance regression (describe below and justify)

**Details:**

## Additional Notes

Add any other context about the PR here.

## Reviewer Notes

**(Optional) Specific areas you'd like reviewers to focus on:**

- 
- 