---
type: Reference
title: Scoped database runtime
status: Accepted
tags: [public-api, database, runtime]
---

# Scoped database runtime

`database_runtime_scope()` is an additive public synchronous context manager for
hosts that select a different database configuration for each operation.

```python
from genai_tag_db_tools import (
    database_runtime_scope,
    get_tag_reader,
    initialize_databases,
)

with database_runtime_scope():
    initialize_databases(user_db_dir="/selected/workspace/tag-data", format_name="Lorairo")
    reader = get_tag_reader()
    # Complete all reader/writer work and close sessions before leaving the scope.
```

Entry saves the current base/user database paths, engines and session factories,
then exposes an uninitialized runtime. Entry itself does no file or network I/O.
Initialization inside the scope follows the usual selected-directory behavior.
Exit disposes engines created inside the scope and restores the exact previous
runtime handles. It does not reopen, migrate, initialize or write the old database.
Exceptions also restore the previous state. Disposal failures are collected into
an ExceptionGroup after restoration; an operation failure remains in its exception
context. Previously active engines are preserved.

Scopes can nest on the same thread. A reentrant lock serializes scopes across
threads for their entire duration. This does **not** make legacy unscoped runtime
access safe while another thread has a scope active. All concurrent users must
cooperate by using scopes, or the host must ensure exclusive runtime access.
Do not await or interleave asynchronous tasks inside this synchronous scope.
Finish workers inside the scope and do not use its readers, repositories, sessions
or engines after exit. A worker must not enter another scope while its parent
thread holds a scope and waits for that worker.

Query cancellation callback registration is process-wide and is unaffected by
workspace selection. Existing callers that do not use a scope retain their
current initialization behavior. Scope exit does not undo writes made to the
selected database during the operation.
