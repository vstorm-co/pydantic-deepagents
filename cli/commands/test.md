---
description: "Run tests, analyze failures, suggest fixes"
argument-hint: "[test path or pattern]"
---

# Run Tests

1. Detect the test framework:
   - Check for `pyproject.toml` with `[tool.pytest]` -> use `pytest`
   - Check for `package.json` with test script -> use `npm test` / `bun test`
   - Check for `Makefile` with test target -> use `make test`
2. Run the tests:
   - If `$ARGUMENTS` is provided: run tests matching that path or pattern
   - Otherwise: run the full test suite
3. If tests pass: report the summary (total, passed, skipped).
4. If tests fail:
   - Parse the error output
   - Read the failing test files
   - Read the source code being tested
   - Explain why each test fails
   - Suggest specific fixes
