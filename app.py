from flask import Flask, request, render_template, jsonify, send_from_directory
import os
import cv2
import yt_dlp
import uuid
from urllib.parse import urlparse
from moviepy.editor import VideoFileClip, TextClip, CompositeVideoClip
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from dotenv import load_dotenv
import requests
from datetime import datetime, timedelta
import json

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Configuration
DOWNLOAD_FOLDER = 'downloads'
FRAMES_FOLDER = 'extracted_frames'
SHORTS_FOLDER = 'generated_shorts'
ALLOWED_PLATFORMS = [
    'youtube.com', 'youtu.be',           # YouTube
    'tiktok.com', 'vm.tiktok.com',       # TikTok
    'facebook.com', 'fb.com', 'm.facebook.com', 'www.facebook.com',  # Facebook
    'douyin.com', 'v.douyin.com',        # Douyin
    'instagram.com', 'www.instagram.com'  # Instagram (bonus)
]

# YouTube API Configuration
YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY', '')
YOUTUBE_API_SERVICE_NAME = 'youtube'
YOUTUBE_API_VERSION = 'v3'

# Ensure folders exist
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)
os.makedirs(FRAMES_FOLDER, exist_ok=True)
os.makedirs(SHORTS_FOLDER, exist_ok=True)

class VideoFrameExtractor:
    def __init__(self):
        self.ydl_opts = {
            'format': 'best[height<=720]',  # Limit to 720p for faster processing
            'outtmpl': {'default': f'{DOWNLOAD_FOLDER}/%(title)s.%(ext)s'},
            'noplaylist': True,
            'ignoreerrors': False,
            'no_warnings': False,
            'extractaudio': False,
            'writeinfojson': False,
            'writedescription': False,
            'writesubtitles': False,
            'writeautomaticsub': False,
        }
        
        # Separate options for platforms that need cookies
        self.ydl_opts_with_cookies = self.ydl_opts.copy()
        # Try multiple cookie sources in order of preference
        self.cookie_sources = ['chrome', 'firefox', 'edge', 'safari']
    
    def is_valid_url(self, url):
        """Check if URL is from supported platforms"""
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            return any(platform in domain for platform in ALLOWED_PLATFORMS)
        except Exception:
            return False
    
    def get_platform_from_url(self, url):
        """Detect platform from URL"""
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            if 'tiktok.com' in domain or 'vm.tiktok.com' in domain:
                return 'tiktok'
            elif 'youtube.com' in domain or 'youtu.be' in domain:
                return 'youtube'
            elif 'facebook.com' in domain or 'fb.com' in domain:
                return 'facebook'
            elif 'douyin.com' in domain:
                return 'douyin'
            elif 'instagram.com' in domain:
                return 'instagram'
            else:
                return 'unknown'
        except Exception:
            return 'unknown'
    
    def download_video(self, url):
        """Download video from URL and return local path"""
        try:
            # Detect platform and set appropriate format
            platform = self.get_platform_from_url(url)
            
            # Create platform-specific options
            download_opts = self.ydl_opts.copy()
            
            if platform == 'tiktok':
                # For TikTok, use best available format (often h264_540p works best)
                download_opts['format'] = 'best/h264_540p_468478/h264_540p_287260/bytevc1_540p_248040/download'
                print("Using TikTok-specific format selection")
            elif platform == 'douyin':
                # Douyin uses similar format structure to TikTok
                download_opts['format'] = 'best/mp4'
                print("Using Douyin-specific format selection")
            elif platform == 'facebook':
                # Facebook video formats
                download_opts['format'] = 'best[height<=720]/best'
                print("Using Facebook-specific format selection")
            elif platform == 'instagram':
                # Instagram video formats - try with cookies first, then without
                download_opts['format'] = 'best[height<=720]/mp4/best'
                print("Using Instagram-specific format selection")
                return self._download_instagram_video(url, download_opts)
            else:
                # Keep original format for YouTube and other platforms
                download_opts['format'] = 'best[height<=720]'
                print("Using standard format selection")
            
            return self._download_with_ytdlp(url, download_opts, platform)
                
        except Exception as e:
            print(f"Error downloading video: {str(e)}")
            import traceback
            print(f"Traceback: {traceback.format_exc()}")
            return None, None
    
    def _download_instagram_video(self, url, base_opts):
        """Special handling for Instagram videos with cookie fallback"""
        print("Attempting Instagram download with cookie fallback...")
        
        # Try 1: Manual cookie file if it exists
        cookie_file_path = os.path.join(os.path.dirname(__file__), 'instagram_cookies.txt')
        if os.path.exists(cookie_file_path):
            try:
                print("Trying manual cookie file...")
                opts_with_cookies = base_opts.copy()
                opts_with_cookies['cookiefile'] = cookie_file_path
                
                result = self._download_with_ytdlp(url, opts_with_cookies, 'instagram')
                if result[0]:  # If successful
                    print("Success with manual cookie file!")
                    return result
                    
            except Exception as e:
                print(f"Failed with manual cookies: {str(e)}")
        
        # Try 2: With cookies from different browsers
        for browser in self.cookie_sources:
            try:
                print(f"Trying cookies from {browser}...")
                opts_with_cookies = base_opts.copy()
                opts_with_cookies['cookiesfrombrowser'] = (browser,)
                
                result = self._download_with_ytdlp(url, opts_with_cookies, 'instagram')
                if result[0]:  # If successful
                    print(f"Success with {browser} cookies!")
                    return result
                    
            except Exception as e:
                print(f"Failed with {browser} cookies: {str(e)}")
                continue
        
        # Try 3: Without cookies (for public content)
        try:
            print("Trying without cookies (public content only)...")
            result = self._download_with_ytdlp(url, base_opts, 'instagram')
            if result[0]:
                print("Success without cookies!")
                return result
        except Exception as e:
            print(f"Failed without cookies: {str(e)}")
        
        # If all attempts fail, return helpful error with manual cookie instructions
        error_msg = (
            "Instagram Error: Could not download this video\n\n"
            "📸 This Instagram content appears to be:\n"
            "• Age-restricted (18+)\n"
            "• Private or login-required\n"
            "• Protected by Instagram's restrictions\n\n"
            "💡 Cookie Authentication Failed:\n"
            "• Chrome: Database access blocked (security limitation)\n"
            "• Firefox: Not installed or no cookies found\n"
            "• Edge: Same database issue as Chrome\n\n"
            "🔧 Manual Cookie Solution:\n"
            "1. Export Instagram cookies from your browser\n"
            "2. Save as 'instagram_cookies.txt' in the app directory\n"
            "3. Use browser extensions like 'Export Cookies'\n"
            "4. Ensure you're logged into Instagram first\n\n"
            "🌐 Alternative Solutions:\n"
            "• Try a different public Instagram post/reel\n"
            "• Use YouTube, TikTok, or other supported platforms\n"
            "• Contact support if this is business-critical content"
        )
        
        return None, error_msg
    
    def _download_with_ytdlp(self, url, download_opts, platform):
        """Core yt-dlp download logic"""
        try:
            with yt_dlp.YoutubeDL(download_opts) as ydl:
                try:
                    # Get video info
                    print(f"Extracting info for URL: {url}")
                    info = ydl.extract_info(url, download=False)
                    print(f"Info type: {type(info)}")
                    
                    # Handle case where info might not be a dict
                    if not isinstance(info, dict):
                        print(f"Unexpected info type: {type(info)}, content: {str(info)[:200]}...")
                        return None, None
                    
                    # Check if info is empty or None
                    if not info:
                        print("Info is empty or None")
                        return None, None
                    
                    title = info.get('title', 'unknown')
                    print(f"Video title: {title}")
                    
                    # Sanitize title for filename
                    title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).rstrip()
                    if not title:
                        title = 'video'
                    
                    # Create unique filename to avoid conflicts
                    unique_id = str(uuid.uuid4())[:8]
                    filename = f"{title}_{unique_id}.%(ext)s"
                    
                    # Update download options with filename template
                    download_opts['outtmpl'] = {'default': f'{DOWNLOAD_FOLDER}/{filename}'}
                    
                    print(f"Starting download with template: {download_opts['outtmpl']}")
                    print(f"Using format: {download_opts['format']}")
                    
                    # Download video with updated options
                    with yt_dlp.YoutubeDL(download_opts) as download_ydl:
                        download_ydl.download([url])
                    
                    print("Download completed, looking for file...")
                    
                    # Find downloaded file
                    for file in os.listdir(DOWNLOAD_FOLDER):
                        print(f"Found file: {file}")
                        if unique_id in file:
                            print(f"Matched file: {file}")
                            return os.path.join(DOWNLOAD_FOLDER, file), title
                    
                    print("No matching file found after download")
                    return None, None
                    
                except yt_dlp.utils.DownloadError as e:
                    error_msg = str(e)
                    print(f"yt-dlp download error: {error_msg}")
                    
                    # Provide platform-specific error guidance
                    if platform == 'instagram' and ('Restricted Video' in error_msg or 'cookies' in error_msg):
                        enhanced_error = (
                            f"Instagram Error: {error_msg}\n\n"
                            "📸 Instagram Troubleshooting:\n"
                            "• This video may be age-restricted or private\n"
                            "• Try logging into Instagram in your browser first\n"
                            "• Public posts usually work better than private/restricted content\n"
                            "• Consider using the Instagram mobile app link instead"
                        )
                        print(enhanced_error)
                        return None, enhanced_error
                    elif platform == 'facebook' and ('login' in error_msg.lower() or 'private' in error_msg.lower()):
                        enhanced_error = (
                            f"Facebook Error: {error_msg}\n\n"
                            "📘 Facebook Troubleshooting:\n"
                            "• This video may be private or require login\n"
                            "• Only public Facebook videos can be downloaded\n"
                            "• Make sure the video is accessible without logging in"
                        )
                        print(enhanced_error)
                        return None, enhanced_error
                    elif platform == 'tiktok' and 'format' in error_msg.lower():
                        enhanced_error = (
                            f"TikTok Error: {error_msg}\n\n"
                            "🎵 TikTok Troubleshooting:\n"
                            "• This TikTok video may be region-blocked\n"
                            "• Try using the vm.tiktok.com share link instead\n"
                            "• Some TikTok videos have download restrictions"
                        )
                        print(enhanced_error)
                        return None, enhanced_error
                    else:
                        return None, error_msg
                except Exception as e:
                    print(f"Error in download process: {str(e)}")
                    import traceback
                    print(f"Traceback: {traceback.format_exc()}")
                    return None, None
        except Exception as e:
            print(f"Error downloading video: {str(e)}")
            import traceback
            print(f"Traceback: {traceback.format_exc()}")
            return None, None
    
    def extract_frames_at_times(self, video_path, timestamps):
        """Extract frames at specific timestamps"""
        try:
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                return None, "Cannot open video file"
            
            fps = cap.get(cv2.CAP_PROP_FPS)
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            duration = total_frames / fps if fps > 0 else 0
            
            extracted_frames = []
            
            for timestamp in timestamps:
                # Parse timestamp (support formats: "1:23", "83", "1:23:45")
                seconds = self.parse_timestamp(timestamp)
                if seconds is None or seconds > duration:
                    continue
                
                # Calculate frame number
                frame_number = int(seconds * fps)
                
                # Set video position
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
                
                # Read frame
                ret, frame = cap.read()
                if ret:
                    # Create unique filename for frame
                    frame_id = str(uuid.uuid4())[:8]
                    frame_filename = f"frame_{timestamp.replace(':', '-')}s_{frame_id}.jpg"
                    frame_path = os.path.join(FRAMES_FOLDER, frame_filename)
                    
                    # Save frame
                    cv2.imwrite(frame_path, frame)
                    extracted_frames.append({
                        'timestamp': timestamp,
                        'filename': frame_filename,
                        'path': frame_path
                    })
            
            cap.release()
            return extracted_frames, None
            
        except Exception as e:
            return None, f"Error extracting frames: {str(e)}"
    
    def parse_timestamp(self, timestamp):
        """Parse timestamp string to seconds"""
        try:
            parts = timestamp.split(':')
            if len(parts) == 1:
                return float(parts[0])
            elif len(parts) == 2:
                return int(parts[0]) * 60 + float(parts[1])
            elif len(parts) == 3:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
            else:
                return None
        except Exception:
            return None

