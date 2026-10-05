"""Keeps README.md honest: what it documents must match the code."""
import re
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import app_enhanced

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / 'README.md').read_text(encoding='utf-8')
CONFIG_SOURCE = (ROOT / 'config.py').read_text(encoding='utf-8')


def section(title: str) -> str:
    """Text of a '## title' section up to the next '## ' heading."""
    match = re.search(rf'^## {re.escape(title)}\n(.*?)(?=^## |\Z)', README, re.M | re.S)
    assert match, f'README has no "{title}" section'
    return match.group(1)


def github_slug(heading: str) -> str:
    return re.sub(r'[^\w\- ]', '', heading.lower()).replace(' ', '-')


class TestSettingsAreDocumented(unittest.TestCase):
    def documented_settings(self):
        names = set()
        for row in re.findall(r'^\|\s*((?:`[A-Z][A-Z_]+`\s*/?\s*)+)\|', section('Configuration'), re.M):
            names.update(re.findall(r'`([A-Z][A-Z_]+)`', row))
        return names

    def settings_read_by_the_code(self):
        patterns = [r"env_(?:bool|int|str|list)\(\s*'([A-Z][A-Z_]+)'",
                    r"os\.getenv\(\s*'([A-Z][A-Z_]+)'"]
        return {name for pattern in patterns for name in re.findall(pattern, CONFIG_SOURCE)}

    def test_every_documented_setting_is_read_by_the_code(self):
        unknown = self.documented_settings() - self.settings_read_by_the_code()
        self.assertEqual(unknown, set(), 'README documents settings the code ignores')

    def test_every_setting_the_code_reads_is_documented(self):
        undocumented = self.settings_read_by_the_code() - self.documented_settings()
        self.assertEqual(undocumented, set(), 'settings missing from the README configuration table')


class TestApiTableMatchesTheApp(unittest.TestCase):
    @staticmethod
    def normalize(path: str) -> str:
        return re.sub(r'<[^>]+>', '<x>', path)

    def documented_routes(self):
        routes = set()
        for row in re.findall(r'^\|(.+?)\|', section('API'), re.M):
            method = 'GET'
            for token in re.findall(r'`((?:(?:GET|POST) )?/[^`\s?]*)[^`]*`', row):
                if token.startswith(('GET ', 'POST ')):
                    method, token = token.split(' ', 1)
                routes.add((method, self.normalize(token)))
        return routes

    def app_routes(self):
        extractor = Mock()
        extractor.cleanup_old_files.return_value = (0, 0, [])
        with patch.object(app_enhanced, 'extractor', extractor), \
                patch.object(app_enhanced, 'youtube_uploader', Mock()), \
                patch.object(app_enhanced, 'db_manager', Mock()):
            app = app_enhanced.create_app()
        routes = set()
        for rule in app.url_map.iter_rules():
            if rule.endpoint == 'static':
                continue
            for method in rule.methods - {'HEAD', 'OPTIONS'}:
                routes.add((method, self.normalize(rule.rule)))
        return routes

    def test_every_documented_endpoint_exists(self):
        missing = self.documented_routes() - self.app_routes()
        self.assertEqual(missing, set(), 'README documents endpoints the app does not have')

    def test_every_endpoint_is_documented(self):
        undocumented = self.app_routes() - self.documented_routes()
        self.assertEqual(undocumented, set(), 'endpoints missing from the README API table')


class TestLinksAndFiles(unittest.TestCase):
    def test_in_page_links_point_at_real_headings(self):
        slugs = {github_slug(title) for title in re.findall(r'^#{1,6} (.+)$', README, re.M)}
        links = set(re.findall(r'\]\(#([a-z0-9-]+)\)', README))
        self.assertTrue(links, 'expected the README to contain in-page links')
        self.assertEqual(links - slugs, set(), 'README links to headings that do not exist')

    def test_files_mentioned_in_the_readme_exist(self):
        for name in ['LICENSE', 'requirements.txt', 'deploy.py', 'scripts/smoke_test.py',
                     'client_secrets.json.template', 'instagram_cookies_template.txt',
                     '.github/workflows/ci.yml']:
            with self.subTest(file=name):
                self.assertTrue((ROOT / name).is_file())
        for name in ['LICENSE', 'client_secrets.json.template', 'instagram_cookies_template.txt']:
            self.assertIn(name, README)

    def test_readme_documents_the_real_commands(self):
        for command in ['python app_enhanced.py', 'python -m unittest discover -s tests -t .',
                        'pip install -r requirements.txt', 'python -m venv .venv']:
            with self.subTest(command=command):
                self.assertIn(command, README)

    def test_secret_files_the_readme_mentions_are_git_ignored(self):
        ignored = (ROOT / '.gitignore').read_text(encoding='utf-8')
        for name in ['.env', 'client_secrets.json', 'youtube_credentials.json',
                     'instagram_cookies.txt']:
            with self.subTest(file=name):
                self.assertRegex(ignored, rf'(?m)^{re.escape(name)}\s*$')


if __name__ == '__main__':
    unittest.main()
