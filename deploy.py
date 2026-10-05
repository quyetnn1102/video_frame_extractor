"""
Production deployment script for Video Frame Extractor
Handles production setup, configuration validation, and deployment
"""
import os
import sys
import subprocess
from pathlib import Path

MIN_SECRET_KEY_LENGTH = 32
# One worker with threads: the sign-in state for YouTube and the rate-limit
# counters live in process memory, so several workers would not share them.
GUNICORN_COMMAND = (
    "gunicorn --workers 1 --threads 4 --timeout 900 "
    "--bind 127.0.0.1:8000 'app_enhanced:create_app()'"
)

def check_python_version():
    """Check if Python version is compatible"""
    if sys.version_info < (3, 8):
        print("❌ Python 3.8 or higher is required")
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

def setup_directories():
    """Create required directories"""
    print("📁 Setting up directories...")
    directories = [
        "downloads",
        "extracted_frames", 
        "generated_shorts",
        "logs"
    ]
    
    for directory in directories:
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
        'AUTO_CLEANUP_HOURS': 'Cleanup interval (default: 4)'
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
        print("\nPlease set these variables before deploying:")
        for var in missing_required:
            print(f"   export {var}=your_value_here")
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
    
    # Check for FFmpeg
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        print("✅ FFmpeg is available")
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("⚠️  FFmpeg not found - some video processing features may not work")
        print("   Install FFmpeg: https://ffmpeg.org/download.html")

def create_production_config():
    """Create production configuration files"""
    print("⚙️  Creating production configuration...")
    
    # Create systemd service file (Linux)
    # .env must be readable only by the service user (chmod 600). The app has no
    # login, so keep it behind an authenticating proxy or VPN, never open to the internet.
    systemd_service = f"""[Unit]
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

    # Create nginx configuration (TLS certificate paths must be filled in)
    nginx_config = """server {
    listen 80;
    server_name your-domain.com;
    return 301 https://$host$request_uri;
}

limit_req_zone $binary_remote_addr zone=video_app:10m rate=30r/m;

server {
    listen 443 ssl;
    server_name your-domain.com;

    ssl_certificate     /path/to/fullchain.pem;
    ssl_certificate_key /path/to/privkey.pem;

    # Only enable this behind authentication (basic auth, SSO proxy or VPN)
    # auth_basic "Video Frame Extractor";
    # auth_basic_user_file /path/to/.htpasswd;

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
    
    # Write configuration files
    with open("production_configs/video-frame-extractor.service", "w") as f:
        f.write(systemd_service)
    
    with open("production_configs/nginx.conf", "w") as f:
        f.write(nginx_config)
    
    print("✅ Configuration files created in production_configs/")
    print("   - Customize paths in video-frame-extractor.service")
    print("   - Customize domain in nginx.conf")

def main():
    """Main deployment function"""
    print("🚀 Video Frame Extractor - Production Deployment")
    print("=" * 50)
    
    # Create production configs directory
    Path("production_configs").mkdir(exist_ok=True)
    
    # Run all checks and setup
    check_python_version()
    setup_directories()
    install_dependencies()
    validate_environment()
    check_external_dependencies()
    run_tests()
    create_production_config()
    
    print("\n🎉 Production deployment preparation complete!")
    print("\nNext steps:")
    print("1. Review and customize configuration files in production_configs/")
    print("2. Set up your web server (nginx) with the provided config")
    print("3. Set up systemd service (Linux) or process manager")
    print("4. Configure SSL certificate")
    print("5. Set up monitoring and log rotation")
    print("\nTo start the application (Linux; gunicorn does not run on Windows):")
    print(f"   {GUNICORN_COMMAND}")
    print("\nTo access the dashboard:")
    print("   http://your-domain.com/dashboard")

if __name__ == "__main__":
    main()