class ShortVideoCreator:
    """Create short videos from longer videos with various options"""
    
    def create_short_video(self, video_path, start_time, duration, output_name, options=None):
        """
        Create a short video from a longer video
        
        Args:
            video_path (str): Path to input video
            start_time (float): Start time in seconds
            duration (float): Duration of short video in seconds
            output_name (str): Name for output file
            options (dict): Additional options for video creation
        """
        try:
            if options is None:
                options = {}
            
            # Load video
            video = VideoFileClip(video_path)
            
            # Check if start_time and duration are valid
            if start_time < 0:
                start_time = 0
            if start_time + duration > video.duration:
                duration = video.duration - start_time
            
            # Extract the clip
            short_clip = video.subclip(start_time, start_time + duration)
            
            # Apply options
            if options.get('resize_to_vertical', False):
                # Resize for vertical format (9:16 ratio for shorts)
                short_clip = self._resize_for_shorts(short_clip)
            
            # Add text overlay if specified
            if options.get('text_overlay'):
                short_clip = self._add_text_overlay(short_clip, options['text_overlay'])
            
            # Set quality
            quality = options.get('quality', 'medium')
            
            # Generate output path
            output_path = os.path.join(SHORTS_FOLDER, f"{output_name}.mp4")
            
            # Write video file
            if quality == 'high':
                short_clip.write_videofile(output_path, codec='libx264', bitrate='5000k')
            elif quality == 'low':
                short_clip.write_videofile(output_path, codec='libx264', bitrate='1000k')
            else:  # medium
                short_clip.write_videofile(output_path, codec='libx264', bitrate='2000k')
            
            # Clean up
            video.close()
            short_clip.close()
            
            return output_path, None
            
        except Exception as e:
            return None, f"Error creating short video: {str(e)}"
    
    def _resize_for_shorts(self, clip):
        """Resize video for vertical shorts format (9:16)"""
        try:
            # Get original dimensions
            w, h = clip.size
            
            # Calculate new dimensions for 9:16 ratio
            if w/h > 9/16:  # Too wide, crop sides
                new_w = int(h * 9/16)
                clip = clip.crop(x1=(w-new_w)//2, x2=(w+new_w)//2)
            else:  # Too tall or perfect, crop top/bottom if needed
                new_h = int(w * 16/9)
                if new_h < h:
                    clip = clip.crop(y1=(h-new_h)//2, y2=(h+new_h)//2)
            
            # Resize to standard shorts resolution (1080x1920)
            clip = clip.resize((1080, 1920))
            
            return clip
        except Exception as e:
            print(f"Error resizing for shorts: {e}")
            return clip
    
    def _add_text_overlay(self, clip, text_config):
        """Add text overlay to video"""
        try:
            text = text_config.get('text', '')
            if not text:
                return clip
            
            # Create text clip
            txt_clip = TextClip(text, 
                              fontsize=text_config.get('fontsize', 50),
                              color=text_config.get('color', 'white'),
                              stroke_color=text_config.get('stroke_color', 'black'),
                              stroke_width=text_config.get('stroke_width', 2))
            
            # Position text
            position = text_config.get('position', 'bottom')
            if position == 'bottom':
                txt_clip = txt_clip.set_position(('center', 'bottom')).set_margin(50)
            elif position == 'top':
                txt_clip = txt_clip.set_position(('center', 'top')).set_margin(50)
            else:
                txt_clip = txt_clip.set_position('center')
            
            # Set duration to match video
            txt_clip = txt_clip.set_duration(clip.duration)
            
            # Composite video with text
            final_clip = CompositeVideoClip([clip, txt_clip])
            
            return final_clip
        except Exception as e:
            print(f"Error adding text overlay: {e}")
            return clip
    
    def get_video_info(self, video_path):
        """Get basic info about a video file"""
        try:
            video = VideoFileClip(video_path)
            info = {
                'duration': video.duration,
                'fps': video.fps,
                'size': video.size,
                'width': video.w,
                'height': video.h
            }
            video.close()
            return info
        except Exception as e:
            return None

class TrendingVideosTracker:
    """Track trending videos from YouTube and TikTok and provide search functionality"""
    
    def __init__(self, api_key=None):
        self.api_key = api_key or YOUTUBE_API_KEY
        self.youtube = None
        if self.api_key and self.api_key != 'your_youtube_api_key_here':
            try:
                self.youtube = build(YOUTUBE_API_SERVICE_NAME, YOUTUBE_API_VERSION, 
                                   developerKey=self.api_key)
            except Exception as e:
                print(f"Failed to initialize YouTube API: {e}")
                self.youtube = None
    
    def get_trending_videos(self, platform='youtube', region_code='US', category_id=None, max_results=20, category=None):
        """Get trending videos from YouTube or TikTok"""
        if platform.lower() == 'tiktok':
            return self.get_tiktok_trending(max_results, category)
        else:
            return self.get_youtube_trending(region_code, category_id, max_results)
    
    def get_youtube_trending(self, region_code='US', category_id=None, max_results=20):
        """Get trending videos from YouTube"""
        if not self.youtube:
            return self._get_mock_youtube_trending_data(), "YouTube API not configured. Showing mock data."
        
        try:
            request = self.youtube.videos().list(
                part='snippet,statistics,contentDetails',
                chart='mostPopular',
                regionCode=region_code,
                videoCategoryId=category_id,
                maxResults=max_results
            )
            
            response = request.execute()
            
            videos = []
            for item in response['items']:
                video_data = self._format_youtube_video_data(item)
                videos.append(video_data)
            
            return videos, None
            
        except HttpError as e:
            error_msg = f"YouTube API error: {e}"
            print(error_msg)
            return self._get_mock_youtube_trending_data(), error_msg
        except Exception as e:
            error_msg = f"Error fetching YouTube trending videos: {e}"
            print(error_msg)
            return self._get_mock_youtube_trending_data(), error_msg
    
    def get_tiktok_trending(self, max_results=20, category=None):
        """Get trending videos from TikTok (using mock data since no public API)"""
        try:
            # Get all TikTok data or filter by category
            all_videos = self._get_mock_tiktok_trending_data()
            
            if category and category != '':
                # Filter videos by category
                filtered_videos = []
                for video in all_videos:
                    video_categories = video.get('categories', [])
                    if category in video_categories:
                        filtered_videos.append(video)
                videos = filtered_videos[:max_results]
                
                if not videos:
                    # If no videos found for category, return a mix
                    videos = all_videos[:max_results//2]
            else:
                videos = all_videos[:max_results]
            
            return videos, "TikTok trending data is curated content. For real-time data, consider using TikTok's official tools."
            
        except Exception as e:
            error_msg = f"Error fetching TikTok trending videos: {e}"
            print(error_msg)
            return self._get_mock_tiktok_trending_data()[:max_results], error_msg
    
    def search_videos(self, query, platform='youtube', max_results=10):
        """Search for videos on YouTube or TikTok"""
        if platform.lower() == 'tiktok':
            return self.search_tiktok_videos(query, max_results)
        else:
            return self.search_youtube_videos(query, max_results)
    
    def search_youtube_videos(self, query, max_results=10):
        """Search for videos on YouTube"""
        if not self.youtube:
            return self._get_mock_youtube_search_data(query), "YouTube API not configured. Showing mock data."
        
        try:
            # Search for videos
            search_request = self.youtube.search().list(
                part='snippet',
                q=query,
                type='video',
                maxResults=max_results,
                order='relevance'
            )
            
            search_response = search_request.execute()
            
            # Get video IDs
            video_ids = [item['id']['videoId'] for item in search_response['items']]
            
            # Get detailed video information
            videos_request = self.youtube.videos().list(
                part='snippet,statistics,contentDetails',
                id=','.join(video_ids)
            )
            
            videos_response = videos_request.execute()
            
            videos = []
            for item in videos_response['items']:
                video_data = self._format_youtube_video_data(item)
                videos.append(video_data)
            
            return videos, None
            
        except HttpError as e:
            error_msg = f"YouTube API error: {e}"
            print(error_msg)
            return self._get_mock_youtube_search_data(query), error_msg
        except Exception as e:
            error_msg = f"Error searching YouTube videos: {e}"
            print(error_msg)
            return self._get_mock_youtube_search_data(query), error_msg
    
    def search_tiktok_videos(self, query, max_results=10):
        """Search for videos on TikTok (using mock data)"""
        try:
            # Since TikTok doesn't have a public search API,
            # we'll return mock data that simulates search results
            videos = self._get_mock_tiktok_search_data(query)[:max_results]
            return videos, "TikTok search results are simulated. For real searches, use TikTok app directly."
            
        except Exception as e:
            error_msg = f"Error searching TikTok videos: {e}"
            print(error_msg)
            return self._get_mock_tiktok_search_data(query)[:max_results], error_msg
    
    
    def _format_youtube_video_data(self, item):
        """Format YouTube API response data"""
        snippet = item['snippet']
        statistics = item.get('statistics', {})
        content_details = item.get('contentDetails', {})
        
        # Parse duration
        duration_str = content_details.get('duration', 'PT0S')
        duration_seconds = self._parse_duration(duration_str)
        
        return {
            'id': item['id'],
            'title': snippet['title'],
            'description': snippet.get('description', '')[:200] + '...' if snippet.get('description') else '',
            'thumbnail': snippet['thumbnails'].get('medium', {}).get('url', ''),
            'channel_title': snippet['channelTitle'],
            'published_at': snippet['publishedAt'],
            'published_date': snippet['publishedAt'][:10] if snippet.get('publishedAt') else 'N/A',
            'duration': duration_seconds,
            'duration_formatted': self._format_duration(duration_seconds),
            'view_count': int(statistics.get('viewCount', 0)),
            'like_count': int(statistics.get('likeCount', 0)),
            'url': f"https://www.youtube.com/watch?v={item['id']}",
            'embed_url': f"https://www.youtube.com/embed/{item['id']}",
            'platform': 'youtube',
            'uploader': snippet['channelTitle']
        }
    
    def _format_tiktok_video_data(self, video_data):
        """Format TikTok video data (mock data structure)"""
        return {
            'id': video_data.get('id', ''),
            'title': video_data.get('title', ''),
            'description': video_data.get('description', ''),
            'thumbnail': video_data.get('thumbnail', ''),
            'channel_title': video_data.get('author', ''),
            'published_at': video_data.get('published_at', ''),
            'published_date': video_data.get('published_date', 'N/A'),
            'duration': video_data.get('duration', 0),
            'duration_formatted': self._format_duration(video_data.get('duration', 0)),
            'view_count': video_data.get('view_count', 0),
            'like_count': video_data.get('like_count', 0),
            'url': video_data.get('url', ''),
            'embed_url': video_data.get('embed_url', ''),
            'platform': 'tiktok',
            'uploader': video_data.get('author', '')
        }
    
    def _parse_duration(self, duration_str):
        """Parse YouTube duration format (PT4M13S) to seconds"""
        import re
        
        if not duration_str:
            return 0
        
        # Remove PT prefix
        duration_str = duration_str[2:] if duration_str.startswith('PT') else duration_str
        
        # Parse hours, minutes, seconds
        hours = re.findall(r'(\d+)H', duration_str)
        minutes = re.findall(r'(\d+)M', duration_str)
        seconds = re.findall(r'(\d+)S', duration_str)
        
        total_seconds = 0
        total_seconds += int(hours[0]) * 3600 if hours else 0
        total_seconds += int(minutes[0]) * 60 if minutes else 0
        total_seconds += int(seconds[0]) if seconds else 0
        
        return total_seconds
    
    def _format_duration(self, seconds):
        """Format seconds to readable duration"""
        if seconds < 60:
            return f"{seconds}s"
        elif seconds < 3600:
            minutes = seconds // 60
            secs = seconds % 60
            return f"{minutes}:{secs:02d}"
        else:
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            secs = seconds % 60
            return f"{hours}:{minutes:02d}:{secs:02d}"
    
    def _get_mock_youtube_trending_data(self):
        """Mock YouTube trending data when API is not available"""
        return [
            {
                'id': 'dQw4w9WgXcQ',
                'title': 'Rick Astley - Never Gonna Give You Up (Official Video)',
                'description': 'The official video for "Never Gonna Give You Up" by Rick Astley...',
                'thumbnail': 'https://i.ytimg.com/vi/dQw4w9WgXcQ/mqdefault.jpg',
                'channel_title': 'Rick Astley',
                'published_at': '2009-10-25T06:57:33Z',
                'published_date': '2009-10-25',
                'duration': 213,
                'duration_formatted': '3:33',
                'view_count': 1400000000,
                'like_count': 15000000,
                'url': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
                'embed_url': 'https://www.youtube.com/embed/dQw4w9WgXcQ',
                'platform': 'youtube',
                'uploader': 'Rick Astley'
            },
            {
                'id': 'y3GDWwWnKlc',
                'title': 'Amazing Music Video - Trending Now',
                'description': 'This amazing music video is trending worldwide...',
                'thumbnail': 'https://i.ytimg.com/vi/y3GDWwWnKlc/mqdefault.jpg',
                'channel_title': 'Music Channel',
                'published_at': '2024-08-10T10:30:00Z',
                'published_date': '2024-08-10',
                'duration': 240,
                'duration_formatted': '4:00',
                'view_count': 5200000,
                'like_count': 185000,
                'url': 'https://www.youtube.com/watch?v=y3GDWwWnKlc',
                'embed_url': 'https://www.youtube.com/embed/y3GDWwWnKlc',
                'platform': 'youtube',
                'uploader': 'Music Channel'
            },
            {
                'id': 'abc123def456',
                'title': 'Viral Dance Challenge Compilation 2024',
                'description': 'The best dance challenges that went viral this year...',
                'thumbnail': 'https://i.ytimg.com/vi/abc123def456/mqdefault.jpg',
                'channel_title': 'Dance Central',
                'published_at': '2024-08-12T15:00:00Z',
                'published_date': '2024-08-12',
                'duration': 180,
                'duration_formatted': '3:00',
                'view_count': 3400000,
                'like_count': 125000,
                'url': 'https://www.youtube.com/watch?v=abc123def456',
                'embed_url': 'https://www.youtube.com/embed/abc123def456',
                'platform': 'youtube',
                'uploader': 'Dance Central'
            }
        ]
    
    def _get_mock_tiktok_trending_data(self):
        """Mock TikTok trending data"""
        return [
            {
                'id': 'tiktok_trend_001',
                'title': '🔥 Viral Dance Trend - Everyone\'s Doing This!',
                'description': 'The hottest dance trend taking over TikTok right now! Try it yourself! #dance #viral #trending',
                'thumbnail': 'https://via.placeholder.com/300x400/ff0050/white?text=TikTok+Dance',
                'author': '@dancequeen2024',
                'published_at': '2024-08-13T12:00:00Z',
                'published_date': '2024-08-13',
                'duration': 15,
                'duration_formatted': '0:15',
                'view_count': 12500000,
                'like_count': 2100000,
                'url': 'https://www.tiktok.com/@dancequeen2024/video/7364829471234567890',
                'embed_url': 'https://www.tiktok.com/@dancequeen2024/video/7364829471234567890',
                'platform': 'tiktok',
                'uploader': '@dancequeen2024',
                'categories': ['dance', 'music']
            },
            {
                'id': 'tiktok_trend_002',
                'title': 'POV: You discover a life hack that changes everything ✨',
                'description': 'This life hack will blow your mind! Save this for later 💫 #lifehack #viral #fyp #tips',
                'thumbnail': 'https://via.placeholder.com/300x400/00d4ff/white?text=Life+Hack',
                'author': '@lifehackmaster',
                'published_at': '2024-08-13T09:30:00Z',
                'published_date': '2024-08-13',
                'duration': 30,
                'duration_formatted': '0:30',
                'view_count': 8900000,
                'like_count': 1500000,
                'url': 'https://www.tiktok.com/@lifehackmaster/video/7364829471234567891',
                'embed_url': 'https://www.tiktok.com/@lifehackmaster/video/7364829471234567891',
                'platform': 'tiktok',
                'uploader': '@lifehackmaster',
                'categories': ['lifehacks']
            },
            {
                'id': 'tiktok_trend_003',
                'title': 'Cooking hack that will save you hours! 🍳',
                'description': 'Chef reveals secret technique! This will change how you cook forever #cooking #chef #foodhack #viral',
                'thumbnail': 'https://via.placeholder.com/300x400/ff6b35/white?text=Cooking+Hack',
                'author': '@chefpro_official',
                'published_at': '2024-08-13T14:15:00Z',
                'published_date': '2024-08-13',
                'duration': 45,
                'duration_formatted': '0:45',
                'view_count': 6700000,
                'like_count': 890000,
                'url': 'https://www.tiktok.com/@chefpro_official/video/7364829471234567892',
                'embed_url': 'https://www.tiktok.com/@chefpro_official/video/7364829471234567892',
                'platform': 'tiktok',
                'uploader': '@chefpro_official',
                'categories': ['cooking']
            },
            {
                'id': 'tiktok_trend_004',
                'title': 'When you realize your pet is smarter than you 🐕',
                'description': 'This dog is literally a genius! Wait for the end 😱 #pets #dogs #funny #viral #animals',
                'thumbnail': 'https://via.placeholder.com/300x400/4ecdc4/white?text=Smart+Pet',
                'author': '@pawsome_pets',
                'published_at': '2024-08-13T11:45:00Z',
                'published_date': '2024-08-13',
                'duration': 22,
                'duration_formatted': '0:22',
                'view_count': 15200000,
                'like_count': 3200000,
                'url': 'https://www.tiktok.com/@pawsome_pets/video/7364829471234567893',
                'embed_url': 'https://www.tiktok.com/@pawsome_pets/video/7364829471234567893',
                'platform': 'tiktok',
                'uploader': '@pawsome_pets',
                'categories': ['pets', 'comedy']
            },
            {
                'id': 'tiktok_trend_005',
                'title': 'This makeup transformation is INSANE! ✨',
                'description': 'From basic to glamorous in 60 seconds! Products used in comments ⬇️ #makeup #transformation #beauty #viral',
                'thumbnail': 'https://via.placeholder.com/300x400/e74c3c/white?text=Makeup+Magic',
                'author': '@beauty_goddess',
                'published_at': '2024-08-13T16:20:00Z',
                'published_date': '2024-08-13',
                'duration': 60,
                'duration_formatted': '1:00',
                'view_count': 9800000,
                'like_count': 1800000,
                'url': 'https://www.tiktok.com/@beauty_goddess/video/7364829471234567894',
                'embed_url': 'https://www.tiktok.com/@beauty_goddess/video/7364829471234567894',
                'platform': 'tiktok',
                'uploader': '@beauty_goddess',
                'categories': ['beauty']
            },
            {
                'id': 'tiktok_trend_006',
                'title': 'Plot twist ending that nobody saw coming 🤯',
                'description': 'This story will keep you on the edge of your seat! Part 2 coming soon 👀 #storytime #plottwist #viral #fyp',
                'thumbnail': 'https://via.placeholder.com/300x400/9b59b6/white?text=Plot+Twist',
                'author': '@storyteller_pro',
                'published_at': '2024-08-13T13:00:00Z',
                'published_date': '2024-08-13',
                'duration': 58,
                'duration_formatted': '0:58',
                'view_count': 7300000,
                'like_count': 1200000,
                'url': 'https://www.tiktok.com/@storyteller_pro/video/7364829471234567895',
                'embed_url': 'https://www.tiktok.com/@storyteller_pro/video/7364829471234567895',
                'platform': 'tiktok',
                'uploader': '@storyteller_pro',
                'categories': ['comedy']
            },
            {
                'id': 'tiktok_trend_007',
                'title': 'Fashion haul that broke the internet 👗',
                'description': 'These outfits are everything! Links in bio for all items ✨ #fashion #haul #style #outfit #viral',
                'thumbnail': 'https://via.placeholder.com/300x400/f39c12/white?text=Fashion+Haul',
                'author': '@styleicon_',
                'published_at': '2024-08-14T08:30:00Z',
                'published_date': '2024-08-14',
                'duration': 38,
                'duration_formatted': '0:38',
                'view_count': 4200000,
                'like_count': 650000,
                'url': 'https://www.tiktok.com/@styleicon_/video/7364829471234567896',
                'embed_url': 'https://www.tiktok.com/@styleicon_/video/7364829471234567896',
                'platform': 'tiktok',
                'uploader': '@styleicon_',
                'categories': ['fashion']
            },
            {
                'id': 'tiktok_trend_008',
                'title': '30-second workout that actually works! 💪',
                'description': 'No gym needed! Do this every morning for amazing results 🔥 #workout #fitness #health #motivation',
                'thumbnail': 'https://via.placeholder.com/300x400/27ae60/white?text=Workout+Trend',
                'author': '@fit_coach_anna',
                'published_at': '2024-08-14T06:15:00Z',
                'published_date': '2024-08-14',
                'duration': 32,
                'duration_formatted': '0:32',
                'view_count': 5800000,
                'like_count': 890000,
                'url': 'https://www.tiktok.com/@fit_coach_anna/video/7364829471234567897',
                'embed_url': 'https://www.tiktok.com/@fit_coach_anna/video/7364829471234567897',
                'platform': 'tiktok',
                'uploader': '@fit_coach_anna',
                'categories': ['fitness']
            },
            {
                'id': 'tiktok_trend_009',
                'title': 'Art hack that will blow your mind! 🎨',
                'description': 'Turn ordinary objects into masterpieces! Save this tutorial 📌 #art #diy #creative #tutorial #viral',
                'thumbnail': 'https://via.placeholder.com/300x400/8e44ad/white?text=Art+Tutorial',
                'author': '@creative_artist',
                'published_at': '2024-08-13T19:45:00Z',
                'published_date': '2024-08-13',
                'duration': 47,
                'duration_formatted': '0:47',
                'view_count': 3900000,
                'like_count': 520000,
                'url': 'https://www.tiktok.com/@creative_artist/video/7364829471234567898',
                'embed_url': 'https://www.tiktok.com/@creative_artist/video/7364829471234567898',
                'platform': 'tiktok',
                'uploader': '@creative_artist',
                'categories': ['art']
            },
            {
                'id': 'tiktok_trend_010',
                'title': 'This song is stuck in EVERYONE\'s head 🎵',
                'description': 'The new viral sound that\'s taking over! Use this sound for your videos 🎶 #music #viral #trending #sound',
                'thumbnail': 'https://via.placeholder.com/300x400/e67e22/white?text=Viral+Song',
                'author': '@music_producer',
                'published_at': '2024-08-14T10:00:00Z',
                'published_date': '2024-08-14',
                'duration': 25,
                'duration_formatted': '0:25',
                'view_count': 18900000,
                'like_count': 4200000,
                'url': 'https://www.tiktok.com/@music_producer/video/7364829471234567899',
                'embed_url': 'https://www.tiktok.com/@music_producer/video/7364829471234567899',
                'platform': 'tiktok',
                'uploader': '@music_producer',
                'categories': ['music']
            }
        ]
    
    def _get_mock_youtube_search_data(self, query):
        """Mock YouTube search data when API is not available"""
        mock_data = self._get_mock_youtube_trending_data()
        # Modify titles to reflect search query
        for video in mock_data:
            video['title'] = f"[YT SEARCH: {query}] " + video['title']
        return mock_data
    
    def _get_mock_tiktok_search_data(self, query):
        """Mock TikTok search data"""
        mock_data = self._get_mock_tiktok_trending_data()
        # Modify titles to reflect search query
        for video in mock_data:
            video['title'] = f"[TT SEARCH: {query}] " + video['title']
        return mock_data

extractor = VideoFrameExtractor()
short_creator = ShortVideoCreator()
trending_tracker = TrendingVideosTracker()

@app.route('/api/test-platform', methods=['POST'])
def test_platform_compatibility():
    """Test platform compatibility and provide specific guidance"""
    try:
        data = request.get_json()
        url = data.get('url', '').strip()
        
        if not url:
            return jsonify({'error': 'URL is required'})
        
        platform = extractor.get_platform_from_url(url)
        
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
        return jsonify({'error': str(e)})

@app.route('/api/validate-url', methods=['POST'])
def validate_url():
    """Validate and get basic info about a URL without downloading"""
    try:
        data = request.get_json()
        url = data.get('url', '').strip()
        
        if not url:
            return jsonify({'valid': False, 'error': 'URL is required'})
        
        # Check if URL is from supported platforms
        if not extractor.is_valid_url(url):
            return jsonify({
                'valid': False, 
                'error': 'Unsupported platform. Please use URLs from YouTube, TikTok, Facebook, Douyin, or Instagram.'
            })
        
        # Get platform info
        platform = extractor.get_platform_from_url(url)
        
        # Try to extract basic info without downloading
        try:
            with yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True}) as ydl:
                info = ydl.extract_info(url, download=False)
                
                if isinstance(info, dict):
                    return jsonify({
                        'valid': True,
                        'platform': platform,
                        'title': info.get('title', 'Unknown'),
                        'duration': info.get('duration', 0),
                        'uploader': info.get('uploader', 'Unknown'),
                        'view_count': info.get('view_count', 0)
                    })
        except Exception as e:
            print(f"Info extraction error: {e}")
            
        # If info extraction fails, still return valid platform
        return jsonify({
            'valid': True,
            'platform': platform,
            'note': 'URL is valid but full info extraction failed'
        })
            
    except Exception as e:
        return jsonify({'valid': False, 'error': str(e)})

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

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/extract', methods=['POST'])
def extract_frames():
    try:
        data = request.get_json()
        print(f"Request data type: {type(data)}")
        print(f"Request data: {data}")
        
        if not isinstance(data, dict):
            return jsonify({'error': f'Invalid request data type: {type(data)}'}), 400
        
        url = data.get('url', '').strip()
        timestamps = data.get('timestamps', [])
        
        print(f"URL: {url}")
        print(f"Timestamps: {timestamps}")
        
        if not url:
            return jsonify({'error': 'URL is required'}), 400
        
        if not timestamps:
            return jsonify({'error': 'At least one timestamp is required'}), 400
        
        # Validate URL
        if not extractor.is_valid_url(url):
            return jsonify({'error': 'URL must be from YouTube or TikTok'}), 400
        
        # Clean up old files (optional)
        cleanup_old_files()
        
        print("Starting video download...")
        # Download video
        video_path, title = extractor.download_video(url)
        print(f"Download result: path={video_path}, title={title}")
        
        if not video_path:
            return jsonify({'error': 'Failed to download video'}), 500
        
        # Extract frames
        frames, error = extractor.extract_frames_at_times(video_path, timestamps)
        
        # Clean up downloaded video
        if os.path.exists(video_path):
            os.remove(video_path)
        
        if error:
            return jsonify({'error': error}), 500
        
        return jsonify({
            'success': True,
            'title': title,
            'frames': frames,
            'total_extracted': len(frames)
        })
        
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"Full error trace: {error_trace}")
        return jsonify({'error': f'Server error: {str(e)}', 'trace': error_trace}), 500

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
        import traceback
        error_trace = traceback.format_exc()
        print(f"Test endpoint error: {error_trace}")
        return jsonify({'error': f'Test error: {str(e)}', 'trace': error_trace}), 500

