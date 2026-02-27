---
name: test-writer
description: "Generate comprehensive test suites for existing code"
tags: [testing, code-quality]
version: "1.0.0"
---

# Test Writer

Generate comprehensive tests for the target code.

## Process

1. Read the source code to understand all public functions/methods
2. Identify the testing framework already used in the project (pytest, unittest, etc.)
3. Follow existing test patterns and conventions in the project
4. Write tests covering all categories below

## Coverage Strategy

### Happy Path
- Normal inputs with expected outputs
- All public methods/functions

### Edge Cases
- Empty inputs (empty string, empty list, None)
- Boundary values (0, -1, max int)
- Single element collections

### Error Cases
- Invalid input types
- Missing required arguments
- Network/IO failures (mock external calls)

### Integration
- Multiple functions working together
- State changes across calls

## Guidelines

- One test function per behavior, not per method
- Descriptive test names: `test_<what>_<condition>_<expected>`
- Use fixtures for shared setup
- Mock external dependencies (APIs, databases, filesystem)
- Assert specific values, not just truthiness
- Test both return values and side effects
