"""Generate documentation pages for packaged skills and their resources."""

import os
from pathlib import Path
import stat

import mkdocs_gen_files


RESOURCE_ROOTS = ("references", "assets")
SKILLS_ROOT = Path("skills")


def reject_unsafe_path(path):
    raise ValueError(f"Unsafe skill path: {path}")


def require_secure_descriptor_support():
    required_constants = ("O_DIRECTORY", "O_NOFOLLOW", "O_NONBLOCK")
    missing_constants = [name for name in required_constants if not hasattr(os, name)]
    required_functions = (os.stat, os.listdir)
    missing_functions = [
        function.__name__ for function in required_functions if function not in os.supports_dir_fd and function not in os.supports_fd
    ]
    if missing_constants or missing_functions:
        missing = ", ".join(missing_constants + missing_functions)
        raise RuntimeError(
            "Secure descriptor-anchored skill reads require openat-style no-follow support; unavailable: " + missing
        )


def _path_stat(path, directory_fd=None):
    try:
        if directory_fd is None:
            return Path(path).lstat()
        return os.stat(path, dir_fd=directory_fd, follow_symlinks=False)
    except OSError:
        reject_unsafe_path(path)


def open_verified_child(directory_fd, name, display_path):
    """Open a direct child without following it, and verify its identity and type."""
    before = _path_stat(name, directory_fd)
    if stat.S_ISLNK(before.st_mode):
        reject_unsafe_path(display_path)
    if stat.S_ISDIR(before.st_mode):
        expected_kind = "directory"
    elif stat.S_ISREG(before.st_mode):
        expected_kind = "file"
    else:
        reject_unsafe_path(display_path)

    flags = os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW
    if expected_kind == "directory":
        flags |= os.O_DIRECTORY
    try:
        descriptor = os.open(name, flags, dir_fd=directory_fd)
    except OSError:
        reject_unsafe_path(display_path)

    try:
        after = os.fstat(descriptor)
        if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
            reject_unsafe_path(display_path)
        if expected_kind == "directory":
            if not stat.S_ISDIR(after.st_mode):
                reject_unsafe_path(display_path)
        elif not stat.S_ISREG(after.st_mode):
            reject_unsafe_path(display_path)
        return descriptor, expected_kind
    except BaseException:
        os.close(descriptor)
        raise


def open_verified_root(skills_root, display_root):
    """Open the lexical top-level skills directory without resolving a symlink."""
    try:
        before = skills_root.lstat()
    except FileNotFoundError:
        return None
    except OSError:
        reject_unsafe_path(display_root)
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISDIR(before.st_mode):
        reject_unsafe_path(display_root)

    flags = os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_DIRECTORY
    try:
        descriptor = os.open(skills_root, flags)
    except OSError:
        reject_unsafe_path(display_root)
    try:
        after = os.fstat(descriptor)
        if not stat.S_ISDIR(after.st_mode) or (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
            reject_unsafe_path(display_root)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def read_captured_regular_file(descriptor, display_path):
    """Read bytes from a previously opened descriptor, never by pathname."""
    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
        reject_unsafe_path(display_path)
    chunks = []
    while True:
        try:
            chunk = os.read(descriptor, 64 * 1024)
        except BlockingIOError:
            reject_unsafe_path(display_path)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


def list_child_names(directory_fd, display_path):
    try:
        return sorted(os.listdir(directory_fd))
    except OSError:
        reject_unsafe_path(display_path)


def has_skill_file(skill_fd):
    try:
        return True, os.stat("SKILL.md", dir_fd=skill_fd, follow_symlinks=False)
    except FileNotFoundError:
        return False, None
    except OSError:
        reject_unsafe_path("SKILL.md")


def build_skill_plan(skills_root, skill_name, skill_fd):
    """Validate one skill tree and capture every published file from trusted FDs."""
    skill_dir = skills_root / skill_name
    captured_skill = None
    captured_resources = {resource_name: [] for resource_name in RESOURCE_ROOTS}

    def walk(directory_fd, directory_path, relative_parts):
        nonlocal captured_skill
        for name in list_child_names(directory_fd, directory_path):
            child_path = directory_path / name
            child_fd, child_kind = open_verified_child(directory_fd, name, child_path)
            child_relative_parts = relative_parts + (name,)
            try:
                if child_kind == "directory":
                    if child_relative_parts == ("SKILL.md",):
                        reject_unsafe_path(child_path)
                    walk(child_fd, child_path, child_relative_parts)
                else:
                    if len(child_relative_parts) == 1 and child_relative_parts[0] in RESOURCE_ROOTS:
                        reject_unsafe_path(child_path)
                    if child_relative_parts == ("SKILL.md",):
                        captured_skill = read_captured_regular_file(child_fd, child_path)
                    elif child_relative_parts[0] in RESOURCE_ROOTS:
                        captured_resources[child_relative_parts[0]].append(
                            (child_path, read_captured_regular_file(child_fd, child_path))
                        )
            finally:
                os.close(child_fd)

    walk(skill_fd, skill_dir, ())

    if captured_skill is None:
        reject_unsafe_path(skill_dir / "SKILL.md")
    return {
        "skill_dir": skill_dir,
        "skill_md": skill_dir / "SKILL.md",
        "body": strip_frontmatter(captured_skill.decode("utf-8")),
        "resources": [resource for resource_name in RESOURCE_ROOTS for resource in captured_resources[resource_name]],
    }


def build_all_skill_plans(skills_root):
    display_root = skills_root if skills_root.is_absolute() else Path.cwd() / skills_root
    skills_fd = open_verified_root(skills_root, display_root)
    if skills_fd is None:
        return []
    plans = []
    try:
        for skill_name in list_child_names(skills_fd, display_root):
            skill_path = display_root / skill_name
            entry_stat = _path_stat(skill_name, skills_fd)
            if stat.S_ISLNK(entry_stat.st_mode):
                reject_unsafe_path(skill_path)
            if not stat.S_ISDIR(entry_stat.st_mode):
                continue
            skill_fd, _ = open_verified_child(skills_fd, skill_name, skill_path)
            try:
                has_skill, _ = has_skill_file(skill_fd)
                if not has_skill:
                    continue
                plans.append(build_skill_plan(display_root, skill_name, skill_fd))
            finally:
                os.close(skill_fd)
    finally:
        os.close(skills_fd)
    return plans


def strip_frontmatter(text):
    if text.startswith("---"):
        return text.split("---", 2)[2].lstrip("\n")
    return text


require_secure_descriptor_support()
skill_plans = build_all_skill_plans(SKILLS_ROOT)

for plan in skill_plans:
    skill_dir = plan["skill_dir"]
    skill_md = plan["skill_md"]
    skill_page_root = f"skills/{skill_dir.relative_to(Path.cwd() / SKILLS_ROOT).as_posix()}"
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
