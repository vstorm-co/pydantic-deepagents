---
name: performant-code
description: "Writing efficient code that handles large data and tight constraints"
tags: [performance, optimization, benchmark]
version: "1.0.0"
---

# Performant Code

How to write code that won't timeout on large inputs.

## Think About Scale First

Before writing code, ask: how big is the data?

| Data size | Approach |
|-----------|----------|
| < 1 MB | Load into memory, any approach works |
| 1-100 MB | Load into memory, but use efficient algorithms |
| 100 MB - 1 GB | Stream/mmap, avoid loading entirely into memory |
| > 1 GB | Streaming only, chunk-based processing |

## I/O Optimization

### Large files
- **mmap** (C: `mmap()`, Python: `mmap.mmap()`) — map file into memory, OS handles paging
- **Buffered binary reads** — `fread()` in C, `open(f, 'rb').read(chunk)` in Python
- **NEVER** read a 500MB file line-by-line with `fgets()` when you need random access

### Writing output
- Buffer writes — don't call `write()` for every byte
- Use `fwrite()` or `sys.stdout.buffer.write()` for binary output
- Flush only when needed

## Algorithm Complexity

- **O(n)** beats **O(n log n)** beats **O(n²)** — always
- Nested loops on large data = timeout. Restructure to single pass + hash map
- Sorting is O(n log n) — only sort if you need to
- Use hash maps/sets for lookup instead of linear search
- Pre-compute what you can outside loops

## Language-Specific Tips

### C
- Use `mmap()` for large file access
- `-O2` or `-O3` for compiler optimizations
- Avoid `malloc()`/`free()` in tight loops — pre-allocate
- Use `memcpy()` instead of byte-by-byte copying
- Integer arithmetic > floating point when possible

### Python
- Use `numpy` for numerical work (100x faster than pure Python loops)
- `collections.Counter`, `defaultdict` — avoid manual counting
- List comprehensions > explicit loops
- `struct.unpack()` for binary parsing
- `subprocess.run()` > `os.system()`
- For heavy computation: consider writing a small C program instead

### General
- Profile before optimizing — find the actual bottleneck
- If a program hangs, it's likely: infinite loop, deadlock, or I/O bound on huge data
- If a program is slow, check: algorithm complexity, I/O pattern, memory allocation

## Constraints Awareness

- If the task says "< 5000 bytes" — count your bytes, use `wc -c`
- If there's a time limit — test with actual data, not toy inputs
- If there's a memory limit — don't load everything into RAM
- Always verify constraints BEFORE declaring done
