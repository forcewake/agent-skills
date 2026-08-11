import json
from pathlib import Path
import re
import unittest

from yaml import BaseLoader, safe_load, load


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = REPOSITORY_ROOT / 'skills' / 'asd-ste100-compliance'
PACKAGE_FILES = (
    Path('SKILL.md'),
    Path('references/official-sources.md'),
    Path('assets/terminology-record.example.json'),
)


def read_frontmatter(text):
    match = re.match(r'\A---\r?\n(.*?)\r?\n---\r?\n', text, re.DOTALL)
    if match is None:
        raise AssertionError('frontmatter must have opening and closing --- delimiters')
    metadata = safe_load(match.group(1))
    if not isinstance(metadata, dict):
        raise AssertionError('frontmatter body must be a YAML mapping')
    return metadata


def assert_relative_package_links(test_case, source_file, text):
    for _, destination in re.findall(r'\[([^\]]+)\]\(([^)]+)\)', text):
        destination = destination.strip()
        if re.fullmatch(r'https?://[^\s]+', destination) or destination.startswith('mailto:') or destination.startswith('#'):
            continue
        test_case.assertFalse(destination.startswith(('/', '\\')), destination)
        test_case.assertIsNone(re.match(r'^[A-Za-z]:[\\/]', destination), destination)
        local_destination = destination.split('#', 1)[0]
        test_case.assertTrue(local_destination, destination)
        test_case.assertNotIn('..', re.split(r'[\\/]+', local_destination), destination)
        candidate = source_file.parent / local_destination
        test_case.assertFalse(candidate.is_symlink(), destination)
        test_case.assertTrue(candidate.exists(), destination)
        test_case.assertTrue(candidate.is_file(), destination)
        try:
            candidate.resolve().relative_to(SKILL_ROOT.resolve())
        except ValueError as error:
            raise AssertionError(f'link escapes package: {destination}') from error


def _flatten_nav(node):
    if isinstance(node, dict):
        for value in node.values():
            yield from _flatten_nav(value)
    elif isinstance(node, list):
        for value in node:
            yield from _flatten_nav(value)
    else:
        yield node


