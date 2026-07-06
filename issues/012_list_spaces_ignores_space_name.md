# 012 — `filter_spaces_by_name` only matches `space_name`, not `space_id`

**Status**: Fixed  
**Severity**: Medium  
**Component**: `vitalgraph/api/vitalgraph_api.py` — `filter_spaces_by_name` and `list_spaces`

## Summary

Two related bugs make the filter/list space endpoints inconsistent and unreliable:

1. **`filter_spaces_by_name`** only matches against `space_impl.space_name`, never
   `space_id`. If `space_name` has been changed (via `update_space`), a user cannot
   find a space by its ID through the filter endpoint.

2. **`list_spaces`** hardcodes `space_name = space_id` in its response, hiding the
   real display name from clients entirely.

## Root Cause

### Bug A: `filter_spaces_by_name` ignores `space_id`

`vitalgraph/api/vitalgraph_api.py` line ~401:

```python
for space_id, space_record in self.space_manager._spaces.items():
    space_name = getattr(space_record.space_impl, 'space_name', space_id)
    if name_filter.lower() in space_name.lower():   # ← only checks space_name
        ...
```

After `update_space` sets `space_impl.space_name = "Verify Update Test"` (line 292),
filtering by the space_id `"apitest_485eb319"` fails because `"apitest_485eb319"` is
not a substring of `"verify update test"`.

### Bug B: `list_spaces` hardcodes `space_name`

`vitalgraph/api/vitalgraph_api.py` line ~184:

```python
spaces.append({
    'space': space_record.space_id,
    'space_name': space_record.space_id,  # ← hardcoded, ignores real name
    'exists': True
})
```

## Failure Sequence (test_spaces.py)

1. `TestSpaceUpdate.test_update_space_verify` calls `update_space` with
   `space_name="Verify Update Test"`
2. Server sets `space_record.space_impl.space_name = "Verify Update Test"` in memory
3. `TestSpaceFilter.test_filter_by_prefix` calls `filter_spaces(name_filter=space_id)`
4. Server checks `"apitest_xxx" in "verify update test"` → **False** → empty result

## Proposed Fix

**Bug A** — match against both `space_id` and `space_name`:

```python
for space_id, space_record in self.space_manager._spaces.items():
    space_name = getattr(space_record.space_impl, 'space_name', space_id)
    if (name_filter.lower() in space_name.lower()
            or name_filter.lower() in space_id.lower()):
        ...
```

**Bug B** — return the real name from `list_spaces`:

```python
spaces.append({
    'space': space_record.space_id,
    'space_name': getattr(space_record.space_impl, 'space_name', space_record.space_id),
    'space_description': getattr(space_record.space_impl, 'space_description', ''),
    'exists': True
})
```

## Failing Test

`tests/api/test_spaces.py::TestSpaceFilter::test_filter_by_prefix` — asserts that
filtering by `space_id` returns the space. Currently fails due to Bug A.
