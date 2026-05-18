"""Manual verification for issue #108 — Windows execute crash.

Runs on a Windows GitHub Actions runner to confirm that `LocalBackend.execute()`
and `LocalBackend.async_execute()` work after bumping the `pydantic-ai-backend`
floor to `>=0.2.7`. The original failure was that 0.2.4 hardcoded
`["sh", "-c", command]`, so `subprocess.run` failed to spawn the shell wrapper
itself with `[WinError 2]`. 0.2.7 routes through `cmd /c` on `win32`.

Delete this file (and `.github/workflows/verify-108.yml`) after the issue is
confirmed fixed on Windows.
"""

from __future__ import annotations

import asyncio
import base64
import os
import sys
import tempfile

from pydantic_ai_backends import LocalBackend


def _section(title: str) -> None:
    print(f"\n--- {title} ---", flush=True)


def _ps_encoded(script: str) -> str:
    """Build a `powershell -EncodedCommand <base64>` invocation.

    Avoids the cmd-/c → powershell quote-mangling that turns
    `powershell -Command "..."` into a string-literal expression.
    """
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    return f"powershell -NoProfile -EncodedCommand {encoded}"


def main() -> int:
    print(f"platform: {sys.platform}", flush=True)
    print(f"python: {sys.version}", flush=True)

    tmp = tempfile.mkdtemp(prefix="verify_108_")
    backend = LocalBackend(root_dir=tmp)
    print(f"tmp root: {tmp}", flush=True)

    # 1) The core #108 regression: did the shell wrapper itself spawn?
    #    On 0.2.4 this raised [WinError 2] because sh is not on Windows PATH.
    _section("backend.execute('dir')  —  shell wrapper smoke")
    r = backend.execute("dir")
    print(f"exit_code: {r.exit_code}")
    print(f"output (first 200): {r.output[:200]!r}")
    assert r.exit_code == 0, f"shell wrapper failed: exit_code={r.exit_code}"
    assert "Directory of" in r.output, "dir output didn't look like dir output"

    # 2) Cmd-builtin folder deletion — the simplest cross-shell path.
    target = os.path.join(tmp, "bozo_cmd")
    os.makedirs(target)
    assert os.path.exists(target)

    _section(f"backend.execute('rmdir /s /q ...')  —  cmd builtin on {target}")
    r = backend.execute(f'rmdir /s /q "{target}"')
    print(f"exit_code: {r.exit_code}")
    print(f"output: {r.output!r}")
    assert not os.path.exists(target), f"folder still exists: {target}"

    # 3) PowerShell folder deletion via -EncodedCommand — quote-safe across
    #    the cmd /c → powershell boundary.
    target2 = os.path.join(tmp, "bozo_ps_encoded")
    os.makedirs(target2)

    _section(f"backend.execute(powershell -EncodedCommand ...) on {target2}")
    r = backend.execute(_ps_encoded(f"Remove-Item -Recurse -Force '{target2}'"))
    print(f"exit_code: {r.exit_code}")
    print(f"output: {r.output!r}")
    assert not os.path.exists(target2), f"folder still exists: {target2}"

    # 4) async_execute path (new in 0.2.7) — same PowerShell scenario.
    target3 = os.path.join(tmp, "bozo_async")
    os.makedirs(target3)

    _section(f"backend.async_execute(powershell -EncodedCommand ...) on {target3}")
    r = asyncio.run(backend.async_execute(_ps_encoded(f"Remove-Item -Recurse -Force '{target3}'")))
    print(f"exit_code: {r.exit_code}")
    print(f"output: {r.output!r}")
    assert not os.path.exists(target3), f"folder still exists: {target3}"

    # 5) Diagnostic — document the LLM-naive pattern that DOES NOT execute on
    #    Windows because of cmd /c quoting. Not an assertion; informational.
    target4 = os.path.join(tmp, "bozo_naive_ps")
    os.makedirs(target4)

    _section('diagnostic: powershell -Command "..."  (naive LLM pattern)')
    naive_cmd = f"powershell -Command \"Remove-Item -Recurse -Force '{target4}'\""
    r = backend.execute(naive_cmd)
    print(f"command sent: {naive_cmd!r}")
    print(f"exit_code: {r.exit_code}")
    print(f"output: {r.output!r}")
    still_exists = os.path.exists(target4)
    print(f"folder still exists: {still_exists}")
    if still_exists:
        print(
            "NOTE: this pattern produced exit_code=0 but PowerShell echoed the "
            "command instead of executing it — known quoting issue across the "
            "cmd /c → powershell boundary. Not a #108 regression."
        )

    print("\nAll #108 regression checks passed.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
