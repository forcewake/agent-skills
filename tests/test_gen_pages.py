import io
import os
from pathlib import Path
import runpy
import signal
import sys
from tempfile import TemporaryDirectory
import types
import unittest
from contextlib import contextmanager
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


class GenerateSkillPagesTests(unittest.TestCase):
    def make_skill(self, root, name="example", skill_text="---\nname: example\n---\n# Example\n"):
        skill_dir = root / "skills" / name
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(skill_text, encoding="utf-8")
        return skill_dir

    def assert_rejected_without_output(self, root, offending_path):
        with self.assertRaisesRegex(ValueError, str(offending_path)):
            run_generator(root)
        try:
            fake, _ = run_generator(root)
        except ValueError:
            return
        self.fail(f"expected {offending_path} to be rejected; wrote {fake.writes}")

    @contextmanager
    def bounded_timeout(self, seconds):
        if not hasattr(signal, "setitimer"):
            yield
            return

        def fail_on_timeout(_signum, _frame):
            self.fail(f"generator did not finish within {seconds} seconds")

        previous_handler = signal.getsignal(signal.SIGALRM)
        signal.signal(signal.SIGALRM, fail_on_timeout)
        signal.setitimer(signal.ITIMER_REAL, seconds)
        try:
            yield
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous_handler)

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
            with self.bounded_timeout(2):
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

    def test_rejects_resource_when_helper_resolution_escapes_skill_root(self):
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            skill_dir = self.make_skill(root)
            source = skill_dir / "references" / "guide.md"
            source.parent.mkdir()
            source.write_text("# Guide\n", encoding="utf-8")
            _, generated = run_generator(root)
            original_resolve = Path.resolve
            outside = root / "outside.md"

            def resolve_with_outside_source(path, *args, **kwargs):
                if path == source:
                    return outside
                return original_resolve(path, *args, **kwargs)

            with patch.object(Path, "resolve", resolve_with_outside_source):
                with self.assertRaisesRegex(ValueError, str(source)):
                    list(generated["iter_validated_resource_files"](skill_dir))

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


if __name__ == "__main__":
    unittest.main()
