# agent-skills

A curated collection of [Agent Skills](https://agentskills.io) for coding agents, packaged as an [APM](https://github.com/microsoft/apm) skill collection. Each skill lives in `skills/<name>/` with its own `SKILL.md`.

**Documentation site:** https://forcewake.github.io/agent-skills/

## Skills

| Skill | Description |
| --- | --- |
| [mkdocs-material](skills/mkdocs-material/SKILL.md) | Material for MkDocs configuration, silent-rendering-failure fixes (task lists, autolinks, Mermaid, table overflow), built-HTML verification, and GitHub Pages deployment including private-repo domains and errored Pages builds |
| [asd-ste100-compliance](skills/asd-ste100-compliance/SKILL.md) | Unofficial ASD-STE100 Issue 9 authoring/review aid; qualified review required. |

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
  - repo: forcewake/agent-skills#v1.0.0
    skills:
      - mkdocs-material
```

## Adding a skill

1. Create `skills/<skill-name>/SKILL.md` with [spec-compliant](https://agentskills.io/specification) frontmatter — `name` must match the directory name; keep frontmatter ASCII-only.
2. Put heavy reference material in `skills/<skill-name>/references/`.
3. Test it: give a fresh agent only the skill files and real failure scenarios; it must retrieve the correct fixes before the skill ships.
4. Add a row to the table above and tag a release.

## License

MIT
