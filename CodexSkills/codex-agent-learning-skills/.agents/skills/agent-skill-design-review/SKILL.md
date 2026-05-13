---
name: agent-skill-design-review
description: Use this skill when the user asks to create, improve, package, review, or refactor Agent Skills for Codex or other agent runtimes.
---

## Purpose

Design practical Agent Skills that codify repeatable workflows without bloating the default prompt.

## Skill structure

A skill should normally be a directory containing:

```text
skill-name/
  SKILL.md
  references/
  scripts/
  assets/
```

`SKILL.md` is required and should contain front matter:

```markdown
---
name: skill-name
description: Use this skill when ...
---
```

## Design workflow

1. Identify the repeatable workflow.
2. Define when the skill should be used.
3. Write a precise `description` as the routing rule.
4. Keep `SKILL.md` focused:
   - purpose
   - workflow
   - constraints
   - examples
   - output format
5. Move long background docs into `references/`.
6. Move repeatable validation or transformation code into `scripts/`.
7. Include safety rules.
8. Include one or two high-quality examples.
9. Avoid making one giant all-purpose skill.

## Good skill description pattern

Use:

```text
Use this skill when the user asks to [specific task types], especially involving [technologies/domains], and needs [workflow/outcome].
```

Avoid:

```text
This skill helps with coding.
```

## Review checklist

When reviewing a skill:

1. Is the `name` clear and stable?
2. Is the `description` specific enough for routing?
3. Does the skill describe a repeatable workflow rather than one-off advice?
4. Are instructions actionable?
5. Are examples realistic?
6. Are safety boundaries explicit?
7. Is the skill too broad?
8. Should large content move to references?
9. Are scripts optional and safe?
10. Is the expected output format specified?

## Output format

When generating a skill, return:

1. Directory structure
2. `SKILL.md`
3. Optional references/scripts
4. Installation notes for Codex
5. Suggested AGENTS.md usage note
