"""The declared dependencies (pyproject.toml, uv.lock) must match what the code imports."""
import ast
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = (ROOT / 'pyproject.toml').read_text(encoding='utf-8')
LOCK = (ROOT / 'uv.lock').read_text(encoding='utf-8')

# import name -> distribution name, for every third-party module the project uses
IMPORT_TO_DIST = {
    'flask': 'flask',
    'flask_limiter': 'flask-limiter',
    'werkzeug': 'werkzeug',
    'requests': 'requests',
    'dotenv': 'python-dotenv',
    'psutil': 'psutil',
    'yt_dlp': 'yt-dlp',
    'cv2': 'opencv-python',
    'numpy': 'numpy',
    'moviepy': 'moviepy',
    'imageio_ffmpeg': 'imageio-ffmpeg',
    'googleapiclient': 'google-api-python-client',
    'google': 'google-auth',  # google.auth, google.oauth2
    'google_auth_oauthlib': 'google-auth-oauthlib',
    'httplib2': 'httplib2',
}

# Declared on purpose although never imported directly
NEEDED_WITHOUT_IMPORT = {
    'limits': "Flask-Limiter's rate-limit backend",
    'oauthlib': 'pinned: oauthlib 4.x is untested with requests-oauthlib 2.0',
    'requests-oauthlib': 'used by google-auth-oauthlib',
    'google-auth-httplib2': 'used by google-api-python-client',
    'pillow': 'used by MoviePy and OpenCV image handling',
    'gunicorn': 'production server on Linux/macOS',
    'pip-audit': 'dependency audit in CI',
}


def normalize(name):
    return re.sub(r'[-_.]+', '-', name).lower()


def toml_list(header):
    match = re.search(rf'^{re.escape(header)} = \[(.*?)^\]', PYPROJECT, re.M | re.S)
    assert match, f'{header} not found in pyproject.toml'
    return re.findall(r'^\s*"([^"]+)"', match.group(1), re.M)


def names_of(requirements):
    return {normalize(re.split(r'[=<>!~;\[ ]', line, maxsplit=1)[0]) for line in requirements}


RUNTIME = toml_list('dependencies')
DEV = toml_list('dev')


def own_python_files():
    ignored = {'.venv', 'venv', '.git', '__pycache__', 'node_modules'}
    return [path for path in ROOT.rglob('*.py')
            if not ignored.intersection(path.relative_to(ROOT).parts)]


def top_level_imports(path):
    for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name.split('.')[0]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.module.split('.')[0]


def third_party_imports(paths):
    """{module: first file that imports it} for modules that are neither stdlib nor the project's own."""
    local = {path.stem for path in ROOT.glob('*.py')} | {'tests', 'scripts'}
    found = {}
    for path in paths:
        for top in top_level_imports(path):
            if top not in sys.stdlib_module_names and top not in local:
                found.setdefault(top, path.relative_to(ROOT).as_posix())
    return found


class TestDeclaredDependencies(unittest.TestCase):
    def test_every_third_party_import_is_declared(self):
        declared = names_of(RUNTIME) | names_of(DEV)
        for module, where in sorted(third_party_imports(own_python_files()).items()):
            with self.subTest(module=module, first_seen=where):
                self.assertIn(module, IMPORT_TO_DIST,
                              f'new import {module!r} ({where}): add it to IMPORT_TO_DIST and pyproject.toml')
                self.assertIn(IMPORT_TO_DIST[module], declared,
                              f'{module!r} is imported in {where} but not declared in pyproject.toml')

    def test_app_modules_only_import_runtime_dependencies(self):
        """A production install (`uv sync --no-dev`) must be enough to run the app."""
        runtime = names_of(RUNTIME)
        app_modules = [path for path in ROOT.glob('*.py') if path.stem != 'deploy']
        for module, where in sorted(third_party_imports(app_modules).items()):
            with self.subTest(module=module, first_seen=where):
                self.assertIn(IMPORT_TO_DIST.get(module), runtime)

    def test_no_declared_dependency_is_stale(self):
        imports = third_party_imports(own_python_files())
        used = {IMPORT_TO_DIST[module] for module in imports if module in IMPORT_TO_DIST}
        unexplained = names_of(RUNTIME) - used - set(NEEDED_WITHOUT_IMPORT)
        self.assertEqual(unexplained, set(),
                         'declared but never imported: remove them, or explain them in NEEDED_WITHOUT_IMPORT')

    def test_every_allowance_is_still_declared(self):
        missing = set(NEEDED_WITHOUT_IMPORT) - names_of(RUNTIME) - names_of(DEV)
        self.assertEqual(missing, set())


class TestLockfile(unittest.TestCase):
    @staticmethod
    def locked_versions():
        return {normalize(name): version for name, version in
                re.findall(r'^\[\[package\]\]\nname = "([^"]+)"\nversion = "([^"]+)"', LOCK, re.M)}

    def test_exact_pins_match_the_lock(self):
        locked = self.locked_versions()
        pins = [line for line in RUNTIME + DEV if '==' in line]
        self.assertGreater(len(pins), 10)
        for line in pins:
            # an exact pin may carry extras: "yt-dlp[curl-cffi]==2026.8.19"
            name, version = re.match(r'([A-Za-z0-9_.\-]+)(?:\[[^\]]*\])?==([^;\s]+)', line).groups()
            with self.subTest(pin=line):
                self.assertEqual(locked.get(normalize(name)), version,
                                 f'uv.lock disagrees with {line}: run `uv lock`')

    def test_lower_bounds_are_satisfied_by_the_lock(self):
        locked = self.locked_versions()
        for line in RUNTIME:
            match = re.match(r'([A-Za-z0-9_.\-]+)>=([\d.]+)', line)
            if not match:
                continue
            name, floor = match.groups()
            with self.subTest(requirement=line):
                have = tuple(int(part) for part in locked[normalize(name)].split('.')[:3] if part.isdigit())
                want = tuple(int(part) for part in floor.split('.'))
                self.assertGreaterEqual(have, want)

    def test_the_lock_is_for_this_project(self):
        self.assertIn('name = "video-frame-extractor"', LOCK)
        self.assertRegex(LOCK, r'requires-python = ">=3\.10"')

    def test_no_local_paths_are_in_the_lock(self):
        self.assertNotIn('quyet', LOCK.lower())
        self.assertNotIn('file://', LOCK)


class TestPythonVersion(unittest.TestCase):
    @staticmethod
    def minimum():
        text = re.search(r'requires-python = ">=([\d.]+)"', PYPROJECT).group(1)
        return tuple(int(part) for part in text.split('.')[:2])

    def test_python_version_file_satisfies_requires_python(self):
        pinned = (ROOT / '.python-version').read_text(encoding='utf-8').strip()
        self.assertGreaterEqual(tuple(int(part) for part in pinned.split('.')[:2]), self.minimum())

    def test_this_interpreter_is_supported(self):
        self.assertGreaterEqual(sys.version_info[:2], self.minimum())


if __name__ == '__main__':
    unittest.main()
