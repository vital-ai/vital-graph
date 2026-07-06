# Missing UserCreate model — client cannot create users

## Summary

The server endpoint `POST /api/users` and the client's `add_user()` both
accept the `User` model, which correctly does **not** contain a password.
However the server-side `add_user` implementation extracts `password` from
the user dict and raises `ValueError("Password is required")` when absent.

Because there is no separate `UserCreate` request model that carries the
password, **user creation through the typed client always fails with 400**.

## Root Cause

The server endpoint (`users_endpoint.py`) accepts `User` as the request
body, calls `user.dict()`, and forwards it to `vitalgraph_api.add_user()`
which expects `password` in that dict:

`vitalgraph/api/vitalgraph_api.py:451-456`:
```python
password = user_data.get('password', '')
...
if not password:
    raise ValueError("Password is required")
```

The `User` model (correctly) has no `password` field, so `model_dump()`
never includes one.  There is no `UserCreate` model to bridge the gap.

## Impact

- Client method `vg_client.users.add_user(user)` always fails.
- Any code or test that creates users through the typed client is broken.
- The admin UI may work because it sends raw JSON with a `password` key
  directly, bypassing the Pydantic model.

## Suggested Fix

Introduce a `UserCreate` request model that includes a password field:

```python
class UserCreate(BaseModel):
    username: str
    password: str
    full_name: Optional[str] = ""
    email: Optional[str] = ""
    role: str = "Viewer"
```

Then update:
1. Server route `POST /api/users` to accept `UserCreate` instead of `User`.
2. Client `UsersEndpoint.add_user()` to accept `UserCreate`.

The existing `User` model remains unchanged — it should never carry a
password.

## Reproduction

```python
from vitalgraph.model.users_model import User

user = User(username="testuser", role="Viewer", full_name="Test")
resp = await vg_client.users.add_user(user)
# → VitalGraphClientError: Request failed (400): Password is required
```

## Status

**Resolved.** `UserCreate` model added to `users_model.py`. Server endpoint
and client updated to use it.

## Discovered

During API endpoint test coverage expansion (test_users_api.py).
