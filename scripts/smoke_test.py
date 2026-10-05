"""
Manual smoke test against a running server.

    python app_enhanced.py                      # in one terminal
    python scripts/smoke_test.py                # in another

It calls the real API and makes yt-dlp download from the internet, so it is not
part of the unit tests (those run offline: python -m unittest discover -s tests -t .).
Pass --create-short to also render a short, which downloads and re-encodes video.
"""
import argparse
import sys

import requests

DEFAULT_BASE_URL = "http://127.0.0.1:5000"
DEFAULT_VIDEO_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
REQUEST_TIMEOUT_SECONDS = 60
RENDER_TIMEOUT_SECONDS = 600


def report(name: str, ok: bool, detail: str = "") -> bool:
    print(f"{'PASS' if ok else 'FAIL'}  {name}{'  - ' + detail if detail else ''}")
    return ok


def call(method: str, url: str, timeout: int = REQUEST_TIMEOUT_SECONDS, **kwargs):
    try:
        response = requests.request(method, url, timeout=timeout, **kwargs)
        return response, response.json()
    except (requests.RequestException, ValueError) as error:
        return None, {"error": type(error).__name__}


def run(base_url: str, video_url: str, create_short: bool) -> bool:
    results = []

    response, body = call("GET", f"{base_url}/api/health")
    results.append(report("health", bool(response) and body.get("status") == "healthy"))

    response, body = call("POST", f"{base_url}/api/validate-url", json={"url": video_url})
    results.append(report("validate-url", bool(response) and body.get("valid") is True,
                          body.get("title", body.get("error", ""))))

    response, body = call("POST", f"{base_url}/api/video-info", json={"url": video_url})
    info = body.get("video_info", {})
    results.append(report("video-info", bool(response) and response.ok and "title" in info,
                          f"{info.get('title', body.get('error', ''))}"))

    if create_short:
        request_body = {"url": video_url, "start_time": "0:05", "duration": 5,
                        "quality": "low", "vertical_format": True}
        response, body = call("POST", f"{base_url}/api/create-short",
                              timeout=RENDER_TIMEOUT_SECONDS, json=request_body)
        ok = bool(response) and body.get("success") is True
        results.append(report("create-short", ok, body.get("download_url", body.get("error", ""))))
        if ok:
            short = requests.get(f"{base_url}{body['download_url']}", timeout=REQUEST_TIMEOUT_SECONDS)
            results.append(report("serve-short", short.ok))

    return all(results)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--video-url", default=DEFAULT_VIDEO_URL)
    parser.add_argument("--create-short", action="store_true")
    arguments = parser.parse_args()
    return 0 if run(arguments.base_url.rstrip("/"), arguments.video_url, arguments.create_short) else 1


if __name__ == "__main__":
    sys.exit(main())
