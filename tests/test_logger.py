"""Tests for logger.py: level handling and log-injection protection."""
import itertools
import logging
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import logger as logger_module
from logger import StructuredLogger, parse_log_level

_names = itertools.count()


class TestParseLogLevel(unittest.TestCase):
    def test_names_are_case_insensitive(self):
        self.assertEqual(parse_log_level('info'), logging.INFO)
        self.assertEqual(parse_log_level('Warning'), logging.WARNING)
        self.assertEqual(parse_log_level('ERROR'), logging.ERROR)
        self.assertEqual(parse_log_level(' debug '), logging.DEBUG)

    def test_invalid_values_fall_back_to_info_instead_of_crashing(self):
        for value in ['', None, 'verbose', 'getLogger', 'basicConfig', '10', 'raiseExceptions']:
            with self.subTest(value=value):
                self.assertEqual(parse_log_level(value), logging.INFO)


class TestStructuredLogger(unittest.TestCase):
    def make_logger(self, level='INFO'):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        log_file = Path(tmp.name) / 'app.log'
        config = SimpleNamespace(LOG_LEVEL=level, LOG_FILE=log_file, LOG_FORMAT='%(levelname)s %(message)s')
        with patch.object(logger_module, 'get_config', return_value=config):
            structured = StructuredLogger(f'test-logger-{next(_names)}')

        def close_handlers():
            for handler in list(structured.logger.handlers):
                handler.close()
                structured.logger.removeHandler(handler)

        self.addCleanup(close_handlers)
        return structured, log_file

    def test_the_log_file_respects_the_configured_level(self):
        structured, log_file = self.make_logger('ERROR')
        structured.debug('debug-line')
        structured.info('info-line')
        structured.warning('warning-line')
        structured.error('error-line')

        text = log_file.read_text(encoding='utf-8')
        self.assertIn('error-line', text)
        for hidden in ('debug-line', 'info-line', 'warning-line'):
            self.assertNotIn(hidden, text)

    def test_lower_case_level_names_work(self):
        structured, log_file = self.make_logger('info')
        structured.debug('debug-line')
        structured.info('info-line')
        text = log_file.read_text(encoding='utf-8')
        self.assertIn('info-line', text)
        self.assertNotIn('debug-line', text)

    def test_control_characters_cannot_forge_log_lines(self):
        structured, log_file = self.make_logger('INFO')
        structured.error('download failed\nERROR forged entry\r\x1b[31mred\x00', url='x')

        lines = log_file.read_text(encoding='utf-8').splitlines()
        self.assertEqual(len(lines), 1)
        self.assertNotIn('\x1b', lines[0])
        self.assertNotIn('\x00', lines[0])
        self.assertIn('forged entry', lines[0])

    def test_context_is_still_logged_as_json(self):
        structured, log_file = self.make_logger('INFO')
        structured.info('hello', platform='youtube', count=3)
        self.assertIn('"platform": "youtube"', log_file.read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