@app.route('/frames/<filename>')
def serve_frame(filename):
    return send_from_directory(FRAMES_FOLDER, filename)

@app.route('/api/cleanup', methods=['POST'])
def cleanup_frames():
    try:
        cleanup_old_files(force=True)
        return jsonify({'success': True, 'message': 'Cleanup completed'})
    except Exception as e:
        return jsonify({'error': f'Cleanup failed: {str(e)}'}), 500

@app.route('/api/create-short', methods=['POST'])
def create_short_video():
    """Create a short video from a longer video"""
    try:
        data = request.get_json()
        print(f"Short video request data: {data}")
        
        if not isinstance(data, dict):
            return jsonify({'error': f'Invalid request data type: {type(data)}'}), 400
        
        url = data.get('url', '').strip()
        start_time = data.get('start_time', 0)  # in seconds
        duration = data.get('duration', 30)  # default 30 seconds
        
        # Validate required fields
        if not url:
            return jsonify({'error': 'URL is required'}), 400
        
        # Validate URL
        if not extractor.is_valid_url(url):
            return jsonify({'error': 'URL must be from YouTube or TikTok'}), 400
        
        # Parse start_time if it's a string (e.g., "1:30")
        if isinstance(start_time, str):
            start_time = extractor.parse_timestamp(start_time)
            if start_time is None:
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
        
        print(f"Creating short video - URL: {url}, Start: {start_time}s, Duration: {duration}s")
        
        # Clean up old files
        cleanup_old_files()
        
        # Download video
        video_path, title = extractor.download_video(url)
        print(f"Downloaded video: {video_path}, title: {title}")
        
        if not video_path:
            return jsonify({'error': 'Failed to download video'}), 500
        
        # Get video info
        video_info = short_creator.get_video_info(video_path)
        if not video_info:
            return jsonify({'error': 'Failed to analyze video'}), 500
        
        print(f"Video info: {video_info}")
        
        # Validate start_time against video duration
        if start_time >= video_info['duration']:
            return jsonify({'error': f'Start time ({start_time}s) exceeds video duration ({video_info["duration"]:.1f}s)'}), 400
        
        # Adjust duration if it exceeds video length
        max_duration = video_info['duration'] - start_time
        if duration > max_duration:
            duration = max_duration
            print(f"Adjusted duration to {duration}s to fit video length")
        
        # Generate unique filename for short video
        short_id = str(uuid.uuid4())[:8]
        sanitized_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).rstrip()
        output_name = f"{sanitized_title}_{short_id}_short"
        
        # Create short video
        output_path, error = short_creator.create_short_video(
            video_path, start_time, duration, output_name, options
        )
        
        # Clean up original video
        if os.path.exists(video_path):
            os.remove(video_path)
        
        if error:
            return jsonify({'error': error}), 500
        
        if not output_path or not os.path.exists(output_path):
            return jsonify({'error': 'Failed to create short video'}), 500
        
        # Get file size
        file_size = os.path.getsize(output_path)
        
        return jsonify({
            'success': True,
            'short_video': {
                'filename': os.path.basename(output_path),
                'title': title,
                'start_time': start_time,
                'duration': duration,
                'file_size': file_size,
                'original_duration': video_info['duration'],
                'options_applied': options
            }
        })
        
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"Error creating short video: {error_trace}")
        return jsonify({'error': f'Server error: {str(e)}', 'trace': error_trace}), 500

