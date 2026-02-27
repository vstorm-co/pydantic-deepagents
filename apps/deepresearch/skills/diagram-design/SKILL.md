---
name: diagram-design
description: Best practices for creating research diagrams with Excalidraw MCP tools
---

# Diagram Design Guide for Research

## When to Create Diagrams

Create a diagram when your research findings involve:
- **Comparing 3+ options** — comparison table or matrix diagram
- **Process with 4+ steps** — flowchart or sequence diagram
- **System with multiple components** — architecture diagram
- **Chronological events** — timeline
- **Hierarchical relationships** — tree or mind map
- **Data flows** — data flow diagram

## Excalidraw Workflow

1. **Plan the diagram** — decide type, elements, and layout before creating
2. **Create elements** — use `create_element` or `batch_create_elements`
3. **Arrange** — use `align_elements` and `distribute_elements` for clean layout
4. **Inspect** — use `describe_scene` to verify the diagram looks right
5. **Adjust** — use `update_element` to fix positioning or text
6. **Group** — use `group_elements` to lock related items together

> **Note:** Do NOT export or share links — the user sees a live embedded canvas that auto-syncs.

## Color Palette

Use consistent colors across diagrams:

| Purpose | Color | Hex |
|---------|-------|-----|
| Primary concepts | Blue | #1971c2 |
| Positive / supported | Green | #2f9e44 |
| Negative / limitations | Red | #e03131 |
| Warning / caveats | Orange | #e8590c |
| Neutral / context | Gray | #868e96 |
| Highlight / focus | Yellow | #f08c00 |

## Layout Patterns

- **Top-to-bottom**: Process flows, decision trees, timelines
- **Left-to-right**: Comparisons, before/after, pipelines
- **Radial / center-out**: Concept maps, mind maps
- **Grid**: Feature matrices, comparison tables

## Element Guidelines

### Text
- Use short labels (2-4 words per element)
- Title font size: 20-24px
- Label font size: 14-16px
- Add detail in sub-labels, not element titles

### Shapes
- **Rectangles**: Processes, components, entities
- **Diamonds**: Decision points
- **Ellipses**: Start/end points, concepts
- **Rectangles with rounded corners**: Groups, categories

### Arrows
- **Solid arrows**: Direct relationships, data flow
- **Dashed arrows**: Optional paths, indirect relationships
- Label arrows to clarify the relationship

### Spacing
- 40px minimum between elements
- 80px between groups
- Consistent spacing within a group

## Diagram Types for Research

### Comparison Diagram
```
[Option A]  [Option B]  [Option C]
   |            |            |
[Pros]      [Pros]      [Pros]
[Cons]      [Cons]      [Cons]
   |            |            |
   └──── [Verdict] ─────────┘
```

### Architecture Diagram
```
┌─────────────────────────────┐
│        [System Name]         │
│  ┌──────┐  ┌──────┐        │
│  │Comp A│──│Comp B│        │
│  └──────┘  └──┬───┘        │
│               │              │
│          ┌────▼────┐        │
│          │ Comp C  │        │
│          └─────────┘        │
└─────────────────────────────┘
```

### Timeline
```
[2020]──[2021]──[2022]──[2023]──[2024]──[2025]
  │       │       │       │       │       │
 Event   Event   Event   Event   Event   Event
```

## Tips

- Always call `describe_scene` after creating elements to verify layout
- Use `batch_create_elements` for efficiency (multiple elements at once)
- Group related elements before aligning for cleaner organization
- Do NOT export or share links — the live embedded canvas auto-syncs for the user
- NEVER use `create_from_mermaid` — it produces invisible results. Always use `batch_create_elements` with element JSON instead
