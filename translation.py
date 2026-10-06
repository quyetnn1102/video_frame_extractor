"""
Offline translation into Vietnamese with the Argos Translate models.

The models are run directly by CTranslate2 and SentencePiece: the argostranslate package would
add PyTorch, spaCy and Stanza to split paragraphs into sentences, which subtitle lines do not
need. Each model is downloaded once into MODELS_FOLDER/argos/<from>_<to>/ and kept, so later
translations need no network. Argos has no direct Chinese-Vietnamese model, so Chinese goes
through English.
"""
import hashlib
import os
import re
import shutil
import tempfile
import threading
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

import requests

from config import get_config
from logger import app_logger

TARGET_LANGUAGE = 'vi'
PIVOT_LANGUAGE = 'en'
LANGUAGE_NAMES = {'zh': 'Chinese', 'en': 'English', 'vi': 'Vietnamese'}


@dataclass(frozen=True)
class ModelPackage:
    url: str
    sha256: str  # the archive is checked against this before anything in it is used


# The URLs are versioned, so their content never changes: a different file is refused
ARGOS_MODELS = {
    ('zh', 'en'): ModelPackage('https://argos-net.com/v1/translate-zh_en-1_9.argosmodel',
                               '62e7af5a3a48b530e47b7b3e5c78c2de79073ecd815750d2bf3ab35b4a67da2d'),
    ('en', 'vi'): ModelPackage('https://argos-net.com/v1/translate-en_vi-1_9.argosmodel',
                               '86957101aa4099aa9a1a7492e41987d938d3cf0fdaf4fb684c0797a9d567dd16'),
}
DOWNLOAD_ORIGIN = 'https://argos-net.com/'  # where a download may end up after redirects

MAX_MODEL_BYTES = 300 * 1024 * 1024  # the packages are about 70 MB
MAX_UNPACKED_BYTES = 600 * 1024 * 1024  # and unpack to about 100 MB
DOWNLOAD_CHUNK_BYTES = 1024 * 1024
DOWNLOAD_TIMEOUT_SECONDS = 60
USER_AGENT = 'video-frame-extractor (offline subtitle translation)'
# The files a model needs, by their path below the package's top folder. Nothing else in the
# archive (READMEs, Stanza sentence splitters) is extracted, and no name can leave the folder.
MODEL_FILE_PATTERN = re.compile(r'model/[A-Za-z0-9_-][A-Za-z0-9_.-]*|sentencepiece\.model')
REQUIRED_FILES = ('model/model.bin', 'model/config.json', 'sentencepiece.model')
WORD_START = '▁'  # SentencePiece's mark for "a space comes before this piece"
# The models translate one sentence at a time: given two, they drop one. A sentence ends at
# . ? ! … (followed by a space) or at Chinese 。？！ (no space follows those).
SENTENCE_END = re.compile(r'(?<=[.?!…])\s+|(?<=[。？！])')
BEAM_SIZE = 4
MAX_BATCH_SIZE = 16

ProgressCallback = Callable[[Optional[float]], None]
_download_lock = threading.Lock()  # two jobs must not unpack the same model at once


