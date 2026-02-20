---
name: verification-strategy
description: "Thorough verification of completed work before declaring done"
tags: [testing, verification, benchmark]
version: "1.0.0"
---

# Verification Strategy

How to verify your work is correct before declaring a task complete.

## The Verification Checklist

After implementing a solution, go through ALL of these:

### 1. Re-read the original task
- Re-read the EXACT wording of the task instruction
- Check every requirement — file paths, names, formats, constraints
- Are there implicit requirements? ("compile with gcc -O3 -lm" means exact flags)

### 2. Check file outputs
- Do all required files exist at the exact paths specified?
- Are file sizes within any stated limits?
- Is the file format correct? (binary vs text, encoding, line endings)

```bash
ls -la /path/to/expected/output
wc -c /path/to/output    # byte count
file /path/to/output      # format detection
head -5 /path/to/output   # content preview
```

### 3. Compile and run
- Compile with the EXACT flags specified in the task
- Run with the EXACT command and arguments specified
- Check exit code: `echo $?` (should be 0 for success)
- Check both stdout AND stderr

### 4. Validate output
- Compare output against expected format
- Check exact field names, delimiters, number formatting
- If the task specifies output format, match it exactly:
  - JSON: valid JSON? correct schema?
  - CSV: correct headers? correct delimiter?
  - Plain text: correct line endings? trailing newline?

### 5. Test edge cases
- Empty input (if applicable)
- The specific test inputs mentioned in the task
- Large inputs (if the task involves performance)

### 6. Check constraints
- Size limits (file size, code length)
- Time limits (does it finish in reasonable time?)
- Memory limits (does it stay within bounds?)
- No external dependencies that aren't available

## Reading Test Scripts

If you can find the test script, READ IT:
- What exact assertions does it make?
- What inputs does it use?
- What output format does it expect?
- What timeouts are set?

Tests often check things you didn't expect:
- Exact string matching (whitespace matters!)
- Specific numeric precision
- File permissions
- Process exit codes

## Common Verification Failures

| What you think is right | What the test actually checks |
|------------------------|-------------------------------|
| Output on stdout | Output in a specific file |
| Human-readable numbers | Exact decimal precision |
| Relative file paths | Absolute file paths |
| "Close enough" answer | Exact match |
| Code that runs | Code under a specific size limit |

## Final Check

Before declaring done, ask yourself:
1. Did I create/modify ALL the files the task asks for?
2. Did I use the EXACT paths, names, and formats specified?
3. Does my code compile/run WITHOUT errors?
4. Does my output match what automated tests would expect?
5. Have I cleaned up any debug output or temporary files?
