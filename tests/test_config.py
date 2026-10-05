"""Tests for config.py: safe defaults and fail-closed environment handling."""
import importlib.util
import os
import unittest
from unittest.mock import patch

import config
from config import (Config, DevelopmentConfig, ProductionConfig, env_bool,
                    get_config, resolve_environment)


def load_fresh_config(env):
    """Execute config.py as a separate module so class attributes pick up `env`."""
    spec = importlib.util.spec_from_file_location('config_fresh', config.__file__)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(os.environ, env):
        spec.loader.exec_module(module)
    return module


class TestEnvBool(unittest.TestCase):
    def test_truthy_values(self):
        for value in ['1', 'true', 'TRUE', 'yes', 'On']:
            with self.subTest(value=value):
                self.assertTrue(env_bool('X', environ={'X': value}))

    def test_falsy_and_unset_values_use_default(self):
        for value in ['0', 'false', 'no', 'off', '']:
            with self.subTest(value=value):
                self.assertFalse(env_bool('X', environ={'X': value}))
        self.assertFalse(env_bool('X', environ={}))
        self.assertTrue(env_bool('X', default=True, environ={}))


class TestResolveEnvironment(unittest.TestCase):
    def test_defaults_to_development_when_unset_or_blank(self):
        self.assertEqual(resolve_environment({}), 'development')
        self.assertEqual(resolve_environment({'FLASK_ENV': ''}), 'development')

    def test_accepts_known_environments(self):
        for name in ['development', 'production', 'testing']:
            self.assertEqual(resolve_environment({'FLASK_ENV': name}), name)

    def test_unknown_environment_fails_closed(self):
        """A typo like 'prod' must not silently fall back to development."""
        for name in ['prod', 'Production ', 'staging', 'dev']:
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    resolve_environment({'FLASK_ENV': name})


class TestGetConfig(unittest.TestCase):
    def test_unknown_environment_raises(self):
        with patch.dict(os.environ, {'FLASK_ENV': 'prod'}):
            with self.assertRaises(ValueError):
                get_config()

    def test_production_requires_a_strong_secret_key(self):
        for secret in [None, '', 'short', 'dev-key-change-in-production']:
            with self.subTest(secret=secret):
                with patch.dict(os.environ, {'FLASK_ENV': 'production'}):
                    os.environ.pop('SECRET_KEY', None)
                    if secret is not None:
                        os.environ['SECRET_KEY'] = secret
                    with self.assertRaises(ValueError):
                        get_config()

    def test_production_accepts_a_long_random_secret_key(self):
        with patch.dict(os.environ, {'FLASK_ENV': 'production', 'SECRET_KEY': 'k' * 48}):
            self.assertEqual(get_config().FLASK_ENV, 'production')


class TestSafeDefaults(unittest.TestCase):
    def test_binds_to_loopback_by_default(self):
        self.assertEqual(load_fresh_config({'HOST': ''}).Config.HOST, '127.0.0.1')

    def test_debugger_is_opt_in(self):
        fresh = load_fresh_config({'FLASK_DEBUG': ''})
        self.assertFalse(fresh.DevelopmentConfig.DEBUG)
        self.assertFalse(fresh.ProductionConfig.DEBUG)
        self.assertTrue(load_fresh_config({'FLASK_DEBUG': '1'}).DevelopmentConfig.DEBUG)

    def test_dev_secret_key_is_random_not_a_published_constant(self):
        fresh = load_fresh_config({'SECRET_KEY': ''})
        self.assertNotEqual(fresh.Config.SECRET_KEY, 'dev-key-change-in-production')
        self.assertGreaterEqual(len(fresh.Config.SECRET_KEY), 32)
        self.assertNotEqual(fresh.Config.SECRET_KEY, load_fresh_config({'SECRET_KEY': ''}).Config.SECRET_KEY)

    def test_only_loopback_hosts_are_allowed_by_default(self):
        fresh = load_fresh_config({'ALLOWED_HOSTS': ''})
        self.assertEqual(set(fresh.Config.ALLOWED_HOSTS), {'localhost', '127.0.0.1', '[::1]'})

    def test_allowed_hosts_can_be_configured(self):
        fresh = load_fresh_config({'ALLOWED_HOSTS': 'My.Box, other.local'})
        self.assertEqual(set(fresh.Config.ALLOWED_HOSTS), {'my.box', 'other.local'})

    def test_browser_cookies_are_opt_in(self):
        self.assertFalse(load_fresh_config({'USE_BROWSER_COOKIES': ''}).Config.USE_BROWSER_COOKIES)
        self.assertTrue(load_fresh_config({'USE_BROWSER_COOKIES': 'true'}).Config.USE_BROWSER_COOKIES)

    def test_no_reverse_proxy_is_trusted_by_default(self):
        self.assertEqual(load_fresh_config({'TRUSTED_PROXY_COUNT': ''}).Config.TRUSTED_PROXY_COUNT, 0)

    def test_download_limits_are_positive(self):
        self.assertGreater(Config.MAX_DOWNLOAD_MB, 0)
        self.assertGreater(Config.SOCKET_TIMEOUT, 0)
        self.assertGreaterEqual(Config.DOWNLOAD_RETRIES, 0)

    def test_production_tunables_follow_the_environment(self):
        """Production values must not silently ignore env vars."""
        fresh = load_fresh_config({'RATE_LIMIT_PER_MINUTE': '7', 'AUTO_CLEANUP_HOURS': '2',
                                   'MAX_VIDEO_DURATION': '900'})
        self.assertEqual(fresh.ProductionConfig.RATE_LIMIT_PER_MINUTE, 7)
        self.assertEqual(fresh.ProductionConfig.AUTO_CLEANUP_HOURS, 2)
        self.assertEqual(fresh.ProductionConfig.MAX_VIDEO_DURATION, 900)


if __name__ == '__main__':
    unittest.main()
