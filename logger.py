"""
Enhanced logging system for Video Frame Extractor
Provides structured logging with different levels and outputs
"""
import logging
import logging.handlers
from datetime import datetime
import json
import traceback
from typing import Optional
import sys

from config import get_config

class CustomFormatter(logging.Formatter):
    """Custom formatter with color coding for console output"""
    
    COLORS = {
        'DEBUG': '\033[36m',     # Cyan
        'INFO': '\033[32m',      # Green
        'WARNING': '\033[33m',   # Yellow
        'ERROR': '\033[31m',     # Red
        'CRITICAL': '\033[35m',  # Magenta
        'RESET': '\033[0m'       # Reset
    }
    
    def format(self, record):
        if hasattr(record, 'color') and record.color:
            color = self.COLORS.get(record.levelname, self.COLORS['RESET'])
            record.levelname = f"{color}{record.levelname}{self.COLORS['RESET']}"
        return super().format(record)

class StructuredLogger:
    """Enhanced logger with structured output and context management"""
    
    def __init__(self, name: str):
        self.config = get_config()
        self.logger = logging.getLogger(name)
        self.logger.setLevel(getattr(logging, self.config.LOG_LEVEL))
        
        # Prevent duplicate handlers
        if not self.logger.handlers:
            self._setup_handlers()
    
    def _setup_handlers(self):
        """Setup file and console handlers"""
        # File handler with rotation
        file_handler = logging.handlers.RotatingFileHandler(
            self.config.LOG_FILE,
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5
        )
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter(self.config.LOG_FORMAT)
        file_handler.setFormatter(file_formatter)
        
        # Console handler with colors
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(getattr(logging, self.config.LOG_LEVEL))
        console_formatter = CustomFormatter(self.config.LOG_FORMAT)
        console_handler.setFormatter(console_formatter)
        
        # Add handlers
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)
    
    def _log_with_context(self, level: int, message: str, **context):
        """Log message with additional context"""
        context_str = ""
        if context:
            context_str = f" | Context: {json.dumps(context, default=str)}"
        
        # Add color to record for console output
        record = self.logger.makeRecord(
            self.logger.name, level, __file__, 0, 
            f"{message}{context_str}", (), None
        )
        record.color = True
        self.logger.handle(record)
    
    def debug(self, message: str, **context):
        self._log_with_context(logging.DEBUG, message, **context)
    
    def info(self, message: str, **context):
        self._log_with_context(logging.INFO, message, **context)
    
    def warning(self, message: str, **context):
        self._log_with_context(logging.WARNING, message, **context)
    
    def error(self, message: str, **context):
        self._log_with_context(logging.ERROR, message, **context)
    
    def critical(self, message: str, **context):
        self._log_with_context(logging.CRITICAL, message, **context)
    
    def exception(self, message: str, **context):
        """Log exception with full traceback"""
        context['traceback'] = traceback.format_exc()
        self.error(message, **context)
    
    def log_api_request(self, method: str, endpoint: str, user_ip: str, 
                       user_agent: str, status_code: int, duration_ms: float):
        """Log API request details"""
        self.info(
            f"API Request: {method} {endpoint}",
            user_ip=user_ip,
            user_agent=user_agent,
            status_code=status_code,
            duration_ms=duration_ms
        )
    
    def log_video_processing(self, platform: str, url: str, action: str, 
                           status: str, duration_ms: Optional[float] = None, 
                           error: Optional[str] = None):
        """Log video processing events"""
        context = {
            'platform': platform,
            'url': url[:100] + '...' if len(url) > 100 else url,  # Truncate long URLs
            'action': action,
            'status': status
        }
        
        if duration_ms:
            context['duration_ms'] = duration_ms
        if error:
            context['error'] = error
        
        level = logging.ERROR if status == 'failed' else logging.INFO
        self._log_with_context(level, f"Video Processing: {action}", **context)

# Global logger instances
app_logger = StructuredLogger('app')
video_logger = StructuredLogger('video_processing')
api_logger = StructuredLogger('api')

def log_function_call(func):
    """Decorator to log function calls"""
    def wrapper(*args, **kwargs):
        start_time = datetime.now()
        try:
            result = func(*args, **kwargs)
            duration = (datetime.now() - start_time).total_seconds() * 1000
            app_logger.debug(
                f"Function call: {func.__name__}",
                duration_ms=duration,
                success=True
            )
            return result
        except Exception as e:
            duration = (datetime.now() - start_time).total_seconds() * 1000
            app_logger.error(
                f"Function call failed: {func.__name__}",
                duration_ms=duration,
                error=str(e)
            )
            raise
    return wrapper

class LogContext:
    """Context manager for logging operations"""
    
    def __init__(self, logger: StructuredLogger, operation: str, **context):
        self.logger = logger
        self.operation = operation
        self.context = context
        self.start_time = None
    
    def __enter__(self):
        self.start_time = datetime.now()
        self.logger.info(f"Starting: {self.operation}", **self.context)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        duration = (datetime.now() - self.start_time).total_seconds() * 1000
        
        if exc_type is None:
            self.logger.info(
                f"Completed: {self.operation}",
                duration_ms=duration,
                **self.context
            )
        else:
            self.logger.error(
                f"Failed: {self.operation}",
                duration_ms=duration,
                error=str(exc_val),
                **self.context
            )
        
        return False  # Don't suppress exceptions
