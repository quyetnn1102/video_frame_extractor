import yt_dlp
import json

# Test multiple URLs
urls = [
    'https://www.youtube.com/watch?v=y3GDWwWnKlc',
    'https://www.youtube.com/watch?v=dQw4w9WgXcQ'  # Rick Roll - a stable test video
]

for url in urls:
    try:
        ydl_opts = {
            'format': 'best[height<=720]',
            'noplaylist': True,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            print(f"\nTesting URL: {url}")
            info = ydl.extract_info(url, download=False)
            
            print(f"Info type: {type(info)}")
            
            if isinstance(info, dict):
                print(f"Title: {info.get('title', 'No title')}")
                print(f"Duration: {info.get('duration', 'Unknown')}")
                print("✅ Success")
            else:
                print(f"❌ Info is not a dict. Content: {str(info)[:200]}...")
                
    except Exception as e:
        print(f"❌ Error with {url}: {e}")
        import traceback
        traceback.print_exc()
