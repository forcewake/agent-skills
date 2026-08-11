import io
import multiprocessing
import os
from pathlib import Path
import runpy
import sys
from tempfile import TemporaryDirectory
import types
import unittest
from unittest.mock import patch


GENERATOR = Path(__file__).resolve().parents[1] / "gen_pages.py"


class FakeMkdocsGenFiles(types.ModuleType):
    def __init__(self):
        super().__init__("mkdocs_gen_files")
        self.writes = {}
        self.write_order = []
        self.edit_paths = []

    def open(self, path, mode):
        path = str(path)
        buffer = io.BytesIO() if "b" in mode else io.StringIO()
        original_close = buffer.close

        def close():
            if not buffer.closed:
                content = buffer.getvalue()
                self.writes[path] = content if isinstance(content, bytes) else content.encode("utf-8")
                self.write_order.append(path)
            original_close()

        buffer.close = close
        return buffer

    def set_edit_path(self, page, source):
        self.edit_paths.append((str(page), Path(source)))


def run_generator(cwd, fake_mkdocs=None):
    fake_mkdocs = fake_mkdocs or FakeMkdocsGenFiles()
    previous_module = sys.modules.get("mkdocs_gen_files")
    previous_cwd = Path.cwd()
    sys.modules["mkdocs_gen_files"] = fake_mkdocs
    try:
        os.chdir(cwd)
        globals_after_run = runpy.run_path(str(GENERATOR), run_name="__main__")
    finally:
        os.chdir(previous_cwd)
        if previous_module is None:
            del sys.modules["mkdocs_gen_files"]
        else:
            sys.modules["mkdocs_gen_files"] = previous_module
    return fake_mkdocs, globals_after_run


