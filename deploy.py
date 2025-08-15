"""
Production deployment script for Video Frame Extractor
Handles production setup, configuration validation, and deployment
"""
import os
import sys
import subprocess
from pathlib import Path

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
        result = subprocess.run([sys.executable, "test_enhanced.py"], 
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
    systemd_service = """[Unit]
Description=Video Frame Extractor
After=network.target

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/path/to/video_frame_extractor
Environment=PATH=/path/to/video_frame_extractor/venv/bin
Environment=FLASK_ENV=production
EnvironmentFile=/path/to/video_frame_extractor/.env
ExecStart=/path/to/video_frame_extractor/venv/bin/gunicorn -w 4 -b 127.0.0.1:8000 app_enhanced:create_app()
Restart=always

[Install]
WantedBy=multi-user.target
"""
    
    # Create nginx configuration
    nginx_config = """server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /static {
        alias /path/to/video_frame_extractor/static;
        expires 1y;
        add_header Cache-Control "public, immutable";
    }

    client_max_body_size 100M;
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
    print("\nTo start the application:")
    print("   gunicorn -w 4 -b 0.0.0.0:8000 app_enhanced:create_app()")
    print("\nTo access the dashboard:")
    print("   http://your-domain.com/dashboard")

if __name__ == "__main__":
    main()
