"""
Configuration management for Video Frame Extractor
Centralizes all configuration settings with environment-based overrides
"""
import os
import secrets
from pathlib import Path
from typing import Mapping, Optional, Tuple

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

TRUTHY_VALUES = frozenset({'1', 'true', 'yes', 'on'})
KNOWN_ENVIRONMENTS = ('development', 'production', 'testing')
MIN_PRODUCTION_SECRET_LENGTH = 32
DEV_PLACEHOLDER_SECRET = 'dev-key-change-in-production'


def env_bool(name: str, default: bool = False, environ: Optional[Mapping[str, str]] = None) -> bool:
    """Read a boolean flag from the environment ('1', 'true', 'yes', 'on')."""
    environ = os.environ if environ is None else environ
    value = (environ.get(name) or '').strip().lower()
    if not value:
        return default
    return value in TRUTHY_VALUES


def env_int(name: str, default: int) -> int:
    """Read an integer from the environment; blank or unset uses the default."""
    return int(os.getenv(name) or default)


def env_str(name: str, default: str) -> str:
    """Read a string from the environment; blank or unset uses the default."""
    return (os.getenv(name) or default).strip()


def env_list(name: str, default: str) -> Tuple[str, ...]:
    """Read a comma-separated list (lower-cased); blank or unset uses the default."""
    raw = os.getenv(name) or default
    return tuple(item.strip().lower() for item in raw.split(',') if item.strip())


def resolve_environment(environ: Optional[Mapping[str, str]] = None) -> str:
    """
    Return the configured environment name.

    Unset or blank means 'development'. An unknown value (for example the typo
    'prod') raises instead of silently falling back to development settings.
    """
    environ = os.environ if environ is None else environ
    name = environ.get('FLASK_ENV') or 'development'
    if name not in KNOWN_ENVIRONMENTS:
        raise ValueError(
            f"Unknown FLASK_ENV {name!r}. Use one of: {', '.join(KNOWN_ENVIRONMENTS)}")
    return name


