import requests
import json

# Test the new short video creation feature
def test_create_short():
    url = "http://127.0.0.1:5000/api/create-short"
    data = {
        "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",  # Rick Roll - stable test video
        "start_time": "0:30",
        "duration": 15,
        "quality": "medium",
        "vertical_format": True,
        "text_overlay": {
            "text": "Never Gonna Give You Up!",
            "position": "bottom",
            "fontsize": 40,
            "color": "white",
            "stroke_color": "black",
            "stroke_width": 2
        }
    }
    
    try:
        response = requests.post(url, json=data, timeout=300)  # 5 minute timeout
        print(f"Status Code: {response.status_code}")
        result = response.json()
        print(f"Response: {json.dumps(result, indent=2)}")
        
        if result.get('success'):
            print("✅ Short video created successfully!")
            filename = result['short_video']['filename']
            print(f"📹 Video file: {filename}")
            print(f"🔗 Access at: http://127.0.0.1:5000/shorts/{filename}")
        else:
            print("❌ Failed to create short video")
            
    except Exception as e:
        print(f"❌ Error: {e}")

def test_video_info():
    url = "http://127.0.0.1:5000/api/video-info"
    data = {"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}
    
    try:
        response = requests.post(url, json=data)
        print(f"\\nVideo Info Status Code: {response.status_code}")
        result = response.json()
        print(f"Video Info Response: {json.dumps(result, indent=2)}")
        
    except Exception as e:
        print(f"❌ Video Info Error: {e}")

if __name__ == "__main__":
    print("🧪 Testing Short Video Creator...")
    test_video_info()
    test_create_short()
