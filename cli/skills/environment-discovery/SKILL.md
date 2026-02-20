---
name: environment-discovery
description: "Systematic exploration of unknown environments before starting work"
tags: [exploration, setup, benchmark]
version: "1.0.0"
---

# Environment Discovery

When dropped into an unfamiliar environment, ALWAYS explore before acting.

## Step 1: Understand the workspace

```
ls -la /app/          # or the working directory
find . -type f | head -50
```

- What files exist? What are their sizes?
- Are there READMEs, Makefiles, config files?
- What languages/frameworks are involved?

## Step 2: Inspect data files

Before writing any code that reads data, understand the format:

- `file <filename>` — detect file type (binary, text, encoding)
- `head -20 <file>` — first lines of text files
- `xxd <file> | head -20` — hex dump for binary files
- `wc -l <file>` — line count for text files
- `stat <file>` — exact file size in bytes
- `python3 -c "import struct; ..."` — parse binary headers

## Step 3: Check available tools

```
which python3 gcc g++ make cmake node npm cargo rustc java go
pip list 2>/dev/null | head -20
```

- What compilers/interpreters are installed?
- What libraries are available?
- What package managers can you use?

## Step 4: Read existing code

If there are existing source files:
- Read them FULLY before modifying
- Understand the build system (Makefile, CMakeLists.txt, pyproject.toml)
- Check for existing tests

## Key Principles

- NEVER assume file formats — always inspect first
- NEVER assume tools are installed — always check
- A 500MB file is NOT a "small file" — plan for it
- Binary files need byte-level inspection, not `cat`
- Spend 30 seconds exploring to save 5 minutes debugging
