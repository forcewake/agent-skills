"""Generate one docs page per skill from skills/<name>/SKILL.md.

Strips YAML frontmatter and emits skills/<name>/index.md so that
relative links to co-located references/ keep working. Reference
files are passed through unchanged (Markdown becomes pages, other
files are copied as static assets).
"""

from pathlib import Path

import mkdocs_gen_files

for skill_md in sorted(Path("skills").glob("*/SKILL.md")):
    skill_dir = skill_md.parent
    text = skill_md.read_text()

    if text.startswith("---"):
        body = text.split("---", 2)[2].lstrip("\n")
    else:
        body = text

    page = f"{skill_dir}/index.md"
    with mkdocs_gen_files.open(page, "w") as f:
        f.write(body)
    mkdocs_gen_files.set_edit_path(page, skill_md)

    for ref in sorted((skill_dir / "references").glob("*")):
        with mkdocs_gen_files.open(str(ref), "wb") as f:
            f.write(ref.read_bytes())
        if ref.suffix == ".md":
            mkdocs_gen_files.set_edit_path(str(ref), ref)
