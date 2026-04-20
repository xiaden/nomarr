# API Application Layer

FastAPI application setup, authentication, and ID encoding for HTTP transport.

## Responsibilities

- Create and configure the FastAPI application with lifespan management
- Authenticate requests via API key or session token
- Encode/decode ArangoDB `_id` fields for safe HTTP transport (`collection/key` ↔ `collection:key`)
- Serve the SPA dashboard and handle catch-all routing

## Key Modules

 | Module | Purpose |
 | -------- | -------- |
 | `api_app.py` | FastAPI app factory — lifespan, exception handler, SPA serving, health check |
 | `auth.py` | `verify_key`, `verify_session`, password hashing, session create/validate/invalidate |
 | `id_codec.py` | `encode_id`/`decode_id` for ArangoDB IDs, recursive `encode_ids` for response data |
 | `INTERFACE_STATUS.md` | Tracks API endpoint completion status |

## Subfolders

 | Folder | Purpose |
 | -------- | -------- |
 | `types/` | Pydantic request/response models (13 domain-specific type files) |
 | `v1/` | Versioned public API routes (admin, navidrome, public info) |
 | `web/` | Internal web dashboard endpoints (16 endpoint files + router + DI) |

## Patterns

- **ID encoding**: All ArangoDB `_id` fields are encoded before HTTP responses and decoded on ingress via `decode_path_id` or `EncodedId` Pydantic type
- **Auth dependency**: `verify_key` and `verify_session` are FastAPI `Depends()` guards on protected routes
- **SPA catch-all**: Non-API paths serve `index.html` for client-side React Router

## Dependencies

- **Calls**: services (via FastAPI `Depends()` in endpoint handlers)
- **MUST NOT** import or access persistence directly
- **Imports**: `helpers/dto` for shared types, `KeyManagementService` for auth