@app.route('/api/video-info', methods=['POST'])
def get_video_info():
    """Get information about a video without downloading it"""
    try:
        data = request.get_json()
        url = data.get('url', '').strip()
        
        if not url:
            return jsonify({'error': 'URL is required'}), 400
        
        if not extractor.is_valid_url(url):
            return jsonify({'error': 'URL must be from YouTube or TikTok'}), 400
        
        # Get video info using yt-dlp
        import yt_dlp
        ydl_opts = {'noplaylist': True}
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
        if not isinstance(info, dict):
            return jsonify({'error': 'Failed to get video information'}), 500
        
        return jsonify({
            'success': True,
            'video_info': {
                'title': info.get('title', 'Unknown'),
                'duration': info.get('duration', 0),
                'description': info.get('description', '')[:200] + '...' if info.get('description') else '',
                'view_count': info.get('view_count', 0),
                'uploader': info.get('uploader', 'Unknown'),
                'upload_date': info.get('upload_date', ''),
                'thumbnail': info.get('thumbnail', ''),
                'webpage_url': info.get('webpage_url', url)
            }
        })
        
    except Exception as e:
        return jsonify({'error': f'Failed to get video info: {str(e)}'}), 500

@app.route('/shorts/<filename>')
def serve_short_video(filename):
    """Serve generated short videos"""
    return send_from_directory(SHORTS_FOLDER, filename)

