import requests
import json

def test_video_info():
    try:
        url = "http://127.0.0.1:5000/api/video-info"
        data = {"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}
        
        print("🧪 Testing video info API...")
        response = requests.post(url, json=data, timeout=30)
        print(f"Status: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            print("✅ Success!")
            print(f"Title: {result['video_info']['title']}")
            print(f"Duration: {result['video_info']['duration']}s")
            print(f"Views: {result['video_info']['view_count']}")
        else:
            print("❌ Failed!")
            print(f"Response: {response.text}")
            
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    test_video_info()
