"""
Production deployment helper for Video Frame Extractor (Linux).
Checks the environment, runs the tests and writes example systemd and nginx files.

The app has no login of its own. Never expose it directly: the generated nginx
config requires HTTP basic authentication in front of every request.
"""
import os
import sys
import subprocess
from pathlib import Path

MIN_PYTHON = (3, 10)
MIN_SECRET_KEY_LENGTH = 32
# One worker with threads: the sign-in state for YouTube and the rate-limit
# counters live in process memory, so several workers would not share them.
GUNICORN_COMMAND = (
    "gunicorn --workers 1 --threads 4 --timeout 900 "
    "--bind 127.0.0.1:8000 'app_enhanced:create_app()'"
)


def make_output_safe(*streams):
    """
    Never crash on a character the output encoding cannot represent. Redirected output on
    Windows uses the legacy code page (cp1252), which has no emoji; unencodable characters
    are printed as '?' instead of raising UnicodeEncodeError.
    """
    for stream in streams or (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(errors='replace')


def check_python_version():
    """Check if Python version is compatible"""
    if sys.version_info < MIN_PYTHON:
        print(f"❌ Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or higher is required")
        sys.exit(1)
    print(f"✅ Python {sys.version_info.major}.{sys.version_info.minor} is compatible")


def install_dependencies():
    """Install production dependencies"""
    print("📦 Installing dependencies...")
    try:
        subprocess.run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"],
                       check=True, capture_output=True, text=True)
        print("✅ Dependencies installed successfully")
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to install dependencies: {e}")
        print(f"Output: {e.stdout}")
        print(f"Error: {e.stderr}")
        sys.exit(1)


def load_dotenv_file():
    """Read .env like the app does, so validate_environment sees the same settings"""
    from dotenv import load_dotenv  # installed by install_dependencies()
    load_dotenv()


def setup_directories():
    """Create required directories"""
    print("📁 Setting up directories...")
    for directory in ("downloads", "extracted_frames", "generated_shorts", "logs"):
        Path(directory).mkdir(exist_ok=True)
        print(f"   Created: {directory}/")
    print("✅ Directories setup complete")


def validate_environment():
    """Validate required environment variables"""
    print("🔍 Validating environment configuration...")

    required_vars = {
        'FLASK_ENV': 'production',
        'SECRET_KEY': None  # Must be set but we won't show the value
    }

    optional_vars = {
        'YOUTUBE_API_KEY': 'YouTube API functionality',
        'RATE_LIMIT_PER_MINUTE': 'Rate limiting (default: 10)',
        'MAX_VIDEO_DURATION': 'Video duration limit (default: 1800)',
        'AUTO_CLEANUP_HOURS': 'Cleanup interval (default: 4)',
        'ALLOWED_HOSTS': 'Host names the app answers to (set your domain)',
        'TRUSTED_PROXY_COUNT': 'Number of proxies in front of the app (set 1 behind nginx)',
    }

    missing_required = []

    for var, expected_value in required_vars.items():
        value = os.getenv(var)
        if not value:
            missing_required.append(var)
        elif expected_value and value != expected_value:
            print(f"⚠️  {var} should be set to '{expected_value}' for production")
        else:
            print(f"✅ {var} is configured")

    if missing_required:
        print(f"❌ Missing required environment variables: {', '.join(missing_required)}")
        print("\nPlease set these variables (in .env or the environment) before deploying:")
        for var in missing_required:
            print(f"   {var}=your_value_here")
        sys.exit(1)

    secret_key = os.getenv('SECRET_KEY', '')
    if len(secret_key) < MIN_SECRET_KEY_LENGTH:
        print(f"❌ SECRET_KEY must be at least {MIN_SECRET_KEY_LENGTH} characters. Generate one with:")
        print('   python -c "import secrets; print(secrets.token_hex(32))"')
        sys.exit(1)

    print("\nOptional environment variables:")
    for var, description in optional_vars.items():
        value = os.getenv(var)
        if value:
            print(f"✅ {var}: configured ({description})")
        else:
            print(f"⚪ {var}: not set ({description})")


