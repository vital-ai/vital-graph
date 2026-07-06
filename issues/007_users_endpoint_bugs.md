# Users endpoint: update_user parameter mismatch + missing filter route

## Bug 1: update_user passes raw dict to DB method

### Summary

`vitalgraph_api.update_user()` passes the entire `user_data` dict as a
positional argument to `db.update_user()`, which expects individual keyword
arguments (`email=`, `full_name=`, `role=`, `is_active=`).

### Root Cause

`vitalgraph/api/vitalgraph_api.py:506`:
```python
updated_user = await self.db.update_user(user_id, user_data)
```

`db.update_user` signature: `(user_id, email=None, full_name=None, role=None, is_active=None) -> bool`

The dict lands in the `email` positional parameter, causing:
`expected str, got dict`

### Additional issue

`db.update_user` returns `bool`, but the endpoint treated it as a dict
and called `.get()` on it → `AttributeError: 'bool' object has no attribute 'get'`.

### Fix

Unpack the dict into keyword args in `vitalgraph_api.update_user()` and
handle the bool return in the endpoint. **Resolved.**

---

## Bug 2: Missing `/api/users/filter` server route

### Summary

The client `UsersEndpoint.filter_users()` called `GET /api/users/filter`,
but no such route existed on the server. The call returned 404.

### Fix

Added an optional `name_filter` query parameter to the existing
`GET /api/users` route. The client `filter_users()` now calls
`GET /api/users?name_filter=...` instead of the non-existent
`/api/users/filter`. **Resolved.**

---

## Bug 3: delete_user response missing `deleted_count`

### Summary

`api.delete_user()` returns `{'message': ..., 'id': ...}` but the endpoint
declares `response_model=UserDeleteResponse` which requires `deleted_count`.
FastAPI raises `ResponseValidationError`.

### Fix

Endpoint now constructs `UserDeleteResponse(deleted_count=1, ...)` directly
instead of returning the raw dict. **Resolved.**

---

## Bug 4: update_user passes username string where DB expects int user_id

### Summary

`api.update_user()` passed the username string directly to `db.update_user()`
as the first positional arg. The DB method expects the integer `user_id`
primary key, causing `'str' object cannot be interpreted as an integer`.

### Fix

`api.update_user()` now looks up the user by username first and passes
`old_user["user_id"]` (the int PK) to `db.update_user()`. **Resolved.**

---

## Bug 5: name_filter NoneType error

### Summary

`list_users` filter comparison called `.lower()` on `full_name` which can be
`None`, causing `'NoneType' object has no attribute 'lower'`.

### Fix

Changed `u.get('full_name', '').lower()` to `(u.get('full_name') or '').lower()`
to handle `None` values. **Resolved.**

## Discovered

During API endpoint test coverage expansion (test_users_api.py).
