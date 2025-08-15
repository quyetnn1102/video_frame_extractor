"""
Configuration management for Video Frame Extractor
Centralizes all configuration settings with environment-based overrides
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class Config:
    """Base configuration class"""
    
    # Base directories
    BASE_DIR = Path(__file__).parent
    DOWNLOAD_FOLDER = BASE_DIR / 'downloads'
    FRAMES_FOLDER = BASE_DIR / 'extracted_frames'
    SHORTS_FOLDER = BASE_DIR / 'generated_shorts'
    LOGS_FOLDER = BASE_DIR / 'logs'
    
    # Flask configuration
    FLASK_ENV = os.getenv('FLASK_ENV', 'development')
    DEBUG = FLASK_ENV == 'development'
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-key-change-in-production')
    MAX_CONTENT_LENGTH = 100 * 1024 * 1024  # 100MB max upload
    
    # API Configuration
    YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY', '')
    YOUTUBE_API_SERVICE_NAME = 'youtube'
    YOUTUBE_API_VERSION = 'v3'
    
    # Rate limiting
    RATE_LIMIT_PER_MINUTE = int(os.getenv('RATE_LIMIT_PER_MINUTE', '30'))
    
    # Platform configuration
    SUPPORTED_PLATFORMS = [
        'youtube.com', 'youtu.be',
        'tiktok.com', 'vm.tiktok.com',
        'facebook.com', 'fb.com', 'm.facebook.com', 'www.facebook.com',
        'douyin.com', 'v.douyin.com',
        'instagram.com', 'www.instagram.com'
    ]
    
    # Video processing settings
    DEFAULT_VIDEO_QUALITY = '720'
    MAX_VIDEO_DURATION = int(os.getenv('MAX_VIDEO_DURATION', '3600'))  # 1 hour
    FRAME_EXTRACTION_TIMEOUT = int(os.getenv('FRAME_EXTRACTION_TIMEOUT', '300'))  # 5 minutes
    
    # Cookie settings
    COOKIE_BROWSERS = ['chrome', 'firefox', 'edge', 'safari']
    COOKIE_FILE_PATH = BASE_DIR / 'instagram_cookies.txt'
    
    # Cleanup settings
    AUTO_CLEANUP_HOURS = int(os.getenv('AUTO_CLEANUP_HOURS', '24'))
    MAX_STORAGE_MB = int(os.getenv('MAX_STORAGE_MB', '1024'))  # 1GB
    
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
    DEBUG = True
    FLASK_ENV = 'development'

class ProductionConfig(Config):
    """Production configuration"""
    DEBUG = False
    FLASK_ENV = 'production'
    SECRET_KEY = os.getenv('SECRET_KEY')  # Must be set in production
    
    # Enhanced security settings
    RATE_LIMIT_PER_MINUTE = 10
    MAX_VIDEO_DURATION = 1800  # 30 minutes
    AUTO_CLEANUP_HOURS = 4
    
    @classmethod
    def validate_production_config(cls):
        """Validate required production settings"""
        required_vars = ['SECRET_KEY']
        missing = [var for var in required_vars if not os.getenv(var)]
        if missing:
            raise ValueError(f"Missing required environment variables: {missing}")

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
    'default': DevelopmentConfig
}

def get_config() -> Config:
    """Get configuration based on environment"""
    env = os.getenv('FLASK_ENV', 'development')
    config_class = config.get(env, config['default'])
    
    if env == 'production':
        config_class.validate_production_config()
    
    config_class.ensure_directories()
    return config_class
