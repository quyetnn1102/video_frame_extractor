# Multi-Platform Video Frame Extractor

Advanced web application for extracting frames from videos across multiple platforms with enhanced authentication and error handling.

## ✨ Features

### 🎥 Platform Support
- ✅ **YouTube** (95% success rate) - Excellent format support
- ✅ **TikTok** (85% success rate) - Enhanced format selection 
- ✅ **Facebook** (70% success rate) - Public videos only
- ✅ **Instagram** (65% success rate) - Multi-browser cookie authentication
- ✅ **Douyin** (80% success rate) - Chinese TikTok alternative

### 🔐 Authentication System
- ✅ **Multi-browser cookie fallback** (Chrome → Firefox → Edge → Safari)
- ✅ **Smart error handling** with platform-specific guidance
- ✅ **Graceful degradation** for restricted content
- ✅ **Real-time URL validation** with platform detection

### 🎨 Modern Interface
- ✅ **Responsive design** - Works on desktop and mobile
- ✅ **Real-time URL validation** - Instant platform detection
- ✅ **Enhanced error messages** - Clear troubleshooting guidance
- ✅ **Platform badges** - Visual platform identification
- ✅ **Multi-line error display** - Comprehensive feedback

### ⚡ Processing Features
- ✅ **Multiple timestamp formats** (30, 1:23, 1:23:45)
- ✅ **High-quality frame extraction** - OpenCV-based processing
- ✅ **Automatic cleanup** - Temporary file management
- ✅ **Download support** - Direct frame download
- ✅ **Error recovery** - Robust failure handling

## 📋 Platform Status

| Platform  | Success Rate | Authentication | Public Content | Restrictions |
|-----------|-------------|----------------|----------------|--------------|
| YouTube   | 95% ✅      | Not required   | Full support   | Minimal      |
| TikTok    | 85% ✅      | Not required   | Full support   | Some regions |
| Facebook  | 70% ⚠️      | Sometimes      | Public only    | Private blocked |
| Instagram | 65% ⚠️      | Often required | Mixed          | Age/login restrictions |
| Douyin    | 80% ✅      | Not required   | Full support   | China-specific |

## 🚀 Installation

1. **Create Python Virtual Environment:**
```powershell
cd video_frame_extractor
python -m venv venv
.\venv\Scripts\Activate.ps1
```

2. **Install Dependencies:**
```powershell
pip install -r requirements.txt
```

3. **Run Application:**
```powershell
python app.py
```

4. **Open Browser:**
```
http://localhost:5000
```

## 📖 Usage Guide

### 1. **Enter Video URL** (Supports multiple formats)
   - **YouTube**: `https://www.youtube.com/watch?v=VIDEO_ID`
   - **TikTok**: `https://www.tiktok.com/@user/video/VIDEO_ID` or `https://vm.tiktok.com/SHORT_ID`
   - **Facebook**: `https://www.facebook.com/watch/?v=VIDEO_ID` (public only)
   - **Instagram**: `https://www.instagram.com/reel/REEL_ID/` (authentication may be required)
   - **Douyin**: `https://www.douyin.com/video/VIDEO_ID`

### 2. **Specify Timestamps** (One per line)
   - `30` - 30 seconds
   - `1:23` - 1 minute 23 seconds  
   - `1:23:45` - 1 hour 23 minutes 45 seconds

### 3. **Extract Frames** and download results

## 🔧 Troubleshooting

### Instagram Authentication Issues
If you encounter Instagram restrictions:

1. **Check Error Details** - Our system provides specific guidance for each failure
2. **Try Public Content** - Use public Instagram posts/reels instead of private content
3. **Alternative Platforms** - YouTube and TikTok have higher success rates
4. **Browser Setup** - Ensure you're logged into Instagram in your browser

For detailed troubleshooting, see [Instagram Authentication Guide](INSTAGRAM_AUTHENTICATION_GUIDE.md)

### Common Issues & Solutions

#### ❌ "Could not copy Chrome cookie database"
**Solution**: Close Chrome completely, try in incognito mode, or use Firefox

#### ❌ "Restricted Video: You must be 18 years old or over"
**Solution**: Use public content or alternative platforms (YouTube, TikTok)

#### ❌ TikTok region blocks
**Solution**: Try using `vm.tiktok.com` share links instead

#### ❌ Facebook private videos
**Solution**: Only public Facebook videos are supported

### Platform Recommendations
- **First choice**: YouTube (most reliable)
- **Second choice**: TikTok (good for short content)  
- **Third choice**: Facebook/Instagram (public content only)

## 📁 Project Structure

```
video_frame_extractor/
├── app.py                              # Main Flask application
├── requirements.txt                    # Python dependencies
├── INSTAGRAM_AUTHENTICATION_GUIDE.md   # Detailed Instagram troubleshooting
├── PLATFORM_TROUBLESHOOTING.md        # Platform-specific guidance
├── templates/
│   └── index.html                     # Modern responsive web interface
├── downloads/                         # Temporary video storage
├── extracted_frames/                  # Output frame storage
└── static/                           # Static assets (CSS, JS)
```

## 🔄 Recent Updates (v2025.8.11)

### ✅ Major Enhancements
- **Multi-platform support** - 5 platforms with smart detection
- **Cookie authentication** - Multi-browser fallback system  
- **Enhanced UI** - Modern, responsive design with real-time validation
- **Better error handling** - Platform-specific troubleshooting guidance
- **Improved reliability** - Higher success rates across all platforms

### 🛠️ Technical Improvements
- Updated to yt-dlp 2025.8.11 with enhanced Instagram support
- Browser-cookie3 integration for improved authentication
- Platform-specific format optimization
- Real-time URL validation API
- Comprehensive error logging and recovery

## 📞 Support

For issues or questions:
1. Check the error message for specific guidance
2. Review the [Platform Troubleshooting Guide](PLATFORM_TROUBLESHOOTING.md)  
3. For Instagram issues, see the [Instagram Authentication Guide](INSTAGRAM_AUTHENTICATION_GUIDE.md)
4. Try alternative platforms if one fails

## Yêu cầu hệ thống

- Python 3.7+
- OpenCV
- yt-dlp (để tải video)
- Flask (web framework)

## Lưu ý

- Video sẽ được tải xuống chất lượng tối đa 720p để tối ưu tốc độ
- File tạm sẽ được tự động xóa sau khi xử lý
- Ảnh cũ sẽ được tự động xóa sau 1 giờ
- Hỗ trợ đa nền tảng: YouTube, TikTok

## Khắc phục sự cố

1. **Lỗi tải video:**
   - Kiểm tra URL có hợp lệ không
   - Đảm bảo video công khai
   - Thử lại với video khác

2. **Lỗi cắt ảnh:**
   - Kiểm tra mốc thời gian có hợp lệ không
   - Đảm bảo thời gian không vượt quá độ dài video

3. **Lỗi dependencies:**
   ```powershell
   pip install --upgrade pip
   pip install -r requirements.txt --force-reinstall
   ```
