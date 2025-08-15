# 🎬 VideoExtract - AI-Powered Video Processing Tool

![Python](https://img.shields.io/badge/Python-3.8%2B-blue)
![Flask](https://img.shields.io/badge/Flask-2.3%2B-green)
![YouTube API](https://img.shields.io/badge/YouTube_API-v3-red)
![License](https://img.shields.io/badge/License-MIT-yellow)

An intelligent video processing platform that extracts frames from videos and creates viral YouTube Shorts with AI-powered optimization.

## ✨ Features

### 🎯 Core Functionality
- **Frame Extraction**: Extract high-quality frames from videos with precise timing
- **Multi-Platform Support**: YouTube, TikTok, Instagram, Facebook, Douyin
- **Real-Time Processing**: Advanced algorithms for fast video processing
- **YouTube Shorts Creation**: AI-powered short video generation (15s, 30s, 60s)

### 🚀 YouTube Integration
- **Direct Upload**: Upload videos directly to your YouTube channel
- **OAuth2 Authentication**: Secure Google authentication
- **Auto-Optimization**: Automatic hashtags, descriptions, and metadata
- **Shorts Validation**: Ensures compliance with YouTube Shorts requirements

### 🎨 Modern UI
- **Social Media Inspired**: YouTube, Instagram, and TikTok styling
- **Dark Theme**: Professional dark interface with YouTube red accents
- **Responsive Design**: Mobile-first approach for all devices
- **Interactive Elements**: Smooth animations and modern card layouts

### 📊 Analytics & Monitoring
- **Real-Time Dashboard**: Track processing statistics
- **API Monitoring**: YouTube API quota management
- **Error Handling**: Comprehensive logging and error recovery
- **Performance Metrics**: Processing time and success rates

## 🚀 Quick Start

### Prerequisites
- Python 3.8+
- Google Cloud Project (for YouTube features)
- YouTube Data API v3 enabled

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/YOUR_USERNAME/video-frame-extractor.git
   cd video-frame-extractor
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up YouTube API** (Optional - for upload features)
   ```bash
   # Follow the detailed guide
   cat YOUTUBE_UPLOAD_SETUP.md
   ```

4. **Run the application**
   ```bash
   python app_enhanced.py
   ```

5. **Open your browser**
   ```
   http://localhost:5000
   ```

## 📖 Documentation

- **[YouTube Upload Setup](YOUTUBE_UPLOAD_SETUP.md)** - Complete YouTube API configuration
- **[GitHub Setup Guide](GITHUB_SETUP.md)** - Repository setup instructions
- **[Instagram Authentication](INSTAGRAM_AUTHENTICATION_GUIDE.md)** - Instagram integration
- **[Platform Troubleshooting](MANUAL_COOKIE_SETUP.md)** - Platform-specific issues

## 🛠️ Tech Stack

### Backend
- **Flask** - Web framework
- **yt-dlp** - Video downloading and processing
- **OpenCV** - Frame extraction and video analysis
- **Google APIs** - YouTube Data API v3 integration
- **OAuth2** - Secure authentication

### Frontend
- **Bootstrap 5** - UI framework
- **Font Awesome** - Icons and visual elements
- **Custom CSS** - Social media-inspired styling
- **Vanilla JavaScript** - Interactive functionality

### Data & Storage
- **SQLite** - Local database for analytics
- **File System** - Frame and video storage
- **Pickle** - Credential caching

## 📁 Project Structure

```
video-frame-extractor/
├── app_enhanced.py              # Main Flask application
├── youtube_uploader.py          # YouTube upload functionality
├── video_processor.py           # Video processing engine
├── config.py                   # Configuration management
├── database.py                 # Database operations
├── validators.py               # Input validation
├── logger.py                   # Logging system
├── analytics.py                # Analytics and monitoring
├── templates/                  # HTML templates
│   ├── index.html             # Main frame extraction page
│   ├── create_short.html      # Short video creation
│   ├── dashboard.html         # Analytics dashboard
│   └── trending.html          # Trending videos
├── requirements.txt            # Python dependencies
└── docs/                      # Documentation files
```

## 🔒 Security Features

- **OAuth2 Authentication**: Secure Google/YouTube login
- **Input Validation**: Comprehensive URL and data validation
- **Rate Limiting**: API request throttling
- **Credential Protection**: Sensitive files excluded from repository
- **Error Handling**: Graceful error recovery and logging

## 🎯 Use Cases

### Content Creators
- Extract frames for thumbnails
- Create YouTube Shorts from long videos
- Analyze video content for optimization
- Upload directly to YouTube channel

### Developers
- Video processing API
- Frame extraction automation
- YouTube API integration example
- OAuth2 implementation reference

### Businesses
- Social media content creation
- Video analysis and processing
- Automated content workflows
- Multi-platform video management

## 📊 API Endpoints

### Video Processing
- `POST /api/extract` - Extract frames from video
- `POST /api/create-short` - Create short video clips
- `POST /api/validate-url` - Validate video URLs

### YouTube Integration
- `GET /api/youtube-auth` - Authentication status
- `POST /api/upload-to-youtube` - Upload video to YouTube
- `GET /api/youtube-quota` - API quota information

### Analytics
- `GET /api/dashboard-data` - Processing statistics
- `GET /api/trending` - Trending videos data

## 🚀 Deployment

### Local Development
```bash
python app_enhanced.py
```

### Production (Gunicorn)
```bash
gunicorn -w 4 -b 0.0.0.0:5000 app_enhanced:app
```

### Docker (Coming Soon)
```bash
docker build -t videoextract .
docker run -p 5000:5000 videoextract
```

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- **yt-dlp** - Powerful video downloading library
- **Google APIs** - YouTube Data API v3
- **Bootstrap** - UI framework
- **Font Awesome** - Icon library
- **Flask** - Web framework

## 📞 Support

- **Documentation**: Check the docs/ directory
- **Issues**: Create a GitHub issue
- **Discussions**: Use GitHub discussions
- **Email**: [Your contact information]

## 🔄 Updates

### Recent Changes
- ✅ YouTube upload integration
- ✅ Modern social media UI
- ✅ Enhanced error handling
- ✅ Real-time analytics dashboard
- ✅ Multi-platform support

### Roadmap
- 🔲 Docker containerization
- 🔲 TikTok upload integration
- 🔲 Instagram direct posting
- 🔲 AI-powered content analysis
- 🔲 Batch processing capabilities

---

⭐ **Star this repository if you find it useful!**

Built with ❤️ for content creators and developers
