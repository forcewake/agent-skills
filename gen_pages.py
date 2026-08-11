"""Generate documentation pages for packaged skills and their resources."""

from pathlib import Path
import stat

import mkdocs_gen_files


RESOURCE_ROOTS = ("references", "assets")
SKILLS_ROOT = Path("skills").resolve()


def reject_unsafe_path(path):
    raise ValueError(f"Unsafe skill path: {path}")


def resolved_within_skill(path, skill_root):
    resolved_path = path.resolve()
    try:
        resolved_path.relative_to(skill_root)
    except ValueError:
        reject_unsafe_path(path)
    return resolved_path


def path_kind(path, skill_root):
    if path.is_symlink():
        reject_unsafe_path(path)
    resolved_within_skill(path, skill_root)
    mode = path.lstat().st_mode
    if stat.S_ISREG(mode):
        return "file"
    if stat.S_ISDIR(mode):
        return "directory"
    reject_unsafe_path(path)


def validate_skill_tree(path, skill_root):
    if path_kind(path, skill_root) == "directory":
        for child in sorted(path.iterdir(), key=lambda item: item.name):
            validate_skill_tree(child, skill_root)


def iter_validated_resource_files(skill_dir):
    skill_root = skill_dir.resolve()
    for resource_name in RESOURCE_ROOTS:
        resource_root = skill_dir / resource_name
        if resource_root.is_symlink():
            reject_unsafe_path(resource_root)
        try:
            resource_kind = path_kind(resource_root, skill_root)
        except FileNotFoundError:
            continue
        if resource_kind != "directory":
            reject_unsafe_path(resource_root)

        def walk(directory):
            for child in sorted(directory.iterdir(), key=lambda item: item.name):
                kind = path_kind(child, skill_root)
                if kind == "directory":
                    yield from walk(child)
                else:
                    yield child

        yield from walk(resource_root)


def iter_skill_directories(skills_root):
    try:
        entries = sorted(skills_root.iterdir(), key=lambda item: item.name)
    except FileNotFoundError:
        return
    for entry in entries:
        if entry.is_symlink():
            reject_unsafe_path(entry)
        if stat.S_ISDIR(entry.lstat().st_mode):
            skill_md = entry / "SKILL.md"
            if skill_md.exists() or skill_md.is_symlink():
                yield entry


def strip_frontmatter(text):
    if text.startswith("---"):
        return text.split("---", 2)[2].lstrip("\n")
    return text


def build_skill_plan(skill_dir):
    skill_root = skill_dir.resolve()
    validate_skill_tree(skill_dir, skill_root)

    skill_md = skill_dir / "SKILL.md"
    if path_kind(skill_md, skill_root) != "file":
        reject_unsafe_path(skill_md)

    resources = list(iter_validated_resource_files(skill_dir))
    return {
        "skill_dir": skill_dir,
        "skill_md": skill_md,
        "body": strip_frontmatter(skill_md.read_text()),
        "resources": [(resource, resource.read_bytes()) for resource in resources],
    }


skill_plans = [
    build_skill_plan(skill_dir)
    for skill_dir in iter_skill_directories(SKILLS_ROOT)
]

for plan in skill_plans:
    skill_dir = plan["skill_dir"]
    skill_md = plan["skill_md"]
    skill_page_root = f"skills/{skill_dir.relative_to(SKILLS_ROOT).as_posix()}"
    page = f"{skill_page_root}/index.md"
    with mkdocs_gen_files.open(page, "w") as file:
        file.write(plan["body"])
    mkdocs_gen_files.set_edit_path(page, skill_md)

    for resource, content in plan["resources"]:
        page = f"{skill_page_root}/{resource.relative_to(skill_dir).as_posix()}"
        with mkdocs_gen_files.open(page, "wb") as file:
            file.write(content)
        if resource.suffix == ".md":
            mkdocs_gen_files.set_edit_path(page, resource)
