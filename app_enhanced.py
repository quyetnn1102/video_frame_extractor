"""
Enhanced Flask application with improved architecture, security, and monitoring
"""
from flask import Flask, request, render_template, jsonify, send_from_directory, redirect, url_for
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.middleware.proxy_fix import ProxyFix
import time
import os
from datetime import datetime
import requests
from dotenv import load_dotenv

from config import get_config
from logger import app_logger, api_logger, LogContext
from validators import validator

# Load environment variables
load_dotenv()
from video_processor import extractor
from database import get_analytics, get_recent_requests
from youtube_uploader import youtube_uploader

def get_youtube_trending(category: str = '0', region: str = 'US', max_results: int = 20) -> list:
    """
    Get real trending videos from YouTube Data API v3
    """
    try:
        # Get API key from environment
        api_key = os.getenv('YOUTUBE_API_KEY')
        if not api_key:
            app_logger.error("YouTube API key not found in environment variables")
            return get_fallback_trending_data()
        
        # YouTube Data API endpoint
        url = "https://www.googleapis.com/youtube/v3/videos"
        
        # Prepare parameters
        params = {
            'part': 'snippet,statistics,contentDetails',
            'chart': 'mostPopular',
            'regionCode': region,
            'maxResults': min(max_results, 50),  # API limit is 50
            'key': api_key
        }
        
        # Add category filter if specified (not '0' = all categories)
        if category != '0':
            params['videoCategoryId'] = category
        
        # Make API request
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        
        if 'items' not in data:
            app_logger.warning(f"No items found in YouTube API response: {data}")
            return get_fallback_trending_data()
        
        # Transform API response to our format
        videos = []
        for item in data['items']:
            try:
                snippet = item.get('snippet', {})
                statistics = item.get('statistics', {})
                content_details = item.get('contentDetails', {})
                
                # Parse duration (ISO 8601 format like PT4M13S)
                duration = parse_youtube_duration(content_details.get('duration', 'PT0S'))
                
                # Format view count
                view_count = int(statistics.get('viewCount', 0))
                
                # Calculate time ago from published date
                published_at = snippet.get('publishedAt', '')
                time_ago = calculate_time_ago(published_at)
                
                # Get category name
                category_name = get_youtube_category_name(snippet.get('categoryId', '1'))
                
                video = {
                    'id': item['id'],
                    'title': snippet.get('title', 'Untitled'),
                    'description': (snippet.get('description', '')[:200] + '...') if len(snippet.get('description', '')) > 200 else snippet.get('description', ''),
                    'thumbnail': snippet.get('thumbnails', {}).get('medium', {}).get('url', f'https://img.youtube.com/vi/{item["id"]}/mqdefault.jpg'),
                    'url': f"https://www.youtube.com/watch?v={item['id']}",
                    'channel': snippet.get('channelTitle', 'Unknown Channel'),
                    'views': str(view_count),
                    'duration': duration,
                    'published': time_ago,
                    'category': category_name
                }
                videos.append(video)
                
            except Exception as item_error:
                app_logger.error(f"Error processing video item {item.get('id', 'unknown')}: {str(item_error)}")
                continue
        
        if not videos:
            app_logger.warning("No valid videos processed from YouTube API")
            return get_fallback_trending_data()
            
        app_logger.info(f"Successfully fetched {len(videos)} trending videos from YouTube API")
        return videos
        
    except requests.exceptions.RequestException as e:
        app_logger.error(f"YouTube API request failed: {str(e)}")
        return get_fallback_trending_data()
    except Exception as e:
        app_logger.error(f"Unexpected error fetching YouTube trending: {str(e)}")
        return get_fallback_trending_data()

def get_fallback_trending_data() -> list:
    """
    Fallback sample data when YouTube API is unavailable
    """
    return [
        {
            'id': 'fallback1',
            'title': '[DEMO] Sample Trending Video',
            'description': 'This is sample data shown when YouTube API is unavailable',
            'thumbnail': 'https://img.youtube.com/vi/dQw4w9WgXcQ/mqdefault.jpg',
            'url': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
            'channel': 'Demo Channel',
            'views': '1000000',
            'duration': '3:35',
            'published': '2 hours ago',
            'category': 'Demo'
        }
    ]