def run_raced_generator(root_string, source_string, replacement, result_queue):
    """Run a real generator process while swapping a resource at os.open time."""
    root = Path(root_string)
    source = Path(source_string)
    external_target = root / "external-resource"
    external_target.write_bytes(b"external content")
    original_open = os.open
    replaced = False

    def open_after_replacement(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal replaced
        if not replaced and path == source.name and dir_fd is not None:
            replaced = True
            source.unlink()
            if replacement == "symlink":
                source.symlink_to(external_target)
            else:
                os.mkfifo(source)
        return original_open(path, flags, mode, dir_fd=dir_fd)

    fake = FakeMkdocsGenFiles()
    patched_dir_fd_support = frozenset(
        open_after_replacement if function is original_open else function for function in os.supports_dir_fd
    )
    try:
        with patch.object(os, "open", open_after_replacement), patch.object(os, "supports_dir_fd", patched_dir_fd_support):
            run_generator(root, fake)
    except BaseException as error:
        result_queue.put(("raised", type(error).__name__, str(error), fake.writes, replaced))
    else:
        result_queue.put(("returned", "", "", fake.writes, replaced))


class GenerateSkillPagesTests(unittest.TestCase):
    def make_skill(self, root, name="example", skill_text="---\nname: example\n---\n# Example\n"):
        skill_dir = root / "skills" / name
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(skill_text, encoding="utf-8")
        return skill_dir

    def run_raced_generator_with_timeout(self, root, source, replacement):
        context = multiprocessing.get_context("spawn")
        results = context.Queue()
        process = context.Process(
            target=run_raced_generator,
            args=(str(root), str(source), replacement, results),
        )
        process.start()
        process.join(5)
        if process.is_alive():
            process.terminate()
            process.join()
            self.fail("generator did not finish within 5 seconds")
        self.assertEqual(process.exitcode, 0)
        return results.get(timeout=1)

    def assert_missing_descriptor_capability_fails_closed(self, support_attribute, unsupported_function, capability_label):
        original_support = getattr(os, support_attribute)
        replacement_support = frozenset(function for function in original_support if function is not unsupported_function)
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "skills").mkdir()
            fake = FakeMkdocsGenFiles()

            with patch.object(os, support_attribute, replacement_support):
                with self.assertRaises(RuntimeError) as error:
                    run_generator(root, fake)

            self.assertIn(capability_label, str(error.exception))
            self.assertEqual(fake.writes, {})
            self.assertEqual(fake.write_order, [])
            self.assertEqual(fake.edit_paths, [])
        self.assertIs(getattr(os, support_attribute), original_support)

    def test_fails_closed_when_open_lacks_dir_fd_support(self):
        self.assert_missing_descriptor_capability_fails_closed("supports_dir_fd", os.open, "os.open(dir_fd)")

    def test_fails_closed_when_stat_lacks_dir_fd_support(self):
        self.assert_missing_descriptor_capability_fails_closed("supports_dir_fd", os.stat, "os.stat(dir_fd)")

    def test_fails_closed_when_stat_lacks_follow_symlinks_support(self):
        self.assert_missing_descriptor_capability_fails_closed(
            "supports_follow_symlinks", os.stat, "os.stat(follow_symlinks=False)"
        )

    def test_fails_closed_when_listdir_lacks_fd_support(self):
        self.assert_missing_descriptor_capability_fails_closed("supports_fd", os.listdir, "os.listdir(fd)")

    def test_publishes_recursive_references_and_assets_with_skill_frontmatter_removed(self):
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            skill_dir = self.make_skill(root)
            guide = skill_dir / "references" / "nested" / "guide.md"
            guide.parent.mkdir(parents=True)
            guide.write_text("# Guide\n", encoding="utf-8")
            record = skill_dir / "assets" / "templates" / "record.json"
            record.parent.mkdir(parents=True)
            record.write_bytes(b'{"record": true}\n')

            fake, _ = run_generator(root)

            self.assertEqual(
                fake.writes,
                {
                    "skills/example/index.md": b"# Example\n",
                    "skills/example/references/nested/guide.md": b"# Guide\n",
                    "skills/example/assets/templates/record.json": b'{"record": true}\n',
                },
            )
            self.assertEqual(
                fake.edit_paths,
                [
                    ("skills/example/index.md", skill_dir / "SKILL.md"),
                    ("skills/example/references/nested/guide.md", guide),
                ],
            )

    def test_accepts_skills_without_optional_resource_roots(self):
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            skill_dir = self.make_skill(root)

            fake, _ = run_generator(root)

            self.assertEqual(fake.writes, {"skills/example/index.md": b"# Example\n"})
            self.assertEqual(fake.edit_paths, [("skills/example/index.md", skill_dir / "SKILL.md")])

    def test_rejects_symlinked_skill_directory_without_output(self):
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            target = root / "target"
            target.mkdir()
            (target / "SKILL.md").write_text("# unsafe\n", encoding="utf-8")
            link = root / "skills" / "example"
            link.parent.mkdir()
            link.symlink_to(target, target_is_directory=True)

            fake = FakeMkdocsGenFiles()
            with self.assertRaisesRegex(ValueError, str(link)):
                run_generator(root, fake)
            self.assertEqual(fake.writes, {})

    def test_rejects_symlinked_skill_file_without_output(self):
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            skill_dir = self.make_skill(root)
            target = root / "outside-skill.md"
            target.write_text("# unsafe\n", encoding="utf-8")
            skill_md = skill_dir / "SKILL.md"
            skill_md.unlink()
            skill_md.symlink_to(target)

            fake = FakeMkdocsGenFiles()
            with self.assertRaisesRegex(ValueError, str(skill_md)):
                run_generator(root, fake)
            self.assertEqual(fake.writes, {})

    def test_preflights_all_skills_before_writing_when_later_skill_has_unsafe_resource(self):
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            valid_skill = self.make_skill(root, name="a-valid")
            valid_resource = valid_skill / "references" / "nested" / "guide.md"
            valid_resource.parent.mkdir(parents=True)
            valid_resource.write_text("# Guide\n", encoding="utf-8")

            invalid_skill = self.make_skill(root, name="z-invalid")
            unsafe_target = root / "outside-guide.md"
            unsafe_target.write_text("# unsafe\n", encoding="utf-8")
            unsafe_resource = invalid_skill / "references" / "unsafe-guide.md"
            unsafe_resource.parent.mkdir()
            unsafe_resource.symlink_to(unsafe_target)

            fake = FakeMkdocsGenFiles()
            with self.assertRaisesRegex(ValueError, str(unsafe_resource)):
                run_generator(root, fake)

            self.assertEqual(fake.writes, {})
            self.assertEqual(fake.write_order, [])
            self.assertEqual(fake.edit_paths, [])

    def test_rejects_symlinked_resource_roots_without_output(self):
        for resource_name in ("references", "assets"):
            with self.subTest(resource_name=resource_name), TemporaryDirectory() as temporary_directory:
                root = Path(temporary_directory)
                skill_dir = self.make_skill(root)
                target = root / "outside-resource-root"
                target.mkdir()
                (target / "unsafe.md").write_text("# unsafe\n", encoding="utf-8")
                resource_root = skill_dir / resource_name
                resource_root.symlink_to(target, target_is_directory=True)

                fake = FakeMkdocsGenFiles()
                with self.assertRaisesRegex(ValueError, str(resource_root)):
                    run_generator(root, fake)
                self.assertEqual(fake.writes, {})

    def test_rejects_nested_resource_symlink_without_output(self):
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            skill_dir = self.make_skill(root)
            resource_root = skill_dir / "references"
            resource_root.mkdir()
            target = root / "outside-guide.md"
            target.write_text("# unsafe\n", encoding="utf-8")
            link = resource_root / "nested-guide.md"
            link.symlink_to(target)

            fake = FakeMkdocsGenFiles()
            with self.assertRaisesRegex(ValueError, str(link)):
                run_generator(root, fake)
            self.assertEqual(fake.writes, {})

    def test_rejects_nonregular_fifo_resource_without_output(self):
        if not hasattr(os, "mkfifo"):
            self.skipTest("os.mkfifo is not supported on this platform")
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            skill_dir = self.make_skill(root)
            fifo = skill_dir / "references" / "stream"
            fifo.parent.mkdir()
            try:
                os.mkfifo(fifo)
            except OSError as error:
                self.skipTest(f"cannot create FIFO: {error}")

            fake = FakeMkdocsGenFiles()
            with self.assertRaisesRegex(ValueError, str(fifo)):
                run_generator(root, fake)
            self.assertEqual(fake.writes, {})

    def test_orders_resources_deterministically_and_never_reads_directories_as_bytes(self):
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            skill_dir = self.make_skill(root)
            (skill_dir / "references" / "nested").mkdir(parents=True)
            (skill_dir / "references" / "directory").mkdir()
            (skill_dir / "references" / "b.md").write_text("b", encoding="utf-8")
            (skill_dir / "references" / "a.md").write_text("a", encoding="utf-8")
            (skill_dir / "references" / "nested" / "c.md").write_text("c", encoding="utf-8")
            (skill_dir / "assets" / "templates").mkdir(parents=True)
            (skill_dir / "assets" / "z.json").write_text("z", encoding="utf-8")
            (skill_dir / "assets" / "templates" / "a.json").write_text("a", encoding="utf-8")
            original_read_bytes = Path.read_bytes

            def reject_directory_reads(path):
                if path.is_dir():
                    raise AssertionError(f"read_bytes called on directory: {path}")
                return original_read_bytes(path)

            with patch.object(Path, "read_bytes", reject_directory_reads):
                fake, _ = run_generator(root)

            self.assertEqual(
                fake.write_order,
                [
                    "skills/example/index.md",
                    "skills/example/references/a.md",
                    "skills/example/references/b.md",
                    "skills/example/references/nested/c.md",
                    "skills/example/assets/templates/a.json",
                    "skills/example/assets/z.json",
                ],
            )

    def test_rejects_symlinked_top_level_skills_root_without_output(self):
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            external_root = root / "external-skills"
            external_skill = external_root / "example"
            external_skill.mkdir(parents=True)
            (external_skill / "SKILL.md").write_text("# external\n", encoding="utf-8")
            skills_link = root / "skills"
            skills_link.symlink_to(external_root, target_is_directory=True)

            fake = FakeMkdocsGenFiles()
            with self.assertRaisesRegex(ValueError, str(skills_link)):
                run_generator(root, fake)
            self.assertEqual(fake.writes, {})

    def test_captures_utf8_skill_and_binary_resource_without_pathname_reopens(self):
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            skill_dir = self.make_skill(root, skill_text="---\nname: café\n---\n# Пример\n")
            resource = skill_dir / "assets" / "bytes.bin"
            resource.parent.mkdir()
            resource_bytes = b"\x00\xffcaf\xc3\xa9\n"
            resource.write_bytes(resource_bytes)

            with patch.object(Path, "read_text", side_effect=AssertionError("pathname read_text")), patch.object(
                Path, "read_bytes", side_effect=AssertionError("pathname read_bytes")
            ):
                fake, _ = run_generator(root)

            self.assertEqual(fake.writes["skills/example/index.md"], "# Пример\n".encode("utf-8"))
            self.assertEqual(fake.writes["skills/example/assets/bytes.bin"], resource_bytes)

    def test_rejects_resource_replaced_at_descriptor_open_boundary_without_output(self):
        replacements = ["symlink"]
        if hasattr(os, "mkfifo"):
            replacements.append("fifo")

        for replacement in replacements:
            with self.subTest(replacement=replacement), TemporaryDirectory() as temporary_directory:
                root = Path(temporary_directory)
                skill_dir = self.make_skill(root)
                source = skill_dir / "references" / "guide.md"
                source.parent.mkdir()
                source.write_text("# Guide\n", encoding="utf-8")

                status, error_type, error_message, writes, replaced = self.run_raced_generator_with_timeout(
                    root, source, replacement
                )

                self.assertTrue(replaced)
                self.assertEqual(status, "raised")
                self.assertEqual(error_type, "ValueError")
                self.assertIn(str(source), error_message)
                self.assertEqual(writes, {})


if __name__ == "__main__":
    unittest.main()