def run_tests():
    """Run test suite"""
    print("🧪 Running test suite...")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."],
            capture_output=True, text=True)
        if result.returncode == 0:
            print("✅ All tests passed")
        else:
            print("⚠️  Some tests failed:")
            print(result.stdout)
            print(result.stderr)
            response = input("Continue deployment despite test failures? (y/N): ")
            if response.lower() != 'y':
                sys.exit(1)
    except Exception as e:
        print(f"⚠️  Could not run tests: {e}")


def check_external_dependencies():
    """Check for external dependencies"""
    print("🔧 Checking external dependencies...")
    print("✅ FFmpeg is bundled with MoviePy (imageio-ffmpeg)")

    for command, purpose in (("magick", "text overlays on shorts (ImageMagick 7)"),
                             ("convert", "text overlays on shorts (ImageMagick 6)")):
        try:
            subprocess.run([command, "-version"], capture_output=True, check=True)
            print(f"✅ ImageMagick found ({command})")
            return
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue
    print("⚠️  ImageMagick not found: shorts are created without text overlays")
    print("   Install it from https://imagemagick.org/ if you want captions")


def render_systemd_service() -> str:
    """Example systemd unit. .env must be readable only by the service user (chmod 600)."""
    return f"""[Unit]
Description=Video Frame Extractor
After=network.target

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/path/to/video_frame_extractor
Environment=PATH=/path/to/video_frame_extractor/venv/bin
Environment=FLASK_ENV=production
Environment=ALLOWED_HOSTS=your-domain.com
Environment=TRUSTED_PROXY_COUNT=1
EnvironmentFile=/path/to/video_frame_extractor/.env
ExecStart=/path/to/video_frame_extractor/venv/bin/{GUNICORN_COMMAND}
Restart=always

# Sandboxing
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/path/to/video_frame_extractor

[Install]
WantedBy=multi-user.target
"""


def render_nginx_config() -> str:
    """
    Example nginx site. The app has no login, so authentication is switched ON here:
    create the password file first (htpasswd -c /path/to/.htpasswd your-username) or
    nginx will refuse every request, which is the safe failure.
    """
    return """server {
    listen 80;
    server_name your-domain.com;
    return 301 https://$host$request_uri;
}

limit_req_zone $binary_remote_addr zone=video_app:10m rate=30r/m;

server {
    listen 443 ssl;
    server_name your-domain.com;
    server_tokens off;

    ssl_certificate     /path/to/fullchain.pem;
    ssl_certificate_key /path/to/privkey.pem;

    # The app has no login of its own: every request must authenticate here
    auth_basic "Video Frame Extractor";
    auth_basic_user_file /path/to/.htpasswd;

    location / {
        limit_req zone=video_app burst=10 nodelay;
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 900s;  # rendering a short happens inside the request
    }

    client_max_body_size 1M;  # the app accepts no uploads
}
"""


def create_production_config():
    """Create production configuration files"""
    print("⚙️  Creating production configuration...")
    config_dir = Path("production_configs")
    config_dir.mkdir(exist_ok=True)

    (config_dir / "video-frame-extractor.service").write_text(render_systemd_service(), encoding="utf-8")
    (config_dir / "nginx.conf").write_text(render_nginx_config(), encoding="utf-8")

    print("✅ Configuration files created in production_configs/")
    print("   - Customize paths in video-frame-extractor.service")
    print("   - Customize the domain, certificate and password file in nginx.conf")


def main():
    """Main deployment function"""
    make_output_safe()
    print("🚀 Video Frame Extractor - Production Deployment")
    print("=" * 50)

    check_python_version()
    setup_directories()
    install_dependencies()
    load_dotenv_file()
    validate_environment()
    check_external_dependencies()
    run_tests()
    create_production_config()

    print("\n🎉 Production deployment preparation complete!")
    print("\nNext steps:")
    print("1. Review and customize configuration files in production_configs/")
    print("2. Create the nginx password file: htpasswd -c /path/to/.htpasswd your-username")
    print("3. Set up your web server (nginx) with the provided config and a TLS certificate")
    print("4. Set up the systemd service (Linux) or another process manager")
    print("5. Set up monitoring and log rotation")
    print("\nTo start the application (Linux; gunicorn does not run on Windows):")
    print(f"   {GUNICORN_COMMAND}")


if __name__ == "__main__":
    main()
