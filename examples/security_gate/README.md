# Security Gate Example

Demonstrates [`default_security_hook()`][pydantic_deep.features.hooks.default_security_hook] —
the built-in safety preset that blocks destructive commands, path-traversal
writes, and credential reads, plus redacts secret-shaped tokens from tool output.

## Run

```bash
uv run python examples/security_gate/main.py
```

## What it shows

1. **Out-of-the-box defaults** — drop the preset in and dangerous shell calls,
   `~/.ssh/*` reads, and `..` traversal writes are denied automatically.
2. **Extending the rules** — concatenate with `DEFAULT_BLOCKED_COMMANDS` to add
   project-specific patterns (e.g. blocking `sudo`).
3. **Tighter write boundary** — pass `allowed_write_roots` to require every
   write to resolve inside a sandbox directory.
4. **Secret redaction** — show how a fake AWS key in tool output becomes
   `[REDACTED]` before the model sees it.

See [docs/advanced/hooks.md](../../docs/advanced/hooks.md) (Built-in Security
Preset section) for the full reference.