class Config:
    """Base configuration class"""

    # Base directories
    BASE_DIR = Path(__file__).parent
    DOWNLOAD_FOLDER = BASE_DIR / 'downloads'
    FRAMES_FOLDER = BASE_DIR / 'extracted_frames'
    SHORTS_FOLDER = BASE_DIR / 'generated_shorts'
    LOGS_FOLDER = BASE_DIR / 'logs'

    # Flask configuration
    FLASK_ENV = env_str('FLASK_ENV', 'development')
    # The interactive Werkzeug debugger is opt-in, never implied by the environment.
    DEBUG = env_bool('FLASK_DEBUG')
    # Without SECRET_KEY, development gets a random per-process key, not a published constant.
    SECRET_KEY = os.getenv('SECRET_KEY') or secrets.token_hex(32)
    MAX_CONTENT_LENGTH = 100 * 1024 * 1024  # 100MB max request body

    # Network exposure: loopback only unless explicitly changed
    HOST = env_str('HOST', '127.0.0.1')
    PORT = env_int('PORT', 5000)
    ALLOWED_HOSTS = env_list('ALLOWED_HOSTS', 'localhost,127.0.0.1,[::1]')
    # Number of reverse proxies in front of the app (0 = none, X-Forwarded-* is ignored)
    TRUSTED_PROXY_COUNT = env_int('TRUSTED_PROXY_COUNT', 0)

    # API Configuration
    YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY', '')
    YOUTUBE_API_SERVICE_NAME = 'youtube'
    YOUTUBE_API_VERSION = 'v3'

    # YouTube upload (OAuth). Credentials are stored as JSON, never pickled.
    YOUTUBE_CLIENT_SECRETS_FILE = BASE_DIR / 'client_secrets.json'
    YOUTUBE_CREDENTIALS_FILE = BASE_DIR / 'youtube_credentials.json'
    YOUTUBE_REDIRECT_URI = env_str('YOUTUBE_REDIRECT_URI', f'http://localhost:{PORT}/oauth2callback')

    # Rate limiting
    RATE_LIMIT_PER_MINUTE = env_int('RATE_LIMIT_PER_MINUTE', 30)
    RATELIMIT_ENABLED = env_bool('RATE_LIMIT_ENABLED', True)  # Flask-Limiter switch

    # Platform configuration
    SUPPORTED_PLATFORMS = [
        'youtube.com', 'youtu.be',
        'tiktok.com', 'vm.tiktok.com',
        'facebook.com', 'fb.com', 'fb.watch', 'm.facebook.com', 'www.facebook.com',
        'douyin.com',
        'instagram.com', 'www.instagram.com'
    ]

    # Video processing settings
    DEFAULT_VIDEO_QUALITY = '720'
    MAX_VIDEO_DURATION = env_int('MAX_VIDEO_DURATION', 3600)  # 1 hour
    MAX_DOWNLOAD_MB = env_int('MAX_DOWNLOAD_MB', 500)
    SOCKET_TIMEOUT = env_int('SOCKET_TIMEOUT', 30)  # seconds
    DOWNLOAD_RETRIES = env_int('DOWNLOAD_RETRIES', 2)

    # Cookie settings. A manual cookie file is used when present; reading the
    # cookies of local browsers is opt-in because it exposes the whole profile.
    COOKIE_BROWSERS = ['chrome', 'firefox', 'edge', 'safari']
    USE_BROWSER_COOKIES = env_bool('USE_BROWSER_COOKIES')
    COOKIE_FILE_PATH = BASE_DIR / 'instagram_cookies.txt'

    # Cleanup settings
    AUTO_CLEANUP_HOURS = env_int('AUTO_CLEANUP_HOURS', 24)
    MAX_STORAGE_MB = env_int('MAX_STORAGE_MB', 1024)  # 1GB

    # Logging configuration
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    LOG_FILE = LOGS_FOLDER / 'app.log'

    @classmethod
    def ensure_directories(cls):
        """Ensure all required directories exist"""
        directories = [
            cls.DOWNLOAD_FOLDER,
            cls.FRAMES_FOLDER,
            cls.SHORTS_FOLDER,
            cls.LOGS_FOLDER
        ]
        for directory in directories:
            directory.mkdir(exist_ok=True, parents=True)

class DevelopmentConfig(Config):
    """Development configuration"""
    FLASK_ENV = 'development'

class ProductionConfig(Config):
    """Production configuration"""
    DEBUG = False
    FLASK_ENV = 'production'
    SECRET_KEY = os.getenv('SECRET_KEY')  # Must be set in production

    # Stricter defaults, still overridable through the environment
    RATE_LIMIT_PER_MINUTE = env_int('RATE_LIMIT_PER_MINUTE', 10)
    MAX_VIDEO_DURATION = env_int('MAX_VIDEO_DURATION', 1800)  # 30 minutes
    AUTO_CLEANUP_HOURS = env_int('AUTO_CLEANUP_HOURS', 4)

    @classmethod
    def validate_production_config(cls):
        """Validate required production settings"""
        secret = os.getenv('SECRET_KEY') or ''
        if not secret:
            raise ValueError("Missing required environment variables: ['SECRET_KEY']")
        if len(secret) < MIN_PRODUCTION_SECRET_LENGTH or secret == DEV_PLACEHOLDER_SECRET:
            raise ValueError(
                f"SECRET_KEY must be a random value of at least "
                f"{MIN_PRODUCTION_SECRET_LENGTH} characters")

class TestConfig(Config):
    """Testing configuration"""
    TESTING = True
    DEBUG = True
    DOWNLOAD_FOLDER = Config.BASE_DIR / 'test_downloads'
    FRAMES_FOLDER = Config.BASE_DIR / 'test_frames'
    SHORTS_FOLDER = Config.BASE_DIR / 'test_shorts'

# Configuration mapping
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestConfig,
}

def get_config() -> Config:
    """Get configuration based on environment (unknown FLASK_ENV values raise)"""
    env = resolve_environment()
    config_class = config[env]

    if env == 'production':
        config_class.validate_production_config()

    config_class.ensure_directories()
    return config_class
