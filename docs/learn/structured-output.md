# Structured output

So far your agent has handed back a string. That's fine when a human reads the
answer — but the moment you want to *use* it in code (store it, branch on it,
pass it to another function), a string means parsing, guessing, and brittle
`json.loads`. Point `output_type` at a Pydantic model instead, and
`result.output` comes back as a validated instance of exactly that model.

```python
import asyncio

from pydantic import BaseModel, Field
from pydantic_deep import create_deep_agent, DeepAgentDeps, StateBackend


class CodeReview(BaseModel):
    summary: str = Field(description="One-sentence verdict on the code.")
    issues: list[str]
    severity: str
    approved: bool


async def main():
    agent = create_deep_agent(
        model="anthropic:claude-sonnet-4-6",
        instructions="You are a meticulous code reviewer.",
        output_type=CodeReview,
    )

    deps = DeepAgentDeps(backend=StateBackend())

    result = await agent.run(
        "Review this function:\n\n"
        "def divide(a, b):\n"
        "    return a / b",
        deps=deps,
    )

    review = result.output
    print(review.summary)
    print("Approved:", review.approved)
    for issue in review.issues:
        print(" -", issue)


asyncio.run(main())
```

## Run it

Save it to `main.py` and run:

<div class="termy">

```console
$ python main.py
```

</div>

You'll see something like:

```text
The function works but lacks guarding against division by zero.
Approved: False
 - No handling for b == 0 (raises ZeroDivisionError)
 - Missing type hints and a docstring
```

`result.output` is not a string here — it's a real `CodeReview` instance.
`review.approved` is a `bool` you can branch on, `review.issues` is a `list[str]`
you can iterate. No parsing step in sight.

!!! example "Check it"
    Add `print(type(result.output))` after the run. You'll see
    `<class '__main__.CodeReview'>` — the model your editor already knows the
    shape of.

## Step by step

The only new idea on this page is one parameter. Let's look at the pieces.

### Step 1: describe the shape you want

```python hl_lines="2 3 4 5"
class CodeReview(BaseModel):
    summary: str = Field(description="One-sentence verdict on the code.")
    issues: list[str]
    severity: str
    approved: bool
```

A plain Pydantic `BaseModel`. Each field is a slot the agent has to fill, and the
types are a contract: `approved` *will* be a `bool`. Use `Field(description=...)`
to tell the model what a field means — it reads those descriptions and fills the
slots accordingly, so a good description is the cheapest way to improve results.

### Step 2: point the agent at it

```python hl_lines="4"
agent = create_deep_agent(
    model="anthropic:claude-sonnet-4-6",
    instructions="You are a meticulous code reviewer.",
    output_type=CodeReview,
)
```

`output_type=CodeReview` is the whole feature. It's handed straight to Pydantic
AI, which tells the model to emit data in that shape and validates whatever comes
back. Everything else about the agent — files, shell, planning, sub-agents — is
exactly as before; structured output just changes the *return type*.

### Step 3: read it back, typed

```python
review = result.output       # a CodeReview, not a str
print(review.summary)
print(review.approved)
```

Because the agent now has type `Agent[DeepAgentDeps, CodeReview]`, your editor
and type-checker know `result.output` is a `CodeReview`. Attribute access,
autocomplete, and `reveal_type()` all just work.

## Validation comes for free

You don't write parsing or validation — Pydantic AI does it. If the model
returns something that doesn't fit your schema (a string where you asked for an
`int`, a missing field), Pydantic AI catches the error and **automatically asks
the model to try again** with the validation message attached. By the time
`result.output` reaches you, it has already passed validation.

That means your own `Field` constraints are enforced too:

```python
from pydantic import BaseModel, Field


class Rating(BaseModel):
    score: int = Field(ge=1, le=10, description="Quality from 1 to 10.")
    explanation: str
```

A `score` of `11` won't slip through — Pydantic rejects it, and the agent
retries until it produces a value in range.

!!! tip "Make fields descriptive, not just typed"
    The model only sees your field names, types, and descriptions. Specific names
    (`security_concerns` beats `notes`) and a one-line `Field(description=...)`
    do more for quality than any amount of prompt-wrangling.

!!! note "Structured output works with every tool"
    An agent with `output_type=` can still read files, run the shell, search the
    web, and delegate to sub-agents. It does all of its work as normal and only
    shapes the *final* answer into your model — so "go read the repo and return a
    `RepoSummary`" is a perfectly good prompt.

!!! info "Nesting and enums are fine"
    A field can be another `BaseModel`, a `list[Step]`, an `Optional[...]`, or an
    `Enum` — anything Pydantic can validate. Build the shape your code wants and
    let the agent fill it in.

## Recap

You swapped a string answer for typed data:

- `output_type=SomeBaseModel` makes `create_deep_agent()` return an
  `Agent[DeepAgentDeps, SomeBaseModel]`, and `result.output` is a validated
  instance of that model.
- Fields are a contract — types are guaranteed, and `Field(description=...)`
  guides the model on how to fill them.
- Validation and retries are handled by Pydantic AI; by the time you touch
  `result.output`, it has already passed your schema (constraints included).
- Nested models, lists, optionals, and enums all work, and structured output
  composes with every other agent capability.

Next, let's watch the agent work in real time instead of waiting for the result.

- [Streaming →](streaming.md)
