# agent-skills

A curated collection of [Agent Skills](https://agentskills.io) for coding agents, packaged as an [APM](https://github.com/microsoft/apm) skill collection.

Each skill ships verified, failure-driven guidance: real symptoms mapped to exact fixes, with reference material agents can load on demand.

## Skills

| Skill | Use when |
| --- | --- |
| [mkdocs-material](skills/mkdocs-material/index.md) | Creating, fixing, or deploying MkDocs / Material for MkDocs sites: checkboxes render as literal `[ ]` text, bare URLs are not clickable, tables overflow, Mermaid shows as a code block, or GitHub Pages misbehaves |
| [asd-ste100-compliance](skills/asd-ste100-compliance/index.md) | Unofficial ASD-STE100 Issue 9 authoring/review aid; qualified review required. |

## Install

Everything:

```bash
apm install forcewake/agent-skills
```

Cherry-pick one skill (selection persists in your `apm.yml`):

```bash
apm install forcewake/agent-skills --skill mkdocs-material
```

Pin a release:

```yaml
# apm.yml
dependencies:
  apm:
  - git: forcewake/agent-skills#v1.0.0
    skills:
      - mkdocs-material
```

## Quality bar

1. Spec-compliant frontmatter ([agentskills.io](https://agentskills.io/specification)) — `name` matches the directory, ASCII-only.
2. Failure-driven content: each skill is built from real observed agent failures, not feature tours.
3. Tested before shipping: a fresh agent given only the skill files must solve the original failure scenarios.