def parse_youtube_duration(duration_str: str) -> str:
    """
    Parse YouTube API duration format (ISO 8601) to readable format
    Example: PT4M13S -> 4:13, PT1H2M30S -> 1:02:30
    """
    try:
        # Remove PT prefix
        duration_str = duration_str.replace('PT', '')
        
        hours = 0
        minutes = 0
        seconds = 0
        
        # Extract hours
        if 'H' in duration_str:
            hours = int(duration_str.split('H')[0])
            duration_str = duration_str.split('H')[1]
        
        # Extract minutes
        if 'M' in duration_str:
            minutes = int(duration_str.split('M')[0])
            duration_str = duration_str.split('M')[1]
        
        # Extract seconds
        if 'S' in duration_str:
            seconds = int(duration_str.split('S')[0])
        
        # Format duration
        if hours > 0:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        else:
            return f"{minutes}:{seconds:02d}"
            
    except Exception:
        return "0:00"

def calculate_time_ago(published_at: str) -> str:
    """
    Calculate human-readable time ago from ISO datetime string
    """
    try:
        # Parse the datetime (YouTube uses ISO format like 2025-01-15T10:30:00Z)
        published_dt = datetime.fromisoformat(published_at.replace('Z', '+00:00'))
        now = datetime.now(published_dt.tzinfo)
        
        diff = now - published_dt
        
        if diff.days > 365:
            years = diff.days // 365
            return f"{years} year{'s' if years != 1 else ''} ago"
        elif diff.days > 30:
            months = diff.days // 30
            return f"{months} month{'s' if months != 1 else ''} ago"
        elif diff.days > 0:
            return f"{diff.days} day{'s' if diff.days != 1 else ''} ago"
        elif diff.seconds > 3600:
            hours = diff.seconds // 3600
            return f"{hours} hour{'s' if hours != 1 else ''} ago"
        elif diff.seconds > 60:
            minutes = diff.seconds // 60
            return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
        else:
            return "Just now"
            
    except Exception:
        return "Recently"

def get_youtube_category_name(category_id: str) -> str:
    """
    Map YouTube category ID to category name
    """
    category_map = {
        '1': 'Film & Animation',
        '2': 'Autos & Vehicles', 
        '10': 'Music',
        '15': 'Pets & Animals',
        '17': 'Sports',
        '19': 'Travel & Events',
        '20': 'Gaming',
        '22': 'People & Blogs',
        '23': 'Comedy',
        '24': 'Entertainment',
        '25': 'News & Politics',
        '26': 'Howto & Style',
        '27': 'Education',
        '28': 'Science & Technology',
        '29': 'Nonprofits & Activism'
    }
    return category_map.get(category_id, 'Unknown')

