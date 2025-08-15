"""
YouTube Video Upload Module
Handles uploading short videos directly to YouTube channel using YouTube Data API v3
"""
import os
import pickle
from typing import Dict, Any, Optional, Tuple
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from logger import app_logger

class YouTubeUploaderError(Exception):
    """Custom exception for YouTube upload errors"""
    pass

class YouTubeUploader:
    """
    Handles YouTube video uploads with OAuth2 authentication
    """
    
    # YouTube API settings
    YOUTUBE_UPLOAD_SCOPE = ["https://www.googleapis.com/auth/youtube.upload"]
    YOUTUBE_API_SERVICE_NAME = "youtube"
    YOUTUBE_API_VERSION = "v3"
    
    # YouTube Shorts requirements
    SHORTS_MAX_DURATION = 60  # seconds
    SHORTS_ASPECT_RATIOS = [(9, 16), (1, 1)]  # Vertical or square
    
    def __init__(self, client_secrets_file: str = "client_secrets.json"):
        """
        Initialize YouTube uploader
        
        Args:
            client_secrets_file: Path to OAuth2 client secrets JSON file
        """
        self.client_secrets_file = client_secrets_file
        self.credentials_file = "youtube_credentials.pickle"
        self.youtube_service = None
        
    def authenticate(self, redirect_uri: str = "http://localhost:8080/oauth2callback") -> Tuple[bool, str]:
        """
        Authenticate with YouTube using OAuth2
        
        Args:
            redirect_uri: OAuth2 redirect URI
            
        Returns:
            Tuple of (success, auth_url_or_error_message)
        """
        try:
            credentials = self._load_credentials()
            
            if not credentials or not credentials.valid:
                if credentials and credentials.expired and credentials.refresh_token:
                    # Refresh expired credentials
                    credentials.refresh(Request())
                    self._save_credentials(credentials)
                else:
                    # Start OAuth2 flow
                    flow = Flow.from_client_secrets_file(
                        self.client_secrets_file,
                        scopes=self.YOUTUBE_UPLOAD_SCOPE,
                        redirect_uri=redirect_uri
                    )
                    
                    auth_url, _ = flow.authorization_url(prompt='consent')
                    return False, auth_url
            
            self.youtube_service = build(
                self.YOUTUBE_API_SERVICE_NAME,
                self.YOUTUBE_API_VERSION,
                credentials=credentials
            )
            
            return True, "Authentication successful"
            
        except Exception as e:
            app_logger.error(f"YouTube authentication failed: {str(e)}")
            return False, f"Authentication failed: {str(e)}"
    
    def complete_auth(self, authorization_code: str, redirect_uri: str) -> Tuple[bool, str]:
        """
        Complete OAuth2 authentication with authorization code
        
        Args:
            authorization_code: Authorization code from OAuth2 callback
            redirect_uri: OAuth2 redirect URI
            
        Returns:
            Tuple of (success, message)
        """
        try:
            flow = Flow.from_client_secrets_file(
                self.client_secrets_file,
                scopes=self.YOUTUBE_UPLOAD_SCOPE,
                redirect_uri=redirect_uri
            )
            
            flow.fetch_token(code=authorization_code)
            credentials = flow.credentials
            
            self._save_credentials(credentials)
            
            self.youtube_service = build(
                self.YOUTUBE_API_SERVICE_NAME,
                self.YOUTUBE_API_VERSION,
                credentials=credentials
            )
            
            return True, "Authentication completed successfully"
            
        except Exception as e:
            app_logger.error(f"Failed to complete YouTube authentication: {str(e)}")
            return False, f"Authentication failed: {str(e)}"
    
    def upload_video(
        self,
        video_path: str,
        title: str,
        description: str = "",
        tags: list = None,
        category_id: str = "22",  # People & Blogs
        privacy_status: str = "private",
        is_short: bool = True
    ) -> Tuple[bool, str, Optional[str]]:
        """
        Upload video to YouTube
        
        Args:
            video_path: Path to video file
            title: Video title
            description: Video description
            tags: List of video tags
            category_id: YouTube category ID
            privacy_status: Video privacy (private, public, unlisted)
            is_short: Whether this is a YouTube Short
            
        Returns:
            Tuple of (success, message, video_id)
        """
        if not self.youtube_service:
            success, message = self.authenticate()
            if not success:
                return False, f"Authentication required: {message}", None
        
        if not os.path.exists(video_path):
            return False, f"Video file not found: {video_path}", None
        
        try:
            # Prepare video metadata
            if is_short:
                # Add #Shorts hashtag for YouTube Shorts
                if not description:
                    description = "Created with VideoExtract - AI-powered short video generator"
                if "#Shorts" not in description:
                    description = f"{description}\n\n#Shorts #VideoExtract #AIGenerated"
                
                # Add default tags for shorts
                if not tags:
                    tags = ["Shorts", "VideoExtract", "AI", "viral", "trending"]
            
            snippet = {
                "title": title[:100],  # YouTube title limit
                "description": description[:5000],  # YouTube description limit
                "tags": tags[:500] if tags else [],  # YouTube tags limit
                "categoryId": category_id
            }
            
            # Set video status
            status = {
                "privacyStatus": privacy_status,
                "selfDeclaredMadeForKids": False
            }
            
            # Create video resource
            body = {
                "snippet": snippet,
                "status": status
            }
            
            # Create media upload
            media = MediaFileUpload(
                video_path,
                chunksize=-1,
                resumable=True,
                mimetype="video/*"
            )
            
            # Execute upload
            insert_request = self.youtube_service.videos().insert(
                part=",".join(body.keys()),
                body=body,
                media_body=media
            )
            
            video_id = self._resumable_upload(insert_request)
            
            if video_id:
                video_url = f"https://www.youtube.com/watch?v={video_id}"
                app_logger.info(f"Video uploaded successfully: {video_url}")
                return True, f"Video uploaded successfully: {video_url}", video_id
            else:
                return False, "Upload failed - no video ID returned", None
                
        except HttpError as e:
            error_msg = f"YouTube API error: {e.resp.status} - {e.content.decode('utf-8')}"
            app_logger.error(error_msg)
            return False, error_msg, None
        except Exception as e:
            error_msg = f"Upload failed: {str(e)}"
            app_logger.error(error_msg)
            return False, error_msg, None
    
    def get_upload_quota_info(self) -> Dict[str, Any]:
        """
        Get YouTube API quota usage information
        
        Returns:
            Dictionary with quota information
        """
        # Note: YouTube API v3 has daily quotas
        # Default quota is 10,000 units per day
        # Video upload costs around 1600 units
        return {
            "daily_quota_limit": 10000,
            "upload_cost": 1600,
            "max_daily_uploads": 6,  # Conservative estimate
            "quota_reset": "Daily at midnight PST"
        }
    
    def validate_short_video(self, video_path: str) -> Tuple[bool, str]:
        """
        Validate if video meets YouTube Shorts requirements
        
        Args:
            video_path: Path to video file
            
        Returns:
            Tuple of (is_valid, message)
        """
        try:
            import cv2
            
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                return False, "Cannot open video file"
            
            # Get video properties
            fps = cap.get(cv2.CAP_PROP_FPS)
            frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            duration = frame_count / fps if fps > 0 else 0
            
            cap.release()
            
            # Check duration (YouTube Shorts must be ≤ 60 seconds)
            if duration > self.SHORTS_MAX_DURATION:
                return False, f"Video too long: {duration:.1f}s (max {self.SHORTS_MAX_DURATION}s)"
            
            # Check aspect ratio (should be vertical or square)
            aspect_ratio = width / height if height > 0 else 0
            is_vertical = height > width  # 9:16 or similar
            is_square = abs(aspect_ratio - 1.0) < 0.1  # Close to 1:1
            
            if not (is_vertical or is_square):
                return False, f"Invalid aspect ratio: {aspect_ratio:.2f} (should be vertical or square)"
            
            # File size check (YouTube limit is 256 GB, but we'll be more conservative)
            file_size = os.path.getsize(video_path)
            max_size = 2 * 1024 * 1024 * 1024  # 2GB limit
            if file_size > max_size:
                return False, f"File too large: {file_size / (1024*1024):.1f}MB (max 2GB)"
            
            return True, f"Valid YouTube Short: {duration:.1f}s, {width}x{height}"
            
        except Exception as e:
            return False, f"Validation error: {str(e)}"
    
    def _load_credentials(self) -> Optional[Credentials]:
        """Load saved credentials from file"""
        if os.path.exists(self.credentials_file):
            try:
                with open(self.credentials_file, 'rb') as f:
                    return pickle.load(f)
            except Exception as e:
                app_logger.warning(f"Failed to load credentials: {e}")
        return None
    
    def _save_credentials(self, credentials: Credentials) -> None:
        """Save credentials to file"""
        try:
            with open(self.credentials_file, 'wb') as f:
                pickle.dump(credentials, f)
        except Exception as e:
            app_logger.error(f"Failed to save credentials: {e}")
    
    def _resumable_upload(self, insert_request) -> Optional[str]:
        """
        Execute resumable upload with retry logic
        
        Args:
            insert_request: YouTube API insert request
            
        Returns:
            Video ID if successful, None otherwise
        """
        response = None
        retry = 0
        max_retries = 3
        
        while response is None:
            try:
                status, response = insert_request.next_chunk()
                if response is not None:
                    if 'id' in response:
                        return response['id']
                    else:
                        app_logger.error(f"Upload failed: {response}")
                        return None
            except HttpError as e:
                if e.resp.status in [500, 502, 503, 504]:
                    # Retry on server errors
                    retry += 1
                    if retry > max_retries:
                        app_logger.error(f"Max retries exceeded: {e}")
                        return None
                    
                    import time
                    time.sleep(2 ** retry)  # Exponential backoff
                else:
                    raise
            except Exception as e:
                app_logger.error(f"Unexpected error during upload: {e}")
                return None
        
        return None

# Global uploader instance
youtube_uploader = YouTubeUploader()