@app.route('/api/trending', methods=['GET'])
def get_trending_videos():
    """Get trending videos from YouTube or TikTok"""
    try:
        platform = request.args.get('platform', 'youtube').lower()
        region = request.args.get('region', 'US')
        category = request.args.get('category', None)
        max_results = int(request.args.get('max_results', 20))
        
        videos, error = trending_tracker.get_trending_videos(
            platform=platform,
            region_code=region,
            category_id=category if platform == 'youtube' else None,
            max_results=max_results,
            category=category if platform == 'tiktok' else None
        )
        
        return jsonify({
            'success': True,
            'platform': platform,
            'videos': videos,
            'total': len(videos),
            'warning': error if error else None
        })
        
    except Exception as e:
        return jsonify({'error': f'Failed to get trending videos: {str(e)}'}), 500

@app.route('/api/search', methods=['POST'])
def search_videos():
    """Search for videos on YouTube or TikTok"""
    try:
        data = request.get_json()
        query = data.get('query', '').strip()
        platform = data.get('platform', 'youtube').lower()
        max_results = data.get('max_results', 10)
        
        if not query:
            return jsonify({'error': 'Search query is required'}), 400
        
        videos, error = trending_tracker.search_videos(
            query=query,
            platform=platform,
            max_results=max_results
        )
        
        return jsonify({
            'success': True,
            'platform': platform,
            'videos': videos,
            'total': len(videos),
            'query': query,
            'warning': error if error else None
        })
        
    except Exception as e:
        return jsonify({'error': f'Failed to search videos: {str(e)}'}), 500

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
            {'id': '28', 'name': 'Science & Technology'},
        ]
        
        return jsonify({
            'success': True,
            'categories': categories
        })
        
    except Exception as e:
        return jsonify({'error': f'Failed to get categories: {str(e)}'}), 500