def create_app(config_name: str = None) -> Flask:
    """Application factory pattern"""
    app = Flask(__name__)
    
    # Load configuration
    config = get_config()
    app.config.from_object(config)
    
    # Trust proxy headers in production
    if not config.DEBUG:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)
    
    # Setup rate limiter
    limiter = Limiter(
        key_func=get_remote_address,
        default_limits=[f"{config.RATE_LIMIT_PER_MINUTE} per minute"],
        storage_uri="memory://"
    )
    limiter.init_app(app)
    
    # Request logging middleware
    @app.before_request
    def log_request_info():
        request.start_time = time.time()
        
        # Rate limit check
        user_ip = get_remote_address()
        is_allowed, remaining = validator.check_rate_limit(user_ip)
        
        if not is_allowed:
            app_logger.warning(
                "Rate limit exceeded",
                user_ip=user_ip,
                endpoint=request.endpoint,
                user_agent=request.headers.get('User-Agent', 'Unknown')
            )
    
    @app.after_request
    def log_response_info(response):
        if hasattr(request, 'start_time'):
            duration = (time.time() - request.start_time) * 1000
            
            api_logger.log_api_request(
                method=request.method,
                endpoint=request.endpoint or request.path,
                user_ip=get_remote_address(),
                user_agent=request.headers.get('User-Agent', 'Unknown'),
                status_code=response.status_code,
                duration_ms=duration
            )
        
        # Security headers
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        
        if not config.DEBUG:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        
        return response
    
    # Error handlers
    @app.errorhandler(400)
    def bad_request(error):
        app_logger.warning("Bad request", error=str(error))
        return jsonify({'success': False, 'error': 'Bad request'}), 400
    
    @app.errorhandler(404)
    def not_found(error):
        return jsonify({'success': False, 'error': 'Endpoint not found'}), 404
    
    @app.errorhandler(429)
    def rate_limit_exceeded(error):
        app_logger.warning("Rate limit exceeded", error=str(error))
        return jsonify({
            'success': False, 
            'error': 'Rate limit exceeded. Please try again later.'
        }), 429
    
    @app.errorhandler(500)
    def internal_error(error):
        app_logger.error("Internal server error", error=str(error))
        return jsonify({
            'success': False, 
            'error': 'Internal server error'
        }), 500
    
    # Routes
    @app.route('/')
    def index():
        """Main page"""
        return render_template('index.html')
    
    @app.route('/trending')
    def trending():
        """Trending videos page"""
        return render_template('trending.html')
    
    @app.route('/create-short')
    def create_short():
        """Create short video page"""
        return render_template('create_short.html')
    
    @app.route('/api/validate-url', methods=['POST'])
    @limiter.limit("30 per minute")
    def validate_url():
        """Validate URL and detect platform"""
        with LogContext(api_logger, "URL validation"):
            try:
                data = request.get_json()
                if not data or 'url' not in data:
                    return jsonify({'success': False, 'error': 'URL is required'}), 400
                
                url = data['url']
                is_valid, platform, error = validator.validate_url(url)
                
                if not is_valid:
                    return jsonify({
                        'success': False,
                        'valid': False,
                        'error': error
                    })
                
                # Get video info for additional validation
                info_success, video_info, info_error = extractor.get_video_info(url)
                
                response_data = {
                    'success': True,
                    'valid': True,
                    'platform': platform
                }
                
                if info_success and video_info:
                    response_data.update({
                        'title': video_info.get('title', 'Unknown'),
                        'duration': video_info.get('duration'),
                        'thumbnail': video_info.get('thumbnail')
                    })
                
                return jsonify(response_data)
                
            except Exception as e:
                api_logger.exception("URL validation failed", error=str(e))
                return jsonify({
                    'success': False,
                    'error': 'Validation failed'
                }), 500
    
    @app.route('/api/extract', methods=['POST'])
    @limiter.limit("10 per minute")
    def extract_frames():
        """Extract frames from video at specified timestamps"""
        with LogContext(api_logger, "Frame extraction"):
            try:
                data = request.get_json()
                if not data:
                    return jsonify({'success': False, 'error': 'No data provided'}), 400
                
                url = data.get('url')
                timestamps = data.get('timestamps', [])
                
                # Validate inputs
                if not url:
                    return jsonify({'success': False, 'error': 'URL is required'}), 400
                
                # Validate URL
                is_valid_url, platform, url_error = validator.validate_url(url)
                if not is_valid_url:
                    return jsonify({'success': False, 'error': url_error}), 400
                
                # Validate timestamps
                is_valid_timestamps, timestamp_errors, valid_seconds = validator.validate_timestamps(timestamps)
                if not is_valid_timestamps:
                    return jsonify({
                        'success': False, 
                        'error': '; '.join(timestamp_errors)
                    }), 400
                
                app_logger.info(
                    "Starting frame extraction",
                    platform=platform,
                    timestamp_count=len(valid_seconds)
                )
                
                # Download video
                video_path, title, download_error = extractor.download_video(url)
                if not video_path:
                    return jsonify({'success': False, 'error': download_error or 'Download failed'}), 400
                
                # Extract frames
                extracted_frames = []
                errors = []
                
                for i, timestamp in enumerate(valid_seconds):
                    try:
                        # Generate unique filename
                        frame_id = f"frame_{timestamp}s_{str(uuid.uuid4())[:8]}"
                        frame_filename = f"{frame_id}.jpg"
                        frame_path = os.path.join(config.FRAMES_FOLDER, frame_filename)
                        
                        # Extract frame
                        success, frame_error = extractor.extract_frame_at_timestamp(
                            video_path, timestamp, frame_path
                        )
                        
                        if success:
                            extracted_frames.append({
                                'timestamp': timestamp,
                                'filename': frame_filename,
                                'url': f'/frames/{frame_filename}'
                            })
                        else:
                            errors.append(f"Timestamp {timestamp}s: {frame_error}")
                            
                    except Exception as e:
                        error_msg = f"Timestamp {timestamp}s: {str(e)}"
                        errors.append(error_msg)
                        app_logger.warning("Frame extraction error", 
                                         timestamp=timestamp, error=str(e))
                
                # Clean up video file
                try:
                    if os.path.exists(video_path):
                        os.remove(video_path)
                except Exception as e:
                    app_logger.warning("Could not clean up video file", 
                                     video_path=video_path, error=str(e))
                
                if not extracted_frames and errors:
                    return jsonify({
                        'success': False,
                        'error': 'Frame extraction failed: ' + '; '.join(errors)
                    }), 400
                
                response_data = {
                    'success': True,
                    'title': title,
                    'frames': extracted_frames,
                    'platform': platform
                }
                
                if errors:
                    response_data['warnings'] = errors
                
                app_logger.info(
                    "Frame extraction completed",
                    platform=platform,
                    frames_extracted=len(extracted_frames),
                    errors=len(errors)
                )
                
                return jsonify(response_data)
                
            except Exception as e:
                api_logger.exception("Frame extraction failed", error=str(e))
                return jsonify({
                    'success': False,
                    'error': 'Frame extraction failed'
                }), 500
    
    @app.route('/api/video-info', methods=['POST'])
    @limiter.limit("20 per minute")
    def get_video_info():
        """Get video information without downloading"""
        with LogContext(api_logger, "Video info request"):
            try:
                data = request.get_json()
                if not data or 'url' not in data:
                    return jsonify({'success': False, 'error': 'URL is required'}), 400
                
                url = data['url']
                
                # Validate URL
                is_valid, platform, error = validator.validate_url(url)
                if not is_valid:
                    return jsonify({'success': False, 'error': error}), 400
                
                # Get video info
                success, video_info, info_error = extractor.get_video_info(url)
                
                if not success:
                    return jsonify({'success': False, 'error': info_error}), 400
                
                return jsonify({
                    'success': True,
                    'video_info': video_info
                })
                
            except Exception as e:
                api_logger.exception("Video info request failed", error=str(e))
                return jsonify({
                    'success': False,
                    'error': 'Could not get video information'
                }), 500
    
    @app.route('/api/cleanup', methods=['POST'])
    @limiter.limit("5 per minute")
    def cleanup_files():
        """Clean up old files"""
        with LogContext(api_logger, "File cleanup"):
            try:
                files_deleted, space_freed, errors = extractor.cleanup_old_files()
                
                response_data = {
                    'success': True,
                    'files_deleted': files_deleted,
                    'space_freed_mb': space_freed,
                    'message': f'Cleaned up {files_deleted} files, freed {space_freed} MB'
                }
                
                if errors:
                    response_data['warnings'] = errors
                
                return jsonify(response_data)
                
            except Exception as e:
                api_logger.exception("File cleanup failed", error=str(e))
                return jsonify({
                    'success': False,
                    'error': 'Cleanup failed'
                }), 500
    
    @app.route('/frames/<filename>')
    def serve_frame(filename):
        """Serve extracted frame files"""
        # Validate filename to prevent directory traversal
        safe_filename = validator.sanitize_filename(filename)
        if safe_filename != filename:
            return jsonify({'error': 'Invalid filename'}), 400
        
        return send_from_directory(config.FRAMES_FOLDER, filename)
    
    @app.route('/api/health')
    def health_check():
        """Health check endpoint"""
        return jsonify({
            'status': 'healthy',
            'timestamp': datetime.now().isoformat(),
            'version': '2.0.0'
        })
    
    @app.route('/dashboard')
    def dashboard():
        """Dashboard with analytics and system information"""
        try:
            # Get analytics data
            analytics = get_analytics()
            
            # Get system information
            import psutil
            system_info = {
                'cpu_percent': psutil.cpu_percent(),
                'memory_percent': psutil.virtual_memory().percent,
                'disk_usage': psutil.disk_usage('/').percent if hasattr(psutil.disk_usage('/'), 'percent') else 0
            }
            
            # Get recent requests
            recent_requests = get_recent_requests(limit=10)
            
            return render_template('dashboard.html', 
                                 analytics=analytics,
                                 system_info=system_info,
                                 recent_requests=recent_requests)
        except Exception as e:
            app_logger.error(f"Dashboard error: {str(e)}")
            return render_template('dashboard.html', 
                                 analytics={},
                                 system_info={},
                                 recent_requests=[])
    
    @app.route('/api/dashboard-data')
    def dashboard_data():
        """API endpoint for dashboard data"""
        try:
            analytics = get_analytics()
            
            import psutil
            system_info = {
                'cpu_percent': psutil.cpu_percent(),
                'memory_percent': psutil.virtual_memory().percent,
                'disk_usage': psutil.disk_usage('/').percent if hasattr(psutil.disk_usage('/'), 'percent') else 0,
                'uptime': time.time() - psutil.boot_time() if hasattr(psutil, 'boot_time') else 0
            }
            
            recent_requests = get_recent_requests(limit=5)
            
            return jsonify({
                'analytics': analytics,
                'system_info': system_info,
                'recent_requests': recent_requests,
                'timestamp': datetime.now().isoformat()
            })
        except Exception as e:
            app_logger.error(f"Dashboard API error: {str(e)}")
            return jsonify({'error': 'Failed to fetch dashboard data'}), 500
    
    @app.route('/api/trending')
    def get_trending():
        """Get trending videos from various platforms"""
        try:
            platform = request.args.get('platform', 'youtube').lower()
            category = request.args.get('category', '0')  # 0 = all categories
            region = request.args.get('region', 'US')
            max_results = min(int(request.args.get('max_results', '20')), 50)
            
            # List of supported platforms
            supported_platforms = ['youtube']
            
            if platform not in supported_platforms:
                return jsonify({
                    'error': f'Platform "{platform}" is not supported yet',
                    'supported_platforms': supported_platforms,
                    'coming_soon': ['tiktok', 'instagram', 'facebook'],
                    'message': 'Currently only YouTube trending videos are available. More platforms coming soon!'
                }), 400
            
            if platform == 'youtube':
                trending_videos = get_youtube_trending(category, region, max_results)
            
            return jsonify({
                'platform': platform,
                'category': category,
                'region': region,
                'videos': trending_videos,
                'total': len(trending_videos),
                'timestamp': datetime.now().isoformat()
            })
            
        except Exception as e:
            app_logger.error(f"Trending API error: {str(e)}")
            return jsonify({'error': 'Failed to fetch trending videos'}), 500
    
    @app.route('/api/test-platform', methods=['POST'])
    def test_platform_compatibility():
        """Test platform compatibility and provide specific guidance"""
        try:
            data = request.get_json()
            url = data.get('url', '').strip()
            
            if not url:
                return jsonify({'error': 'URL is required'})
            
            platform = validator.get_platform_from_url(url)
            
            # Platform-specific guidance
            guidance = {
                'youtube': {
                    'status': 'excellent',
                    'reliability': '95%',
                    'notes': 'Fully supported with all features',
                    'tips': ['Copy URL from browser address bar', 'All video types supported']
                },
                'tiktok': {
                    'status': 'good',
                    'reliability': '85%',
                    'notes': 'Enhanced format support implemented',
                    'tips': ['Use vm.tiktok.com links', 'Share → Copy link from app']
                },
                'facebook': {
                    'status': 'limited',
                    'reliability': '70%',
                    'notes': 'Public videos only',
                    'tips': ['Only public videos work', 'Right-click → Copy video URL']
                },
                'instagram': {
                    'status': 'limited',
                    'reliability': '65%',
                    'notes': 'May require browser login for restricted content',
                    'tips': ['Log into Instagram in browser first', 'Use public posts/reels', 'Avoid age-restricted content']
                },
                'douyin': {
                    'status': 'good',
                    'reliability': '80%',
                    'notes': 'Chinese TikTok version',
                    'tips': ['Use official share links', 'Public videos work best']
                }
            }
            
            platform_info = guidance.get(platform, {
                'status': 'unknown',
                'reliability': '0%',
                'notes': 'Unsupported platform',
                'tips': ['Try YouTube, TikTok, Facebook, Instagram, or Douyin instead']
            })
            
            return jsonify({
                'platform': platform,
                'valid': platform in guidance,
                'info': platform_info
            })
            
        except Exception as e:
            app_logger.error(f"Platform test error: {str(e)}")
            return jsonify({'error': 'Failed to test platform compatibility'}), 500
    
    @app.route('/api/platform-status')
    def get_platform_status():
        """Get the status of supported platforms"""
        platforms = {
            'youtube': {'name': '📺 YouTube', 'status': 'active', 'note': 'Fully supported'},
            'tiktok': {'name': '🎵 TikTok', 'status': 'active', 'note': 'Enhanced format support'},
            'facebook': {'name': '📘 Facebook', 'status': 'active', 'note': 'Public videos supported'},
            'douyin': {'name': '🎨 Douyin', 'status': 'active', 'note': 'Chinese TikTok version'},
            'instagram': {'name': '📸 Instagram', 'status': 'active', 'note': 'Posts and Reels supported'}
        }
        return jsonify(platforms)
    
    @app.route('/api/test-ytdlp', methods=['POST'])
    def test_ytdlp():
        """Test endpoint to debug yt-dlp issues"""
        try:
            data = request.get_json()
            url = data.get('url', 'https://www.youtube.com/watch?v=dQw4w9WgXcQ')
            
            # Test yt-dlp directly in Flask context
            import yt_dlp
            ydl_opts = {
                'format': 'best[height<=720]',
                'noplaylist': True,
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
            return jsonify({
                'success': True,
                'info_type': str(type(info)),
                'is_dict': isinstance(info, dict),
                'title': info.get('title', 'No title') if isinstance(info, dict) else 'Not a dict',
                'keys': list(info.keys())[:10] if isinstance(info, dict) else []
            })
            
        except Exception as e:
            app_logger.error(f"yt-dlp test error: {str(e)}")
            return jsonify({
                'success': False,
                'error': str(e)
            })
    
    @app.route('/api/video-categories', methods=['GET'])
    def get_video_categories():
        """Get YouTube video categories"""
        try:
            # Common YouTube categories
            categories = [
                {'id': '1', 'name': 'Film & Animation'},
                {'id': '2', 'name': 'Autos & Vehicles'},
                {'id': '10', 'name': 'Music'},
                {'id': '15', 'name': 'Pets & Animals'},
                {'id': '17', 'name': 'Sports'},
                {'id': '19', 'name': 'Travel & Events'},
                {'id': '20', 'name': 'Gaming'},
                {'id': '22', 'name': 'People & Blogs'},
                {'id': '23', 'name': 'Comedy'},
                {'id': '24', 'name': 'Entertainment'},
                {'id': '25', 'name': 'News & Politics'},
                {'id': '26', 'name': 'Howto & Style'},
                {'id': '27', 'name': 'Education'},
                {'id': '28', 'name': 'Science & Technology'}
            ]
            
            return jsonify({
                'categories': categories,
                'total': len(categories)
            })
            
        except Exception as e:
            app_logger.error(f"Categories error: {str(e)}")
            return jsonify({'error': 'Failed to fetch categories'}), 500
    
    @app.route('/api/search', methods=['POST'])
    def search_videos():
        """Search for videos on YouTube"""
        try:
            data = request.get_json()
            query = data.get('query', '').strip()
            platform = data.get('platform', 'youtube').lower()
            max_results = min(int(data.get('max_results', 10)), 50)
            
            if not query:
                return jsonify({'error': 'Search query is required'}), 400
            
            if platform != 'youtube':
                return jsonify({'error': 'Only YouTube search is currently supported'}), 400
            
            # For demo purposes, return sample search results
            sample_results = [
                {
                    'id': f'search_{query}_1',
                    'title': f'{query} - Tutorial Video',
                    'description': f'Learn about {query} in this comprehensive tutorial',
                    'thumbnail': 'https://img.youtube.com/vi/dQw4w9WgXcQ/mqdefault.jpg',
                    'url': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
                    'channel': 'Educational Channel',
                    'views': '250000',
                    'duration': '10:30',
                    'published': '2 days ago'
                },
                {
                    'id': f'search_{query}_2',
                    'title': f'Top 10 {query} Tips',
                    'description': f'Discover the best tips for {query}',
                    'thumbnail': 'https://img.youtube.com/vi/example123/mqdefault.jpg',
                    'url': 'https://www.youtube.com/watch?v=example123',
                    'channel': 'Tips & Tricks',
                    'views': '150000',
                    'duration': '8:45',
                    'published': '1 week ago'
                }
            ]
            
            return jsonify({
                'success': True,
                'platform': platform,
                'videos': sample_results[:max_results],
                'total': len(sample_results),
                'query': query
            })
            
        except Exception as e:
            app_logger.error(f"Video search error: {str(e)}")
            return jsonify({'error': f'Failed to search videos: {str(e)}'}), 500
    
    @app.route('/api/create-short', methods=['POST'])
    def create_short_video():
        """Create a short video from a longer video"""
        try:
            data = request.get_json()
            
            if not isinstance(data, dict):
                return jsonify({'error': f'Invalid request data type: {type(data)}'}), 400
            
            url = data.get('url', '').strip()
            start_time = data.get('start_time', 0)  # in seconds
            duration = data.get('duration', 30)  # default 30 seconds
            
            # Validate required fields
            if not url:
                return jsonify({'error': 'URL is required'}), 400
            
            # Validate URL
            is_valid_url, platform, url_error = validator.validate_url(url)
            if not is_valid_url:
                return jsonify({'error': f'Invalid URL: {url_error or "URL must be from a supported platform"}'}), 400
            
            # Parse start_time if it's a string (e.g., "1:30")
            if isinstance(start_time, str):
                try:
                    if ':' in start_time:
                        parts = start_time.split(':')
                        if len(parts) == 2:
                            start_time = int(parts[0]) * 60 + int(parts[1])
                        else:
                            start_time = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
                    else:
                        start_time = float(start_time)
                except ValueError:
                    return jsonify({'error': 'Invalid start_time format. Use seconds or MM:SS format'}), 400
            
            # Validate duration
            if duration <= 0 or duration > 300:  # Max 5 minutes for shorts
                return jsonify({'error': 'Duration must be between 1 and 300 seconds'}), 400
            
            # Options for video creation
            options = {
                'resize_to_vertical': data.get('vertical_format', False),
                'quality': data.get('quality', 'medium'),  # low, medium, high
                'text_overlay': data.get('text_overlay'),  # Optional text overlay
            }
            
            with LogContext(api_logger, "Short video creation"):
                # Download video using the enhanced video processor
                try:
                    video_path, video_title, metadata = extractor.download_video(url)
                except Exception as e:
                    app_logger.error(f"Failed to download video: {str(e)}")
                    return jsonify({'error': 'Failed to download video'}), 500
                
                if not video_path:
                    return jsonify({'error': 'Failed to download video'}), 500
                
                # Generate unique filename
                import uuid
                unique_id = str(uuid.uuid4())[:8]
                safe_title = "".join(c for c in (video_title or "short")[:50] if c.isalnum() or c in (' ', '-', '_')).strip()
                output_name = f"{safe_title}_{unique_id}_short"
                
                # Create short video using moviepy
                try:
                    from moviepy.editor import VideoFileClip, TextClip, CompositeVideoClip
                    
                    config = get_config()
                    output_path = config.SHORTS_FOLDER / f"{output_name}.mp4"
                    
                    # Load video
                    video = VideoFileClip(video_path)
                    
                    # Validate start_time against video duration
                    if start_time >= video.duration:
                        video.close()
                        return jsonify({'error': f'Start time ({start_time}s) exceeds video duration ({video.duration:.1f}s)'}), 400
                    
                    # Adjust duration if it exceeds video length
                    if start_time + duration > video.duration:
                        duration = video.duration - start_time
                    
                    # Extract the clip
                    short_clip = video.subclip(start_time, start_time + duration)
                    
                    # Apply resize for vertical format if requested
                    if options.get('resize_to_vertical', False):
                        w, h = short_clip.size
                        if w/h > 9/16:  # Too wide, crop sides
                            new_w = int(h * 9/16)
                            short_clip = short_clip.crop(x1=(w-new_w)//2, x2=(w+new_w)//2)
                        # Resize to standard shorts resolution
                        short_clip = short_clip.resize((1080, 1920))
                    
                    # Add text overlay if specified
                    if options.get('text_overlay') and options['text_overlay'].get('text'):
                        text_config = options['text_overlay']
                        txt_clip = TextClip(text_config.get('text', ''), 
                                          fontsize=text_config.get('fontsize', 50),
                                          color=text_config.get('color', 'white'),
                                          stroke_color=text_config.get('stroke_color', 'black'),
                                          stroke_width=text_config.get('stroke_width', 2))
                        
                        position = text_config.get('position', 'bottom')
                        if position == 'bottom':
                            txt_clip = txt_clip.set_position(('center', 'bottom')).set_margin(50)
                        elif position == 'top':
                            txt_clip = txt_clip.set_position(('center', 'top')).set_margin(50)
                        else:
                            txt_clip = txt_clip.set_position('center')
                        
                        txt_clip = txt_clip.set_duration(short_clip.duration)
                        short_clip = CompositeVideoClip([short_clip, txt_clip])
                    
                    # Write video file with quality settings
                    quality = options.get('quality', 'medium')
                    if quality == 'high':
                        short_clip.write_videofile(str(output_path), codec='libx264', bitrate='5000k', verbose=False, logger=None)
                    elif quality == 'low':
                        short_clip.write_videofile(str(output_path), codec='libx264', bitrate='1000k', verbose=False, logger=None)
                    else:  # medium
                        short_clip.write_videofile(str(output_path), codec='libx264', bitrate='2000k', verbose=False, logger=None)
                    
                    # Clean up
                    video.close()
                    short_clip.close()
                    
                    return jsonify({
                        'success': True,
                        'message': 'Short video created successfully',
                        'filename': f"{output_name}.mp4",
                        'title': video_title,
                        'duration': duration,
                        'start_time': start_time,
                        'download_url': f'/shorts/{output_name}.mp4'
                    })
                    
                except Exception as e:
                    app_logger.error(f"Failed to create short video: {str(e)}")
                    return jsonify({'error': f'Failed to create short video: {str(e)}'}), 500
        
        except Exception as e:
            app_logger.error(f"Short video creation error: {str(e)}")
            return jsonify({'error': f'Short video creation failed: {str(e)}'}), 500
    
    @app.route('/shorts/<filename>')
    def serve_short_video(filename):
        """Serve generated short videos"""
        config = get_config()
        return send_from_directory(str(config.SHORTS_FOLDER), filename)
    
    @app.route('/api/youtube-auth', methods=['GET'])
    def youtube_auth():
        """Start YouTube OAuth2 authentication"""
        try:
            success, auth_url = youtube_uploader.authenticate()
            if success:
                return jsonify({'authenticated': True, 'message': 'Already authenticated'})
            else:
                return jsonify({'authenticated': False, 'auth_url': auth_url})
        except Exception as e:
            app_logger.error(f"YouTube auth error: {str(e)}")
            return jsonify({'error': str(e)}), 500
    
    @app.route('/api/youtube-callback', methods=['POST'])
    def youtube_callback():
        """Handle YouTube OAuth2 callback"""
        try:
            data = request.get_json()
            auth_code = data.get('code')
            
            if not auth_code:
                return jsonify({'error': 'Authorization code required'}), 400
            
            success, message = youtube_uploader.complete_auth(
                auth_code, 
                "http://localhost:8080/oauth2callback"
            )
            
            if success:
                return jsonify({'success': True, 'message': message})
            else:
                return jsonify({'error': message}), 400
                
        except Exception as e:
            app_logger.error(f"YouTube callback error: {str(e)}")
            return jsonify({'error': str(e)}), 500
    
    @app.route('/api/upload-to-youtube', methods=['POST'])
    def upload_to_youtube():
        """Upload short video to YouTube"""
        try:
            data = request.get_json()
            video_path = data.get('video_path')
            title = data.get('title', 'Viral Short Video - Created with VideoExtract')
            description = data.get('description', 'Created with VideoExtract - AI-powered short video generator\n\n#Shorts #VideoExtract #Viral')
            tags = data.get('tags', ['Shorts', 'VideoExtract', 'AI', 'viral', 'trending'])
            privacy = data.get('privacy', 'private')  # private, public, unlisted
            
            if not video_path:
                return jsonify({'error': 'Video path required'}), 400
            
            if not os.path.exists(video_path):
                return jsonify({'error': 'Video file not found'}), 404
            
            # Validate video for YouTube Shorts
            is_valid, validation_msg = youtube_uploader.validate_short_video(video_path)
            if not is_valid:
                return jsonify({'error': f'Video validation failed: {validation_msg}'}), 400
            
            # Upload to YouTube
            success, message, video_id = youtube_uploader.upload_video(
                video_path=video_path,
                title=title,
                description=description,
                tags=tags,
                privacy_status=privacy,
                is_short=True
            )
            
            if success:
                return jsonify({
                    'success': True,
                    'message': message,
                    'video_id': video_id,
                    'youtube_url': f'https://www.youtube.com/watch?v={video_id}',
                    'studio_url': f'https://studio.youtube.com/video/{video_id}/edit'
                })
            else:
                return jsonify({'error': message}), 500
                
        except Exception as e:
            app_logger.error(f"YouTube upload error: {str(e)}")
            return jsonify({'error': str(e)}), 500
    
    @app.route('/api/youtube-quota', methods=['GET'])
    def youtube_quota():
        """Get YouTube API quota information"""
        try:
            quota_info = youtube_uploader.get_upload_quota_info()
            return jsonify(quota_info)
        except Exception as e:
            app_logger.error(f"YouTube quota error: {str(e)}")
            return jsonify({'error': str(e)}), 500
    
    # Import uuid here to avoid circular imports
    import uuid
    
    return app

def main():
    """Main entry point"""
    config = get_config()
    app = create_app()
    
    app_logger.info(
        "Starting Video Frame Extractor",
        environment=config.FLASK_ENV,
        debug=config.DEBUG
    )
    
    app.run(
        host='0.0.0.0',
        port=5000,
        debug=config.DEBUG,
        threaded=True
    )

if __name__ == '__main__':
    main()