class AsdSte100SkillPackageTests(unittest.TestCase):
    def new_skill_text(self):
        return '\n'.join((SKILL_ROOT / relative_path).read_text(encoding='utf-8') for relative_path in PACKAGE_FILES)

    def test_required_skill_directory_and_public_files_exist(self):
        self.assertTrue(SKILL_ROOT.is_dir(), SKILL_ROOT)
        for relative_path in PACKAGE_FILES:
            self.assertTrue((SKILL_ROOT / relative_path).is_file(), relative_path)

    def test_frontmatter_is_exact_and_required(self):
        metadata = read_frontmatter((SKILL_ROOT / 'SKILL.md').read_text(encoding='utf-8'))
        self.assertEqual(set(metadata), {'name', 'description', 'license'})
        self.assertEqual(metadata['name'], 'asd-ste100-compliance')
        self.assertTrue(metadata['description'].startswith(
            'Use when drafting, revising, or reviewing English technical documentation'
        ))
        self.assertEqual(metadata['license'], 'MIT')

    def test_package_tree_is_exactly_three_public_files(self):
        self.assertTrue(SKILL_ROOT.is_dir(), SKILL_ROOT)
        package_paths = list(SKILL_ROOT.rglob('*'))
        self.assertTrue(all(not path.is_symlink() for path in package_paths), 'package must not contain symlinks')
        actual_files = {path.relative_to(SKILL_ROOT) for path in package_paths if path.is_file()}
        self.assertEqual(actual_files, set(PACKAGE_FILES))
        actual_directories = {path.relative_to(SKILL_ROOT) for path in package_paths if path.is_dir()}
        self.assertEqual(actual_directories, {Path('references'), Path('assets')})
        prohibited_names = {
            'apm.yml', '.apm', 'requirements.txt', 'requirements-dev.txt', 'poetry.lock',
            'uv.lock', 'Pipfile', 'Pipfile.lock', 'package-lock.json', 'yarn.lock',
            'pnpm-lock.yaml', 'manifest.json', 'checker.py', 'check.py', 'target',
        }
        self.assertFalse({path.name for path in package_paths} & prohibited_names)

    def test_terminology_example_is_valid_synthetic_project_owned_json(self):
        payload = json.loads((SKILL_ROOT / 'assets' / 'terminology-record.example.json').read_text(encoding='utf-8'))
        self.assertEqual(set(payload), {'terms'})
        self.assertIsInstance(payload['terms'], list)
        self.assertEqual(len(payload['terms']), 2)
        self.assertEqual({entry['term_type'] for entry in payload['terms']}, {'noun', 'verb'})
        self.assertEqual({entry['term'] for entry in payload['terms']}, {'zunel', 'ravex'})
        for entry in payload['terms']:
            self.assertEqual(set(entry), {'term', 'term_type', 'definition', 'status', 'approval', 'version'})
            self.assertIsInstance(entry['definition'], str)
            self.assertIn('synthetic generic', entry['definition'].lower())
            self.assertIn('project-owned', entry['status'].lower())
            self.assertIn('pending', entry['status'].lower())
            self.assertIn('no external approval', entry['approval'].lower())
            self.assertTrue(entry['version'])

    def test_skill_links_are_exact_and_all_package_links_are_safe(self):
        skill_path = SKILL_ROOT / 'SKILL.md'
        skill_text = skill_path.read_text(encoding='utf-8')
        self.assertEqual(
            re.findall(r'\[([^\]]+)\]\(([^)]+)\)', skill_text),
            [
                ('official ASD/STEMG sources', 'references/official-sources.md'),
                ('project terminology-record example', 'assets/terminology-record.example.json'),
            ],
        )
        assert_relative_package_links(self, skill_path, skill_text)
        sources_path = SKILL_ROOT / 'references' / 'official-sources.md'
        assert_relative_package_links(self, sources_path, sources_path.read_text(encoding='utf-8'))

    def test_sources_are_official_current_on_access_and_cover_safe_authoring_boundaries(self):
        sources_text = (SKILL_ROOT / 'references' / 'official-sources.md').read_text(encoding='utf-8')
        expected_urls = {
            'https://www.asd-ste100.org/assets/files/ASD-STE100_ISSUE9.pdf',
            'https://www.asd-ste100.org/STE_faq.html',
            'https://www.asd-ste100.org/software.html',
            'https://www.asd-ste100.org/assets/files/WhitePaper-ASD-STE100_and_AI.pdf',
        }
        actual_urls = set(re.findall(r'https://[^\s)>]+', sources_text))
        self.assertEqual(actual_urls, expected_urls)
        self.assertEqual(len(re.findall(r'Accessed: 2026-08-11', sources_text)), 4)
        self.assertNotRegex(sources_text, r'(?m)^\s*https?://')
        self.assertIn('Issue 9 was current on the access date; reconfirm before use.', sources_text)
        self.assertIn('external-only', sources_text.lower())
        self.assertIn('does not redistribute', sources_text.lower())
        for phrase in ('PDF', 'controlled dictionary', 'checklist', 'logos', 'protected material'):
            self.assertIn(phrase.lower(), sources_text.lower())
        lower_sources = sources_text.lower()
        for phrase in (
            'preserve facts', 'values', 'units', 'identifiers', 'commands', 'warnings',
            'sequence', 'actors', 'scope', 'uncertainty', 'procedure', 'description', 'safety',
            'project-owned terminology', 'official consultation', 'technical sme authorization',
            'qualified ste reviewer', 'technical sme release gates',
        ):
            self.assertIn(phrase, lower_sources)

    def test_skill_declares_unofficial_safe_boundary_and_release_gates(self):
        skill_text = (SKILL_ROOT / 'SKILL.md').read_text(encoding='utf-8')
        lower_skill = skill_text.lower()
        for phrase in (
            'independent', 'unofficial', 'no endorsement', 'non-certification',
            'preserve source literals and technical semantics', 'sme fact-change authority',
            'source-incomplete', 'escalation', 'consequence', 'risk', 'prevention', 'authority',
            'do not invent', 'do not guess', 'do not downgrade', 'do not silently omit',
            'project-owned terminology', 'official consultation', 'technical sme authorization',
            'qualified ste reviewer', 'technical sme release gates',
        ):
            self.assertIn(phrase, lower_skill)
        expected_statuses = [
            'Drafted with this unofficial authoring and review aid; qualified technical SME and STE review pending.',
            'Reviewed with this unofficial authoring and review aid; technical SME review pending.',
            'Source information incomplete—escalated to the technical owner; do not release.',
            'Qualified technical SME and STE review recorded; release decision remains with the responsible authority.',
            'Not assessed against ASD-STE100.',
        ]
        status_section = re.search(r'## Usable status statements\n(.*?)(?=\n## |\Z)', skill_text, re.DOTALL)
        if status_section is None:
            self.fail('missing usable status statements section')
        self.assertEqual(re.findall(r'(?m)^- (.+)$', status_section.group(1)), expected_statuses)
        for phrase in (
            'identified reviewers', 'review date', 'source revision/scope', 'evidence location/reference',
            'authority identity', 'decision/reference', 'scope/revision date',
            'named qualified ste reviewer', 'sme full-review evidence',
            'cannot make evidence', 'cannot decide',
        ):
            self.assertIn(phrase, lower_skill)
        for phrase in ('certification', 'asd/stemg approval', 'endorsement', 'official approval', 'full compliance', 'guaranteed compliance'):
            self.assertIn(phrase, lower_skill)
        for forbidden_claim in ('is certified', 'certified by', 'asd/stemg-approved', 'officially approved', 'guarantees compliance'):
            self.assertNotIn(forbidden_claim, lower_skill)

    def test_new_package_text_has_no_private_material_or_hidden_controls(self):
        text = self.new_skill_text()
        lower_text = text.lower()
        for forbidden in (
            '/home/', '/users/', '\\users\\', 'epam', 'hermes', 'skillopt', 'agpl',
            'copied issue9', 'copied issue 9', 'rule id', 'rule-id', 'rule_ids',
        ):
            self.assertNotIn(forbidden, lower_text)
        self.assertNotRegex(text, r'(?i)(password|api[_ -]?key|secret|token)\s*[:=]')
        self.assertNotRegex(text, r'[\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff]')
        self.assertNotIn('ASD/STEMG certification', text)

    def test_repository_catalog_and_docs_navigation_expose_the_skill(self):
        description = 'Unofficial ASD-STE100 Issue 9 authoring/review aid; qualified review required.'
        catalogues = (
            (REPOSITORY_ROOT / 'README.md', 'skills/asd-ste100-compliance/SKILL.md'),
            (REPOSITORY_ROOT / 'docs' / 'index.md', 'skills/asd-ste100-compliance/index.md'),
        )
        for catalogue_path, destination in catalogues:
            expected_row = f'| [asd-ste100-compliance]({destination}) | {description} |'
            rows = re.findall(rf'(?m)^{re.escape(expected_row)}$', catalogue_path.read_text(encoding='utf-8'))
            self.assertEqual(rows, [expected_row], catalogue_path)

        ignore_rules = (REPOSITORY_ROOT / '.gitignore').read_text(encoding='utf-8').splitlines()
        self.assertEqual(ignore_rules.count('.hermes/'), 1)
        self.assertFalse(any(rule.startswith('!.hermes') for rule in ignore_rules))

        config = load((REPOSITORY_ROOT / 'mkdocs.yml').read_text(encoding='utf-8'), Loader=BaseLoader)
        skills_nav = next(item['Skills'] for item in config['nav'] if 'Skills' in item)
        asd_sections = [item['asd-ste100-compliance'] for item in skills_nav if 'asd-ste100-compliance' in item]
        self.assertEqual(len(asd_sections), 1)
        asd_nav = asd_sections[0]
        self.assertEqual(asd_nav[0], 'skills/asd-ste100-compliance/index.md')
        self.assertEqual(asd_nav[1], {'Official sources': 'skills/asd-ste100-compliance/references/official-sources.md'})
        self.assertFalse(any(
            isinstance(item, str) and item.endswith('.json')
            for item in _flatten_nav(config['nav'])
        ))

    def test_docs_workflow_runs_discovery_before_unchanged_strict_deploy_flow(self):
        workflow_path = REPOSITORY_ROOT / '.github' / 'workflows' / 'docs.yml'
        workflow = load(workflow_path.read_text(encoding='utf-8'), Loader=BaseLoader)
        self.assertEqual(workflow['on'], {'push': {'branches': ['main']}})
        self.assertEqual(workflow['permissions'], {'contents': 'write'})

        steps = workflow['jobs']['deploy']['steps']
        runs = [step['run'] for step in steps if 'run' in step]
        self.assertEqual(
            runs,
            [
                'pip install -r requirements.txt',
                'python3 -m unittest discover -v',
                'mkdocs build --strict',
                'mkdocs gh-deploy --force',
            ],
        )


if __name__ == '__main__':
    unittest.main()
