# nomarr.interfaces.api.auth

API reference for `nomarr.interfaces.api.auth`.

---

## Functions

### cleanup_expired_sessions() -> 'int'

Cleanup expired sessions using the singleton KeyManagementService instance.

### create_session() -> 'str'

Create a new session using the singleton KeyManagementService instance.

### get_admin_password_hash() -> 'str'

Get admin password hash using the singleton KeyManagementService instance.

### get_key_service() -> 'KeyManagementService'

Get the KeyManagementService singleton instance.

### hash_password(password: 'str') -> 'str'

Hash a password. Pure utility function - stateless.

### invalidate_session(session_token: 'str') -> 'None'

Invalidate a session using the singleton KeyManagementService instance.

### load_sessions_from_db() -> 'int'

TODO: describe load_sessions_from_db

### validate_session(session_token: 'str') -> 'bool'

Validate a session token using the singleton KeyManagementService instance.

### verify_key(creds: 'HTTPAuthorizationCredentials' = Depends(HTTPBearer))

TODO: describe verify_key

### verify_password(password: 'str', password_hash: 'str') -> 'bool'

Verify a password against a hash. Pure utility function - stateless.

### verify_session(creds: 'HTTPAuthorizationCredentials' = Depends(HTTPBearer))

Verify session token using the singleton KeyManagementService instance.

---
