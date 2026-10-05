"""Tests for deploy.py: the generated production files must be safe as written."""
import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import deploy

ROOT = Path(__file__).resolve().parent.parent


def active_lines(text: str):
    """Config lines that are not comments."""
    return [line.strip() for line in text.splitlines()
            if line.strip() and not line.strip().startswith('#')]


class TestNginxConfig(unittest.TestCase):
    def setUp(self):
        self.text = deploy.render_nginx_config()
        self.lines = active_lines(self.text)

    def test_authentication_is_enabled_not_commented_out(self):
        """The app has no login: an unauthenticated proxy would expose a downloader to the internet."""
        self.assertTrue(any(line.startswith('auth_basic "') for line in self.lines))
        self.assertTrue(any(line.startswith('auth_basic_user_file ') for line in self.lines))

    def test_tls_is_required_and_plain_http_only_redirects(self):
        self.assertIn('listen 443 ssl;', self.lines)
        self.assertIn('return 301 https://$host$request_uri;', self.lines)
        first_server = self.text.split('server {')[1].split('}')[0]
        self.assertNotIn('proxy_pass', first_server)

    def test_hardening_directives_are_present(self):
        self.assertIn('server_tokens off;', self.lines)
        self.assertTrue(any(line.startswith('limit_req ') for line in self.lines))
        self.assertTrue(any(line.startswith('client_max_body_size 1M') for line in self.lines))

    def test_the_proxy_sets_only_the_forwarded_headers_the_app_trusts(self):
        self.assertIn('proxy_set_header X-Forwarded-For $remote_addr;', self.lines)  # not appended
        self.assertTrue(any('proxy_read_timeout' in line for line in self.lines))


class TestSystemdUnit(unittest.TestCase):
    def setUp(self):
        self.text = deploy.render_systemd_service()

    def test_runs_one_worker_with_threads_on_loopback(self):
        self.assertIn(deploy.GUNICORN_COMMAND, self.text)
        self.assertIn('--workers 1', self.text)
        self.assertIn('--bind 127.0.0.1:8000', self.text)

    def test_is_sandboxed(self):
        for directive in ['NoNewPrivileges=true', 'PrivateTmp=true', 'ProtectSystem=strict',
                          'ProtectHome=true', 'ReadWritePaths=']:
            with self.subTest(directive=directive):
                self.assertIn(directive, self.text)

    def test_tells_the_app_it_sits_behind_one_proxy(self):
        self.assertIn('Environment=TRUSTED_PROXY_COUNT=1', self.text)
        self.assertIn('Environment=ALLOWED_HOSTS=', self.text)
        self.assertIn('Environment=FLASK_ENV=production', self.text)


class TestOutputEncoding(unittest.TestCase):
    def test_redirected_output_with_a_legacy_code_page_does_not_crash(self):
        legacy = io.TextIOWrapper(io.BytesIO(), encoding='cp1252')
        with self.assertRaises(UnicodeEncodeError):
            print('🔍 checking', file=legacy, flush=True)  # the failure being guarded against

        legacy = io.TextIOWrapper(io.BytesIO(), encoding='cp1252')
        deploy.make_output_safe(legacy)
        print('🔍 checking ✅', file=legacy, flush=True)
        self.assertIn(b'checking', legacy.buffer.getvalue())

    def test_streams_that_cannot_be_reconfigured_are_left_alone(self):
        deploy.make_output_safe(io.StringIO(), object())  # does not raise


class QuietTestCase(unittest.TestCase):
    """deploy.py prints emoji progress messages; keep them out of the test output."""

    def setUp(self):
        redirect = contextlib.redirect_stdout(io.StringIO())
        redirect.__enter__()
        self.addCleanup(redirect.__exit__, None, None, None)


class TestChecks(QuietTestCase):
    def test_the_python_floor_matches_the_documentation(self):
        readme = (ROOT / 'README.md').read_text(encoding='utf-8')
        self.assertIn(f'Python {deploy.MIN_PYTHON[0]}.{deploy.MIN_PYTHON[1]}', readme)

    def test_short_secret_keys_are_refused(self):
        for secret in ['short', 'x' * (deploy.MIN_SECRET_KEY_LENGTH - 1)]:
            with self.subTest(length=len(secret)):
                with patch.dict(os.environ, {'FLASK_ENV': 'production', 'SECRET_KEY': secret}):
                    with self.assertRaises(SystemExit):
                        deploy.validate_environment()

    def test_a_long_secret_key_is_accepted(self):
        with patch.dict(os.environ, {'FLASK_ENV': 'production',
                                     'SECRET_KEY': 'x' * deploy.MIN_SECRET_KEY_LENGTH}):
            deploy.validate_environment()  # does not exit

    def test_missing_settings_are_refused(self):
        with patch.dict(os.environ, {'FLASK_ENV': '', 'SECRET_KEY': ''}):
            with self.assertRaises(SystemExit):
                deploy.validate_environment()


class TestUvInstall(QuietTestCase):
    def test_production_install_uses_the_lock_without_dev_tools(self):
        self.assertEqual(deploy.INSTALL_COMMAND, 'uv sync --frozen --no-dev')
        self.assertIn('--frozen', deploy.DEPLOY_COMMAND)
        self.assertIn('--no-dev', deploy.DEPLOY_COMMAND)

    def test_the_service_runs_gunicorn_from_the_uv_environment(self):
        text = deploy.render_systemd_service()
        self.assertIn(f'ExecStart={deploy.VENV_BIN}/gunicorn', text)
        self.assertIn(f'Environment=PATH={deploy.VENV_BIN}', text)
        self.assertTrue(deploy.VENV_BIN.endswith('/.venv/bin'))

    def test_missing_dependencies_stop_with_the_uv_command(self):
        output = io.StringIO()
        with patch.dict('sys.modules', {'dotenv': None}), contextlib.redirect_stdout(output):
            with self.assertRaises(SystemExit):
                deploy.require_project_environment()
        self.assertIn(deploy.DEPLOY_COMMAND, output.getvalue())

    def test_nothing_is_installed_into_the_running_python(self):
        with patch('subprocess.run') as run:
            deploy.require_project_environment()
        run.assert_not_called()

    def test_the_readme_documents_the_commands_deploy_prints(self):
        readme = (ROOT / 'README.md').read_text(encoding='utf-8')
        self.assertIn(deploy.INSTALL_COMMAND, readme)
        self.assertIn(deploy.DEPLOY_COMMAND, readme)


class TestWritingFiles(QuietTestCase):
    def test_both_files_are_written(self):
        previous = os.getcwd()
        with tempfile.TemporaryDirectory() as folder:
            os.chdir(folder)
            try:
                deploy.create_production_config()
                written = sorted(path.name for path in Path('production_configs').iterdir())
            finally:
                os.chdir(previous)
        self.assertEqual(written, ['nginx.conf', 'video-frame-extractor.service'])


if __name__ == '__main__':
    unittest.main()
