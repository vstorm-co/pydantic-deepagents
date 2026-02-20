---
name: systematic-debugging
description: "Systematic approach to diagnosing and fixing errors"
tags: [debugging, errors, benchmark]
version: "1.0.0"
---

# Systematic Debugging

A structured approach to finding and fixing bugs.

## The Debugging Loop

```
1. REPRODUCE → 2. ISOLATE → 3. DIAGNOSE → 4. FIX → 5. VERIFY
```

Never skip steps. Never guess-and-check repeatedly.

## Step 1: Reproduce

- Run the exact command that fails
- Capture FULL output (stdout AND stderr)
- Note: exit code, error message, stack trace
- If intermittent, identify what changes between runs

## Step 2: Isolate

- What's the MINIMAL input that triggers the error?
- Which specific line/function fails? (read the traceback bottom-up)
- Is it a compile error, runtime error, or wrong output?
- Does it fail on all inputs or specific ones?

## Step 3: Diagnose

### Read the error message carefully

| Error type | Where to look |
|-----------|---------------|
| Compile error | The FIRST error (later ones are often cascading) |
| Segfault | Last function in the stack trace, check array bounds and null pointers |
| Python traceback | The innermost frame (bottom), but also check the middle for context |
| Wrong output | Diff expected vs actual: `diff <(expected) <(actual)` |
| Timeout/hang | Is it an infinite loop? Deadlock? I/O bound? Add a timer or counter |

### Add minimal instrumentation

- C: `fprintf(stderr, "reached checkpoint %d\n", __LINE__);`
- Python: `print(f"DEBUG: {var=}", file=sys.stderr)`
- Check intermediate values, not just final output
- Remove debug prints after fixing

## Step 4: Fix

- Change ONE thing at a time
- If the same approach fails 3 times → completely different strategy
- Don't add workarounds — fix the root cause
- Common root causes:
  - Off-by-one errors (loop bounds, array indexing)
  - Type mismatches (int vs float, signed vs unsigned)
  - Encoding issues (UTF-8 vs bytes)
  - Path errors (relative vs absolute, missing trailing slash)
  - Race conditions (file not written yet, process not started)

## Step 5: Verify

- Run the same command that failed before
- Test with multiple inputs, not just the one that was failing
- Check edge cases: empty input, single element, very large input
- Run any existing test suite

## Common Failure Patterns

### "It compiles but gives wrong output"
1. Print all intermediate values
2. Compare with a known-correct reference implementation
3. Check: integer overflow, floating point precision, endianness

### "It works on small input but times out on large"
1. Check algorithm complexity — O(n²) on 1M items = timeout
2. Profile: which loop/function takes the most time?
3. Restructure: hash maps, sorting, streaming

### "It works locally but fails in the test"
1. Check: absolute vs relative paths
2. Check: different working directory
3. Check: different input format than expected
4. Read the test script to understand what it actually checks
