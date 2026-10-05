import requests
import json

# Test the debug endpoint
url = "http://127.0.0.1:5000/api/test-ytdlp"
data = {"url": "https://www.youtube.com/watch?v=y3GDWwWnKlc"}

try:
    response = requests.post(url, json=data)
    print(f"Status Code: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
except Exception as e:
    print(f"Error: {e}")
