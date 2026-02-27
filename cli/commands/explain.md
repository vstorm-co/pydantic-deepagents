---
description: "Explain a file, function, or module"
argument-hint: "<file path or symbol name>"
---

# Explain Code

Provide a clear explanation of the specified code.

1. Find the code to explain:
   - If `$ARGUMENTS` is a file path: read that file
   - If `$ARGUMENTS` looks like a symbol name: search for it in the codebase
   - If `$ARGUMENTS` is empty: explain the project structure
2. Explain:
   - **Purpose**: What does this code do and why does it exist?
   - **How it works**: Walk through the key logic step by step
   - **Dependencies**: What does it depend on and what depends on it?
   - **Key patterns**: Notable design patterns or techniques used
3. Keep the explanation concise and practical. Focus on understanding, not restating the code.
