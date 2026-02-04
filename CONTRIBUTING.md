# Contributing to Nomarr

Thank you for your interest in contributing to Nomarr! This document provides guidelines for contributing to this pre-alpha project.

## ⚠️ Project Status

**Nomarr is in pre-alpha development** and changes heavily on a daily basis. The architecture is actively being refactored, and breaking changes are expected. We welcome contributions but ask for patience as the codebase stabilizes.

## 🤝 How to Contribute

### Reporting Bugs

1. Check [existing issues](https://github.com/xiaden/nomarr/issues) to avoid duplicates
2. Use the bug report template when creating a new issue
3. Include:
   - Nomarr version (check container logs or `config/nomarr.yaml`)
   - Docker/system environment details
   - Steps to reproduce
   - Expected vs actual behavior
   - Relevant logs (from `docker compose logs nomarr`)

### Suggesting Features

1. Check [existing discussions](https://github.com/xiaden/nomarr/discussions) and issues
2. Use the feature request template
3. Describe the use case and why it fits Nomarr's goals (music library auto-tagging for self-hosted systems)

### Submitting Pull Requests

**Before starting work on a PR:**

1. **Discuss first** - For anything beyond trivial fixes, open an issue or discussion first
2. **Understand the architecture** - Read [docs/dev/architecture.md](docs/dev/architecture.md) and [.github/copilot-instructions.md](.github/copilot-instructions.md)
3. **Check the layer structure** - Nomarr uses clean architecture with strict layer boundaries

**PR Requirements:**

- Code follows the existing architecture patterns (see below)
- Python code passes `ruff` linting and `mypy` type checking (zero errors)
- Frontend code passes ESLint
- All tests pass (if applicable)
- Commit messages are descriptive
- PR description explains what changed and why

**For ML model contributions:**

⚠️ **Consult with Music Technology Group, Universitat Pompeu Fabra** before submitting PRs that:
- Modify model processing logic
- Create derivative works of Essentia models
- Change how model outputs are interpreted or normalized

Essentia models are licensed under CC BY-NC-SA 4.0 with ShareAlike requirements.

## 🏗️ Architecture Guidelines

Nomarr uses a **layered clean architecture** with strict dependency rules:

```
interfaces → services → workflows → components → (persistence / helpers)
```

**Key Rules:**

1. **Layer boundaries are enforced** by `import-linter` - violations will fail CI
2. **Dependency injection** is used for major resources (database, config, ML backends)
3. **No global state** - config is loaded once and passed via parameters
4. **Type annotations are mandatory** - all Python code must be fully typed
5. **Essentia is isolated** - only `components/ml/ml_backend_essentia_comp.py` imports essentia

**Layer-specific instructions:**

- `nomarr/interfaces/` - FastAPI routes, request/response models, DI wiring
- `nomarr/services/` - Service layer, orchestrates workflows and components
- `nomarr/workflows/` - Multi-step business logic, calls components
- `nomarr/components/` - Reusable domain logic, calls persistence/helpers
- `nomarr/persistence/` - Database access, ArangoDB queries
- `nomarr/helpers/` - Pure utility functions, no nomarr imports

See [.github/instructions/](`.github/instructions/`) for detailed layer conventions.

## 🔧 Development Setup

### Prerequisites

- Python 3.12+
- Node.js 18+ (for frontend)
- Docker + Docker Compose
- NVIDIA GPU with CUDA support (for ML inference)

### Local Setup

1. **Clone the repository:**

   ```bash
   git clone https://github.com/xiaden/nomarr.git
   cd nomarr
   ```

2. **Backend setup:**

   ```bash
   # Create and activate virtual environment
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate

   # Install dependencies
   pip install -e ".[dev]"
   ```

3. **Frontend setup:**

   ```bash
   cd frontend
   npm install
   ```

4. **Start development environment:**

   ```bash
   # From repo root
   docker compose up -d arangodb  # Start database only

   # In one terminal - backend
   source .venv/bin/activate
   uvicorn nomarr.interfaces.main:app --reload --port 8356

   # In another terminal - frontend
   cd frontend
   npm run dev
   ```

### Running Tests

```bash
# Backend unit tests
pytest tests/

# Backend linting (MUST pass before submitting PR)
ruff check nomarr/
mypy nomarr/
python -m import_linter  # Check layer boundaries

# Frontend linting
cd frontend && npm run lint

# End-to-end tests (requires Docker environment)
npx playwright test
```

## 📝 Code Style

### Python

- **Formatter:** `ruff format` (automatically applied)
- **Linter:** `ruff check` (must pass with zero errors)
- **Type checker:** `mypy --strict` (must pass with zero errors)
- **Line length:** 100 characters
- **Imports:** Sorted with `ruff` (groups: stdlib, third-party, local)

### TypeScript/React

- **Linter:** ESLint with React plugin
- **Style:** Functional components with hooks
- **Naming:** PascalCase for components, camelCase for functions/variables

### Commit Messages

- Use present tense ("Add feature" not "Added feature")
- Be descriptive but concise
- Reference issues when applicable (`Fixes #123`)

Examples:
```
Fix calibration calculation for edge case with zero variance
Add file watcher polling mode for network mounts
Refactor service layer to use workflow orchestration
```

## 🚫 What We're Not Accepting (Yet)

- Database migrations or backwards compatibility layers (pre-alpha policy)
- Alternative ML backends without discussion first
- UI framework changes
- Major architectural changes without RFC

## 📚 Resources

- [Architecture Documentation](docs/dev/architecture.md)
- [API Reference](docs/user/api_reference.md)
- [Copilot Instructions](.github/copilot-instructions.md) (developer context)
- [Layer-Specific Instructions](.github/instructions/)

## 📄 License

By contributing, you agree that your contributions will be licensed under [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/) (same as the project).

## 💬 Questions?

- Open a [Discussion](https://github.com/xiaden/nomarr/discussions)
- Ask in an existing issue thread
- Check the [documentation](docs/)

---

**Thank you for helping make Nomarr better! 🎵**