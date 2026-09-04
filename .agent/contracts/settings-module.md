# Settings Module Contract

Authoritative contract for the per-module persistent settings layer.
The matching implementation lives in
[`backend/common/core/settings_store.py`](../../backend/common/core/settings_store.py)
(shared by both backend apps) and is mounted by each app's own
`_MODULE_DOMAINS` table — `backend/machine/main.py` (port 8000) and
`backend/system/main.py` (port 8001). See
[`.agent/contracts/backend-router.md`](backend-router.md) for which
module id belongs to which app.

> **Modules are mandatory.** Every backend module exposes the four
> canonical settings endpoints through this contract. A module
> without a Pydantic defaults model does not exist — every module
> returns a non-null `BaseModel` from `get_settings_model()`.

## 1. Storage Layout

Settings are persisted per module at:

```
<data_root>/modules/<module_id>/settings.json
```

`data_root` is **per app**, not shared: each app's `main.py` resolves
it as `Path(__file__).resolve().parents[1] / "data"`, which lands at
`backend/machine/data/` for modules owned by the machine backend and
`backend/system/data/` for modules owned by the system service. Each
module owns exactly one file — no shared schemas, no migrations.
Modules that want richer layouts (multiple files, schemas,
validation) wrap this store rather than replace it.

## 2. The Four Canonical Endpoints

The registry mounts the following routes for every module:

| Method | Path                                | Description                                |
|--------|-------------------------------------|--------------------------------------------|
| `GET`  | `/api/v1/modules/{id}/settings`     | Read full payload (defaults merged in).    |
| `GET`  | `/api/v1/modules/{id}/settings/{k}` | Read single key (404 if missing).          |
| `PUT`  | `/api/v1/modules/{id}/settings`     | Replace full payload, returns merged.      |
| `PUT`  | `/api/v1/modules/{id}/settings/{k}` | Upsert single key, returns merged.         |

Modules **must not** add their own settings endpoints. The four
above are sufficient for any JSON-serialisable settings object. If
a module needs custom validation, it should expose its own API at a
non-`/settings` path under the module prefix.

## 3. Atomic Write Contract

Every `PUT` writes through the following sequence:

```python
fd, tmp = tempfile.mkstemp(dir=path.parent)
write_payload(fd)
fsync(fd)
os.replace(tmp, settings.json)
```

`os.replace` is atomic on POSIX filesystems. A process crash mid-write
leaves the previous `settings.json` intact. The temp file is
cleaned up on failure (`os.unlink(tmp)`).

The contract is exercised by the test
`backend/common/tests/test_settings_store.py::test_atomic_write_leaves_no_partial_file_on_interrupt`
which monkey-patches `os.replace` to raise and asserts the original
file is unchanged.

## 4. Defaults Merge — Pydantic Model Required

Every module declares its defaults as a Pydantic model instance.
`SettingsStore` accepts the model at construction:

```python
class CameraSettings(BaseModel):
    resolution: tuple[int, int] = (640, 480)
    fps: int = 10

store = SettingsStore("camera", data_root, defaults=CameraSettings())
```

On every read, defaults are merged underneath the persisted payload:

```python
defaults = {"resolution": (640, 480), "fps": 10}
persisted = {"fps": 30}
merged = {**defaults, **persisted}  # {"resolution": (640, 480), "fps": 30}
```

User-set values always win. New defaults added in a later release
appear automatically for existing deployments without forcing a
migration.

## 5. In-Memory Cache

The store caches the merged payload after every successful read or
write. The next `read_all` returns the cached value without hitting
the filesystem. Writes invalidate and re-populate the cache under a
module-local lock, so concurrent PUTs on the same module cannot race.

Tests verify this in
`test_settings_store.py::test_invalidate_forces_re_read`.

## 6. Validation Rules

The store is intentionally untyped at the storage layer — it stores
any JSON-serialisable value. The Pydantic defaults model is the
single source of truth for the schema; modules validate on the
endpoint boundary (using the Pydantic model) and reject bad input
before it reaches the store.

The frontend has no dedicated settings client abstraction — components
call the generated OpenAPI client directly against the four endpoints
above and treat the payload as opaque JSON; they do no validation of
their own.

## 7. Failure Modes

| Failure | Behaviour |
|---------|-----------|
| File missing | Falls back to defaults; `read_all` returns the merged defaults. |
| File corrupt (JSON parse error) | Logged at ERROR; falls back to an empty dict, then merged with defaults. |
| `PUT` parent dir missing | `mkdir(parents=True, exist_ok=True)` creates the directory on first write. |
| `os.replace` fails | Exception propagates; temp file is cleaned up; original file untouched. |
| Concurrent PUTs | Serialised by a module-local `threading.Lock`. |

## 8. Acceptance Checklist

A settings surface is "ready" when:

- [ ] `get_settings_model()` returns a non-null Pydantic `BaseModel`
      instance.
- [ ] The module id appears in the owning app's `main.py:_MODULE_DOMAINS`
      — and only that app's (see `.agent/contracts/backend-router.md`).
- [ ] All persisted values flow through `read_all` / `write_all` /
      `write_key`.
- [ ] Defaults are Pydantic models so new keys can be added later.
- [ ] The atomic-write property is verified by the included test.
