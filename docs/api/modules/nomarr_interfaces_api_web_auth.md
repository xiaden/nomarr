# nomarr.interfaces.api.web.auth

API reference for `nomarr.interfaces.api.web.auth`.

---

## Classes

### LoginRequest

!!! abstract "Usage Documentation"

### LoginResponse

!!! abstract "Usage Documentation"

### LogoutResponse

!!! abstract "Usage Documentation"

---

## Functions

### login(request: 'LoginRequest')

Authenticate with admin password and receive a session token.

### logout(creds=Depends(verify_session))

Invalidate the current session token (logout).

---
