# Workspace Context

This workspace is managed by the pydantic-deep Demo Agent.

## Directory Structure

- `/workspace/` - Main working directory for generated files (code, charts, reports)
- `/uploads/` - User-uploaded files (CSV, PDF, images, text)
- `/skills/` - Skill definitions (data-analysis, code-review, test-generator)

## Available Capabilities

- **File operations**: read, write, edit, glob, grep files
- **Code execution**: Python code in isolated Docker sandbox (pre-installed: pandas, numpy, matplotlib, scikit-learn, seaborn, plotly)
- **Data analysis**: Load the `data-analysis` skill for CSV analysis with pandas and visualization
- **Code review**: Delegate to the `code-reviewer` subagent for quality and security review
- **Test generation**: Load the `test-generator` skill for pytest test cases
- **GitHub queries**: Mock GitHub API tools (repos, issues, PRs, users)
- **Subagent delegation**: joke-generator, code-reviewer, general-purpose subagents

## Conventions

- Save all generated files (scripts, charts, reports) to `/workspace/`
- Save charts/visualizations as PNG to `/workspace/`
- Save interactive HTML charts to `/workspace/`
- Use TODO list to track multi-step tasks
- Load relevant skills before tackling domain-specific tasks
