---
name: planning
description: Use when a user request requires a multi-step solution, architectural changes, or complex implementation. Establishes a roadmap before any code is modified.
---

## Objective

Provide a clear, technical roadmap and architectural overview for a requested feature or fix without prematurely modifying the codebase.

## Workflow

1. **Analyze**: Break down the user's request into technical requirements.
2. **Audit**: Identify all files, classes, and dependencies that will be impacted.
3. **Architect**: Propose the structural changes (new classes, service updates, configuration changes).
4. **Sequence**: List the order of operations for the "Building Phase".
5. **Review**: Present the plan to the user for approval.

## Constraints

- **No File Mutations**: Do not use `write_file` or `replace_text` on existing source code during this phase.
- **No Implementation**: Do not write the actual logic; focus on signatures, paths, and logic flow.
- **Drafting Only**: New files can only be proposed or created as temporary markdown docs if requested.

## Output Format

The plan should be delivered as a structured Markdown response with sections for:
- Summary of Changes
- Impacted Components
- Step-by-Step Execution Plan
- Potential Risks
