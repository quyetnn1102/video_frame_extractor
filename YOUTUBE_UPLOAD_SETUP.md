# YouTube Upload Setup Guide

This guide will help you set up YouTube upload functionality for VideoExtract.

## Prerequisites

1. **Google Cloud Project**: You need a Google Cloud project with YouTube Data API v3 enabled
2. **OAuth2 Credentials**: Desktop application credentials for YouTube upload access
3. **Python Dependencies**: Install required YouTube API libraries

## Step 1: Create Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select existing one
3. Enable the **YouTube Data API v3**:
   - Go to APIs & Services > Library
   - Search for "YouTube Data API v3"
   - Click "Enable"

## Step 2: Create OAuth2 Credentials

1. Go to APIs & Services > Credentials
2. Click "Create Credentials" > "OAuth 2.0 Client ID"
3. Choose "Desktop application"
4. Name it (e.g., "VideoExtract YouTube Uploader")
5. Download the JSON file
6. Rename it to `client_secrets.json`
7. Place it in your project root directory

## Step 3: Install Dependencies

```bash
pip install google-api-python-client google-auth-oauthlib google-auth-httplib2
```

Or install from requirements.txt:
```bash
pip install -r requirements.txt
```

## Step 4: Configure OAuth2 Redirect URI

In your Google Cloud Console:
1. Go to APIs & Services > Credentials
2. Edit your OAuth 2.0 Client ID
3. Add these authorized redirect URIs:
   - `http://localhost:8080/oauth2callback`
   - `http://127.0.0.1:8080/oauth2callback`

## Step 5: Test the Setup

1. Start your Flask application
2. Go to the "Create Short" page
3. Create a short video
4. Click "Upload to YouTube" button
5. Complete OAuth2 authentication when prompted

## File Structure

Your project should have:
```
video_frame_extractor/
├── client_secrets.json          # Your OAuth2 credentials (don't commit!)
├── youtube_credentials.pickle   # Saved authentication (auto-created)
├── youtube_uploader.py         # YouTube upload module
└── app_enhanced.py            # Main Flask app with YouTube routes
```

## Important Notes

### Quota Limits
- YouTube Data API v3 has daily quota limits
- Default quota: 10,000 units/day
- Video upload costs ~1,600 units
- Maximum ~6 uploads per day with default quota

### Video Requirements for YouTube Shorts
- **Duration**: ≤ 60 seconds
- **Aspect Ratio**: Vertical (9:16) or Square (1:1)
- **File Size**: ≤ 256GB (we limit to 2GB)
- **Format**: MP4 recommended

### Privacy Settings
- Videos are uploaded as **Private** by default
- Users can change to Public/Unlisted in YouTube Studio
- This prevents accidental public uploads

### Security Best Practices
1. **Never commit `client_secrets.json`** to version control
2. Add `client_secrets.json` to `.gitignore`
3. Add `youtube_credentials.pickle` to `.gitignore`
4. Use environment variables for sensitive data in production

## Troubleshooting

### "Authentication Required" Error
- Delete `youtube_credentials.pickle` file
- Try authentication process again

### "Quota Exceeded" Error
- You've hit daily API limits
- Wait until quota resets (midnight PST)
- Consider requesting quota increase from Google

### "Invalid Credentials" Error
- Check `client_secrets.json` is valid
- Ensure OAuth2 redirect URIs are configured
- Verify YouTube Data API v3 is enabled

### "Video Validation Failed" Error
- Check video duration (≤60 seconds)
- Ensure vertical or square aspect ratio
- Verify file size (≤2GB)

## API Endpoints

The following endpoints are available:

- `GET /api/youtube-auth` - Check authentication status
- `POST /api/youtube-callback` - Handle OAuth2 callback
- `POST /api/upload-to-youtube` - Upload video to YouTube
- `GET /api/youtube-quota` - Get quota information

## Example Usage

```javascript
// Check if user is authenticated
const authStatus = await fetch('/api/youtube-auth');
const authData = await authStatus.json();

if (authData.authenticated) {
    // User is ready to upload
    const uploadResponse = await fetch('/api/upload-to-youtube', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            video_path: '/path/to/video.mp4',
            title: 'My Viral Short',
            description: 'Created with VideoExtract',
            tags: ['Shorts', 'Viral'],
            privacy: 'private'
        })
    });
}
```

## Support

For additional help:
1. Check Google's [YouTube API documentation](https://developers.google.com/youtube/v3)
2. Review [OAuth2 setup guide](https://developers.google.com/youtube/v3/guides/auth/installed-apps)
3. Test with [YouTube API Explorer](https://developers.google.com/youtube/v3/docs/videos/insert)