class TranslationError(Exception):
    """A translation that cannot be done; the message is safe to show to the user."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def language_name(code: str) -> str:
    return LANGUAGE_NAMES.get(code, f'"{code}"')


def translation_route(source: str) -> List[Tuple[str, str]]:
    """The models that take `source` to Vietnamese, in order (none when it already is)."""
    if source == TARGET_LANGUAGE:
        return []
    if (source, TARGET_LANGUAGE) in ARGOS_MODELS:
        return [(source, TARGET_LANGUAGE)]
    if (source, PIVOT_LANGUAGE) in ARGOS_MODELS and (PIVOT_LANGUAGE, TARGET_LANGUAGE) in ARGOS_MODELS:
        return [(source, PIVOT_LANGUAGE), (PIVOT_LANGUAGE, TARGET_LANGUAGE)]
    supported = ', '.join(sorted(language_name(pair[0]) for pair in ARGOS_MODELS))
    raise TranslationError(
        f"The speech is in {language_name(source)}, which cannot be translated yet "
        f"(supported: {supported}).")


def model_folder(pair: Tuple[str, str]) -> Path:
    return get_config().MODELS_FOLDER / 'argos' / f'{pair[0]}_{pair[1]}'


def _is_installed(folder: Path) -> bool:
    return all((folder / name).is_file() for name in REQUIRED_FILES)


def _too_large() -> TranslationError:
    return TranslationError('The translation model is larger than expected, so it was not downloaded.')


def _download(package: ModelPackage, destination: Path, on_progress: Optional[ProgressCallback]) -> None:
    """Downloads a model archive; raises TranslationError unless it is exactly the expected file."""
    digest = hashlib.sha256()
    with requests.get(package.url, stream=True, timeout=DOWNLOAD_TIMEOUT_SECONDS,
                      headers={'User-Agent': USER_AGENT}) as response:
        response.raise_for_status()
        if not str(response.url or package.url).startswith(DOWNLOAD_ORIGIN):
            raise TranslationError('The translation model download was redirected elsewhere, so it was refused.')
        total = int(response.headers.get('Content-Length') or 0)
        if total > MAX_MODEL_BYTES:
            raise _too_large()
        received = 0
        with open(destination, 'wb') as file:
            for chunk in response.iter_content(DOWNLOAD_CHUNK_BYTES):
                received += len(chunk)
                if received > MAX_MODEL_BYTES:
                    raise _too_large()
                digest.update(chunk)
                file.write(chunk)
                if on_progress:
                    on_progress(received / total if total else None)
    if digest.hexdigest() != package.sha256:
        raise TranslationError('The translation model did not match the expected file, so it was not used.')


def _model_members(package: zipfile.ZipFile) -> List[Tuple[zipfile.ZipInfo, str]]:
    """(member, path below the top folder) of the files a model needs."""
    members = []
    for member in package.infolist():
        # Every file sits below one top folder, e.g. translate-zh_en-1_9/model/model.bin
        relative = member.filename.partition('/')[2]
        if not member.is_dir() and MODEL_FILE_PATTERN.fullmatch(relative):
            members.append((member, relative))
    return members


def extract_model(archive: Path, destination: Path) -> None:
    """Unpacks the files a model needs from an .argosmodel (zip) archive into `destination`."""
    destination.mkdir(parents=True)
    with zipfile.ZipFile(archive) as package:
        members = _model_members(package)
        # Reading stops at each member's declared size, so this bounds what is written
        if sum(member.file_size for member, _ in members) > MAX_UNPACKED_BYTES:
            raise _too_large()
        for member, relative in members:
            target = destination / relative
            target.parent.mkdir(exist_ok=True)
            with package.open(member) as source, open(target, 'wb') as output:
                shutil.copyfileobj(source, output)
    if not _is_installed(destination):
        raise TranslationError('The translation model download is incomplete. Try again.')


def ensure_model(pair: Tuple[str, str], on_progress: Optional[ProgressCallback] = None) -> Path:
    """The folder of an installed model, downloading it first when needed."""
    folder = model_folder(pair)
    with _download_lock:
        if _is_installed(folder):
            return folder
        folder.parent.mkdir(parents=True, exist_ok=True)
        unpacking = folder.with_name(folder.name + '.partial')
        handle, archive_name = tempfile.mkstemp(suffix='.argosmodel', dir=folder.parent)
        os.close(handle)
        archive = Path(archive_name)
        try:
            _download(ARGOS_MODELS[pair], archive, on_progress)
            shutil.rmtree(unpacking, ignore_errors=True)
            extract_model(archive, unpacking)
            shutil.rmtree(folder, ignore_errors=True)  # what a broken earlier attempt left
            os.replace(unpacking, folder)
        except (requests.RequestException, zipfile.BadZipFile, OSError) as error:
            app_logger.error(f"Translation model {pair[0]}->{pair[1]} could not be installed "
                             f"({type(error).__name__})")
            raise TranslationError('Could not download the translation model. Check the internet '
                                   'connection and try again.') from error
        finally:
            archive.unlink(missing_ok=True)
            shutil.rmtree(unpacking, ignore_errors=True)
    return folder


def detokenize(pieces: Sequence[str]) -> str:
    """
    Joins SentencePiece pieces into text. The models write pieces their SentencePiece model
    does not know, which its decoder would keep verbatim, so this is done by hand, as Argos does.
    """
    return ''.join(pieces).replace(WORD_START, ' ').strip()


def translate_lines(lines: Sequence[str], pair: Tuple[str, str]) -> List[str]:
    """
    Translates each line with an installed model; blank lines stay blank. The model is loaded
    for this call only: kept loaded, the models would hold memory between jobs.
    """
    import ctranslate2
    import sentencepiece

    # Every sentence is translated on its own, then the sentences of each line are joined again
    sentences = [split_sentences(line) for line in lines]
    flat = [sentence for line in sentences for sentence in line]
    if not flat:
        return [''] * len(lines)
    folder = model_folder(pair)
    tokenizer = sentencepiece.SentencePieceProcessor(model_file=str(folder / 'sentencepiece.model'))
    translator = ctranslate2.Translator(str(folder / 'model'), device='cpu')
    results = translator.translate_batch([tokenizer.encode(sentence, out_type=str) for sentence in flat],
                                         beam_size=BEAM_SIZE, max_batch_size=MAX_BATCH_SIZE)
    translated = iter(detokenize(result.hypotheses[0]) for result in results)
    # The targets (English, Vietnamese) put a space between sentences
    return [' '.join(next(translated) for _ in line) for line in sentences]


def split_sentences(line: str) -> List[str]:
    """The sentences of a line, punctuation kept; none for a blank line."""
    return [part.strip() for part in SENTENCE_END.split(line) if part.strip()]


def translate_to_vietnamese(lines: Sequence[str], source: str,
                            on_download: Optional[ProgressCallback] = None) -> List[str]:
    """
    Translates `lines` (in the language `source`, an ISO 639-1 code) into Vietnamese.
    Raises TranslationError when the language is not supported or a model cannot be fetched.
    """
    route = translation_route(source)
    for pair in route:
        ensure_model(pair, on_download)
    translated = list(lines)
    for pair in route:
        translated = translate_lines(translated, pair)
    return translated