def cleanup_old_files(force=False):
    """Clean up old downloaded videos, extracted frames, and generated shorts"""
    try:
        # Clean downloads folder
        for file in os.listdir(DOWNLOAD_FOLDER):
            file_path = os.path.join(DOWNLOAD_FOLDER, file)
            if os.path.isfile(file_path):
                os.remove(file_path)
        
        # Clean frames folder (only if force or files are old)
        if force:
            for file in os.listdir(FRAMES_FOLDER):
                file_path = os.path.join(FRAMES_FOLDER, file)
                if os.path.isfile(file_path):
                    os.remove(file_path)
            
            # Clean shorts folder when force cleanup
            for file in os.listdir(SHORTS_FOLDER):
                file_path = os.path.join(SHORTS_FOLDER, file)
                if os.path.isfile(file_path):
                    os.remove(file_path)
        else:
            # Remove files older than 1 hour
            import time
            current_time = time.time()
            
            # Clean old frames
            for file in os.listdir(FRAMES_FOLDER):
                file_path = os.path.join(FRAMES_FOLDER, file)
                if os.path.isfile(file_path):
                    file_age = current_time - os.path.getctime(file_path)
                    if file_age > 3600:  # 1 hour
                        os.remove(file_path)
            
            # Clean old short videos (keep for 24 hours)
            for file in os.listdir(SHORTS_FOLDER):
                file_path = os.path.join(SHORTS_FOLDER, file)
                if os.path.isfile(file_path):
                    file_age = current_time - os.path.getctime(file_path)
                    if file_age > 86400:  # 24 hours
                        os.remove(file_path)
                        
    except Exception as e:
        print(f"Cleanup error: {str(e)}")

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
