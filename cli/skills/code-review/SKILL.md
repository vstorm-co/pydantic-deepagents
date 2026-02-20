---
name: code-review
description: "Systematic code review for bugs, security, style, and performance"
tags: [code-quality, review]
version: "1.0.0"
---

# Code Review

Perform a systematic code review covering these categories:

## Review Checklist

### 1. Correctness
- Logic errors, off-by-one, null/None handling
- Edge cases: empty inputs, large inputs, concurrent access
- Error handling: are exceptions caught and handled properly?

### 2. Security
- Input validation and sanitization
- SQL injection, XSS, command injection
- Secrets in code, hardcoded credentials
- Authentication and authorization checks

### 3. Performance
- Unnecessary loops, N+1 queries
- Missing indexes for database queries
- Large memory allocations, unbounded collections
- Blocking calls in async code

### 4. Style & Maintainability
- Naming clarity (variables, functions, classes)
- Function length — split if >30 lines
- Dead code, commented-out code
- Missing type annotations

### 5. Testing
- Are new code paths covered by tests?
- Are edge cases tested?
- Are error paths tested?

## Output Format

For each issue found:
- **File:line** — category — description — suggested fix
- Severity: critical / warning / suggestion
