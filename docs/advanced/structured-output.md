# Structured Output

pydantic-deep supports structured output through Pydantic models, allowing you to get type-safe responses from your agents.

## Basic Usage

Use the `output_type` parameter to specify the expected response format:

```python
from pydantic import BaseModel
from pydantic_deep import create_deep_agent, create_default_deps

class TaskAnalysis(BaseModel):
    summary: str
    priority: str
    estimated_hours: float
    tags: list[str]

# Create agent with structured output
agent = create_deep_agent(output_type=TaskAnalysis)

deps = create_default_deps()
result = await agent.run(
    "Analyze this task: implement user authentication with OAuth",
    deps=deps,
)

# Type-safe access to the response
print(result.output.summary)
print(result.output.priority)
print(result.output.estimated_hours)
```

## Complex Models

You can use nested Pydantic models for complex responses:

```python
from pydantic import BaseModel, Field

class Step(BaseModel):
    description: str
    estimated_time: str
    dependencies: list[str] = Field(default_factory=list)

class ProjectPlan(BaseModel):
    title: str
    overview: str
    steps: list[Step]
    total_estimated_hours: float
    risks: list[str]

agent = create_deep_agent(output_type=ProjectPlan)

result = await agent.run(
    "Create a plan for building a REST API with authentication",
    deps=deps,
)

for i, step in enumerate(result.output.steps, 1):
    print(f"{i}. {step.description} ({step.estimated_time})")
```

## Optional Fields

Use `Optional` types for fields that may not always be present:

```python
from pydantic import BaseModel
from typing import Optional

class CodeReview(BaseModel):
    file_path: str
    issues_found: int
    severity: str
    suggestions: list[str]
    security_concerns: Optional[str] = None

agent = create_deep_agent(output_type=CodeReview)
```

## Validation

Pydantic automatically validates the LLM's response:

```python
from pydantic import BaseModel, Field, field_validator

class Rating(BaseModel):
    score: int = Field(ge=1, le=10)
    explanation: str

    @field_validator("explanation")
    @classmethod
    def explanation_not_empty(cls, v):
        if not v.strip():
            raise ValueError("Explanation cannot be empty")
        return v

agent = create_deep_agent(output_type=Rating)
```

## Combining with Tools

Structured output works alongside all agent tools:

```python
from pydantic import BaseModel
from pydantic_deep import create_deep_agent, create_default_deps, StateBackend

class FileAnalysis(BaseModel):
    file_count: int
    total_lines: int
    languages_detected: list[str]
    summary: str

agent = create_deep_agent(
    output_type=FileAnalysis,
    include_filesystem=True,  # Agent can use file tools
)

# Agent reads files and returns structured analysis
deps = create_default_deps(backend=StateBackend())
result = await agent.run(
    "Analyze the files in the /src directory",
    deps=deps,
)

print(f"Found {result.output.file_count} files")
print(f"Languages: {', '.join(result.output.languages_detected)}")
```

## Type Inference

When using `output_type`, the agent's return type is properly inferred:

```python
from pydantic import BaseModel
from pydantic_deep import create_deep_agent

class Summary(BaseModel):
    title: str
    content: str

# Agent type is Agent[DeepAgentDeps, Summary]
agent = create_deep_agent(output_type=Summary)

result = await agent.run("Summarize this document", deps=deps)
# result.output is typed as Summary
reveal_type(result.output)  # Summary
```

## Enum Constraints

Use enums to constrain possible values:

```python
from enum import Enum
from pydantic import BaseModel

class Priority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class TaskClassification(BaseModel):
    category: str
    priority: Priority
    assigned_team: str

agent = create_deep_agent(output_type=TaskClassification)
```

## ResponseFormat Type Alias

For convenience, `ResponseFormat` is exported as an alias:

```python
from pydantic_deep import ResponseFormat

# ResponseFormat is an alias for pydantic-ai's OutputSpec
# Use it for type hints in your code
def process_output(output: ResponseFormat) -> None:
    ...
```

## Best Practices

1. **Keep models focused**: Create specific models for each task rather than one large model

2. **Use Field descriptions**: Help the LLM understand what's expected:
   ```python
   class Analysis(BaseModel):
       summary: str = Field(description="A 2-3 sentence summary")
       confidence: float = Field(ge=0, le=1, description="Confidence score 0-1")
   ```

3. **Provide examples in instructions**: Guide the LLM with example outputs:
   ```python
   agent = create_deep_agent(
       output_type=Analysis,
       instructions="""
       Analyze the given text and return structured data.
       Example output structure:
       - summary: Brief overview of the content
       - confidence: How confident you are in the analysis
       """
   )
   ```

4. **Handle validation errors**: Wrap agent calls in try/except for validation failures

## Next Steps

- [History Processors](processors.md) - Manage conversation context
- [Streaming](streaming.md) - Real-time response handling
- [Examples](../examples/index.md) - More usage examples
