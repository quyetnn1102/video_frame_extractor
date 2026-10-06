"""Offline translation: which models a language needs, the safe model install, the chain."""
import hashlib
import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import requests

import translation
from config import get_config
from jobs import JobCancelled
from translation import ModelPackage, TranslationError

MODEL_FILES = ('model/model.bin', 'model/config.json', 'model/shared_vocabulary.json', 'sentencepiece.model')


def model_archive(extra=(), files=MODEL_FILES) -> bytes:
    """An .argosmodel (zip) with the given files below one top folder, plus `extra` raw names."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as package:
        for name in files:
            package.writestr(f'translate-zh_en-1_9/{name}', b'data')
        for name in extra:
            package.writestr(name, b'evil')
    return buffer.getvalue()


def fake_download(data: bytes, content_length=None, url='https://argos-net.com/v1/translate-zh_en-1_9.argosmodel'):
    response = MagicMock()
    response.url = url
    response.headers = {'Content-Length': str(len(data) if content_length is None else content_length)}
    response.iter_content.return_value = [data[:10], data[10:]]
    response.__enter__.return_value = response
    return response


class TranslationTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.models = Path(tmp.name) / 'models'
        patcher = patch.object(get_config(), 'MODELS_FOLDER', self.models)
        patcher.start()
        self.addCleanup(patcher.stop)
        # The test archive stands in for the real one: pin its hash instead
        self.archive = model_archive()
        package = ModelPackage(translation.ARGOS_MODELS[('zh', 'en')].url, hashlib.sha256(self.archive).hexdigest())
        patcher = patch.dict(translation.ARGOS_MODELS, {('zh', 'en'): package})
        patcher.start()
        self.addCleanup(patcher.stop)

    def leftovers(self):
        folder = self.models / 'argos'
        return sorted(path.name for path in folder.iterdir()) if folder.exists() else []


class TestRoute(unittest.TestCase):
    def test_chinese_goes_through_english(self):
        self.assertEqual(translation.translation_route('zh'), [('zh', 'en'), ('en', 'vi')])

    def test_english_is_translated_directly_and_vietnamese_not_at_all(self):
        self.assertEqual(translation.translation_route('en'), [('en', 'vi')])
        self.assertEqual(translation.translation_route('vi'), [])

    def test_an_unsupported_language_is_named_in_the_error(self):
        with self.assertRaises(TranslationError) as raised:
            translation.translation_route('ja')
        self.assertIn('"ja"', raised.exception.message)
        self.assertIn('Chinese', raised.exception.message)


class TestDetokenize(unittest.TestCase):
    def test_pieces_become_words_even_when_sentencepiece_would_keep_the_marks(self):
        self.assertEqual(translation.detokenize(['▁Anh', '▁không▁có', '▁tai', '▁à', '?']),
                         'Anh không có tai à?')


class TestModelInstall(TranslationTestCase):
    def test_only_the_model_files_are_unpacked_and_nothing_leaves_the_folder(self):
        archive = self.models / 'package.zip'
        archive.parent.mkdir(parents=True)
        archive.write_bytes(model_archive(extra=(
            'translate-zh_en-1_9/README.md', 'translate-zh_en-1_9/stanza/zh/tokenize.pt',
            'translate-zh_en-1_9/../evil.txt', 'translate-zh_en-1_9/model/../../evil.txt',
            'translate-zh_en-1_9/model/sub/deep.bin', '/absolute.txt')))
        destination = self.models / 'installed'

        translation.extract_model(archive, destination)

        unpacked = sorted(path.relative_to(destination).as_posix()
                          for path in destination.rglob('*') if path.is_file())
        self.assertEqual(unpacked, sorted(MODEL_FILES))
        self.assertEqual(sorted(path.name for path in self.models.iterdir()), ['installed', 'package.zip'])

    def test_an_archive_without_the_model_is_refused(self):
        archive = self.models / 'package.zip'
        archive.parent.mkdir(parents=True)
        archive.write_bytes(model_archive(files=('sentencepiece.model',)))
        with self.assertRaises(TranslationError):
            translation.extract_model(archive, self.models / 'installed')

    def test_a_model_is_downloaded_once_then_reused(self):
        with patch.object(translation.requests, 'get', return_value=fake_download(self.archive)) as get:
            folder = translation.ensure_model(('zh', 'en'))
            again = translation.ensure_model(('zh', 'en'))
        self.assertEqual(folder, again)
        self.assertEqual(get.call_count, 1)
        self.assertEqual(get.call_args.args[0], translation.ARGOS_MODELS[('zh', 'en')].url)
        self.assertTrue((folder / 'model' / 'model.bin').is_file())
        self.assertEqual(self.leftovers(), ['zh_en'], 'no download or half-unpacked folder is left')

    def test_download_progress_is_reported(self):
        reports = []
        with patch.object(translation.requests, 'get', return_value=fake_download(self.archive)):
            translation.ensure_model(('zh', 'en'), reports.append)
        self.assertEqual(reports[-1], 1)

    def test_a_network_failure_says_what_to_do_and_leaves_nothing(self):
        with patch.object(translation.requests, 'get', side_effect=requests.ConnectionError('C:\\secret')):
            with self.assertRaises(TranslationError) as raised:
                translation.ensure_model(('zh', 'en'))
        self.assertIn('internet connection', raised.exception.message)
        self.assertNotIn('secret', raised.exception.message)
        self.assertEqual(self.leftovers(), [])

    def test_an_oversized_download_is_refused(self):
        too_big = fake_download(self.archive, content_length=translation.MAX_MODEL_BYTES + 1)
        with patch.object(translation.requests, 'get', return_value=too_big):
            with self.assertRaises(TranslationError):
                translation.ensure_model(('zh', 'en'))
        self.assertEqual(self.leftovers(), [])

    def test_a_different_file_is_refused(self):
        tampered = fake_download(model_archive(extra=('translate-zh_en-1_9/model/extra.bin',)))
        with patch.object(translation.requests, 'get', return_value=tampered):
            with self.assertRaises(TranslationError) as raised:
                translation.ensure_model(('zh', 'en'))
        self.assertIn('did not match', raised.exception.message)
        self.assertEqual(self.leftovers(), [])

    def test_a_download_redirected_to_another_site_is_refused(self):
        moved = fake_download(self.archive, url='http://argos-net.com.evil.example/model')
        with patch.object(translation.requests, 'get', return_value=moved):
            with self.assertRaises(TranslationError) as raised:
                translation.ensure_model(('zh', 'en'))
        self.assertIn('redirected', raised.exception.message)
        self.assertEqual(self.leftovers(), [])

    def test_an_archive_that_unpacks_too_large_is_refused(self):
        archive = self.models / 'package.zip'
        archive.parent.mkdir(parents=True)
        archive.write_bytes(self.archive)
        with patch.object(translation, 'MAX_UNPACKED_BYTES', 10):
            with self.assertRaises(TranslationError):
                translation.extract_model(archive, self.models / 'installed')

    def test_dot_names_are_not_model_files(self):
        for name in ('model/..', 'model/.', 'model/.hidden'):
            with self.subTest(name=name):
                self.assertIsNone(translation.MODEL_FILE_PATTERN.fullmatch(name))

    def test_a_cancelled_download_stops_and_leaves_nothing(self):
        def cancel(_fraction):
            raise JobCancelled()

        with patch.object(translation.requests, 'get', return_value=fake_download(self.archive)):
            with self.assertRaises(JobCancelled):
                translation.ensure_model(('zh', 'en'), cancel)
        self.assertEqual(self.leftovers(), [])


class TestTranslateToVietnamese(TranslationTestCase):
    def test_chinese_lines_go_through_both_models_in_order(self):
        def fake_translate(lines, pair):
            return [f'{line}>{pair[1]}' for line in lines]

        with patch.object(translation, 'ensure_model') as ensure, \
                patch.object(translation, 'translate_lines', side_effect=fake_translate):
            result = translation.translate_to_vietnamese(['你好', '再见'], 'zh')
        self.assertEqual(result, ['你好>en>vi', '再见>en>vi'])
        self.assertEqual([call.args[0] for call in ensure.call_args_list], [('zh', 'en'), ('en', 'vi')])

    def test_two_downloads_fill_one_progress_bar(self):
        reports = []

        def fake_ensure(pair, on_progress):
            on_progress(0.5)
            on_progress(None)

        with patch.object(translation, 'ensure_model', side_effect=fake_ensure), \
                patch.object(translation, 'translate_lines', side_effect=lambda lines, pair: lines):
            translation.translate_to_vietnamese(['你好'], 'zh', on_download=reports.append)
        self.assertEqual(reports, [0.25, None, 0.75, None])

    def test_a_model_that_cannot_be_loaded_is_removed_to_be_fetched_again(self):
        folder = translation.model_folder(('en', 'vi'))
        (folder / 'model').mkdir(parents=True)
        with patch('sentencepiece.SentencePieceProcessor', side_effect=RuntimeError('damaged')):
            with self.assertRaises(translation.TranslationError) as raised:
                translation.translate_lines(['Hello'], ('en', 'vi'))
        self.assertIn('downloaded again', raised.exception.message)
        self.assertFalse(folder.exists())

    def test_vietnamese_speech_is_kept_as_it_is(self):
        with patch.object(translation, 'translate_lines') as translate:
            self.assertEqual(translation.translate_to_vietnamese(['Xin chào'], 'vi'), ['Xin chào'])
        translate.assert_not_called()

    def test_blank_lines_are_not_sent_to_the_model(self):
        self.assertEqual(translation.translate_lines(['', '  '], ('zh', 'en')), ['', ''])

    def test_each_sentence_is_translated_on_its_own_then_joined_per_line(self):
        tokenizer = MagicMock()
        tokenizer.encode.side_effect = lambda text, out_type: [text]
        translator = MagicMock()
        translator.translate_batch.side_effect = lambda batch, **options: [
            SimpleNamespace(hypotheses=[['▁' + tokens[0].upper()]]) for tokens in batch]
        with patch('sentencepiece.SentencePieceProcessor', return_value=tokenizer),                 patch('ctranslate2.Translator', return_value=translator):
            result = translation.translate_lines(['How are you? I am fine.', '', 'Bye'], ('en', 'vi'))
        self.assertEqual(result, ['HOW ARE YOU? I AM FINE.', '', 'BYE'])
        self.assertEqual(translator.translate_batch.call_args.args[0],
                         [['How are you?'], ['I am fine.'], ['Bye']])


class TestSplitSentences(unittest.TestCase):
    def test_sentences_end_at_western_and_chinese_punctuation(self):
        self.assertEqual(translation.split_sentences('Hello, how are you? I am fine. Ok!'),
                         ['Hello, how are you?', 'I am fine.', 'Ok!'])
        self.assertEqual(translation.split_sentences('你好吗？我很好。明天见'), ['你好吗？', '我很好。', '明天见'])

    def test_numbers_and_unpunctuated_lines_stay_whole(self):
        self.assertEqual(translation.split_sentences('It costs 3.50 today'), ['It costs 3.50 today'])
        self.assertEqual(translation.split_sentences('人不能进入我们的幸福世界'), ['人不能进入我们的幸福世界'])
        self.assertEqual(translation.split_sentences('  '), [])


if __name__ == '__main__':
    unittest.main()
