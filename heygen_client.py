"""HeyGen video generation client.

Provides methods to:
- Create a digital avatar from an image
- Generate lip-sync video from text/audio
- Poll for completion and return the MP4 URL
"""

import os
import time
import json
import logging
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

BASE_URL = "https://api.heygen.com/v3"


def _request(method: str, path: str, api_key: str, json_payload: Optional[Dict] = None, params: Optional[Dict] = None) -> Dict[str, Any]:
    url = f"{BASE_URL}{path}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    resp = requests.request(method, url, headers=headers, json=json_payload, params=params, timeout=30)
    if resp.status_code == 400:
        try:
            data = resp.json()
            print("HeyGen 400 Error response:", json.dumps(data, indent=2, ensure_ascii=False))
        except Exception:
            print("HeyGen 400 Error response (non-JSON):", resp.text[:500])
        return resp.json()
    resp.raise_for_status()
    return resp.json()


class HeyGenClient:
    def __init__(self, api_key: Optional[str] = None, base_url: str = BASE_URL) -> None:
        self.api_key = api_key or os.getenv("HEYGEN_API_KEY")
        if not self.api_key:
            raise ValueError("HEYGEN_API_KEY not set")
        self.base_url = base_url

    def create_avatar(self, avatar_image_url: str, name: str = "proos_avatar") -> Dict[str, Any]:
        """Create a photo avatar from a URL."""
        payload = {
            "type": "photo",
            "name": name,
            "file": {
                "type": "url",
                "url": avatar_image_url,
            },
        }
        return _request("POST", "/avatars", self.api_key, json_payload=payload)

    def create_video(self, avatar_id: str, audio_url: str, text: str) -> Dict[str, Any]:
        """Submit a video generation job with avatar + audio."""
        payload = {
            "avatar_id": avatar_id,
            "audio_url": audio_url,
            "text": text,
        }
        return _request("POST", "/videos", self.api_key, json_payload=payload)

    def poll_video(self, video_id: str, max_wait: int = 300, poll_interval: int = 10) -> Dict[str, Any]:
        """Poll until video is ready or max_wait seconds elapse."""
        start = time.time()
        while time.time() - start < max_wait:
            data = _request("GET", f"/videos/{video_id}", self.api_key)
            status = data.get("status", "")
            if status in ("completed", "succeeded"):
                return data
            if status in ("failed", "error"):
                raise RuntimeError(f"Heygen video generation failed: {data}")
            time.sleep(poll_interval)
        raise TimeoutError(f"Heygen video generation timed out after {max_wait}s, video_id={video_id}")

    def generate_from_text(
        self,
        avatar_image_url: str,
        text: str,
        audio_url: str,
        avatar_name: str = "DefaultAvatar",
        max_wait: int = 300,
    ) -> Dict[str, Any]:
        """Full pipeline: create avatar (if needed) → generate video → poll."""
        # 1) Create avatar from image
        avatar_resp = self.create_avatar(avatar_image_url, name=avatar_name)
        avatar_id = avatar_resp.get("data", {}).get("avatar_id") or avatar_resp.get("avatar_id")
        if not avatar_id:
            raise RuntimeError(f"Could not get avatar_id from create_avatar response: {avatar_resp}")

        # 2) Submit video generation
        video_resp = self.create_video(avatar_id, audio_url, text)
        video_id = video_resp.get("data", {}).get("video_id") or video_resp.get("video_id")
        if not video_id:
            raise RuntimeError(f"Could not get video_id from create_video response: {video_resp}")

        # 3) Poll for completion
        final = self.poll_video(video_id, max_wait=max_wait)
        return final


if __name__ == "__main__":
    # Minimal CLI: just print config check
    client = HeyGenClient()
    print("HeyGen client initialized. base_url=", client.base_url)
    print("HEYGEN_API_KEY set:", bool(client.api_key))