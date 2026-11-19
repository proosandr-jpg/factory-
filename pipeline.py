#!/usr/bin/python3
import argparse, os, sys
from typing import Optional
from heygen_client import HeyGenClient

def read_text_file(path):
    if not os.path.isfile(path):
        print("Error: text file not found: " + path, file=sys.stderr)
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()

def main():
    parser = argparse.ArgumentParser(description="HeyGen video generation pipeline")
    parser.add_argument("--video-engine", required=True, choices=["heygen"], help="Video generation engine")
    parser.add_argument("--heygen-audio-url", required=True, help="Public URL to the audio file (WAV/MP3)")
    parser.add_argument("--heygen-avatar-id", default=None, help="Existing HeyGen avatar_id")
    parser.add_argument("--avatar-image", default="assets/avatar.png", help="Path to avatar image")
    parser.add_argument("--text-file", required=True, help="Path to scenario text file")
    parser.add_argument("--avatar-name", default="DoctorAvatar", help="Name for new avatar")
    args = parser.parse_args()

    avatar_image_url = "https://qazimir.by/media/avatar.png"
    text = read_text_file(args.text_file)

    if args.video_engine == "heygen":
        client = HeyGenClient()
        avatar_id = args.heygen_avatar_id

        if not avatar_id:
            print("Creating HeyGen avatar from image URL: " + avatar_image_url + "...")
            avatar_resp = client.create_avatar(avatar_image_url, name=args.avatar_name)
            avatar_id = avatar_resp.get("data", {}).get("avatar_id") or avatar_resp.get("avatar_id")
            if not avatar_id:
                print("Error: Could not create avatar. Response: " + str(avatar_resp), file=sys.stderr)
                sys.exit(1)
            print("Avatar created. avatar_id=" + avatar_id)

        print("Generating HeyGen video with avatar_id=" + avatar_id + ", audio_url=" + args.heygen_audio_url + "...")
        video_resp = client.create_video(avatar_id, args.heygen_audio_url, text)

        video_id = video_resp.get("data", {}).get("video_id") or video_resp.get("video_id")
        if not video_id:
            print("Error: Could not get video_id. Response: " + str(video_resp), file=sys.stderr)
            sys.exit(1)

        print("Video generation started. video_id=" + video_id + ". Polling for completion (max 5 min)...")
        final = client.poll_video(video_id, max_wait=300, poll_interval=10)

        video_url = final.get("data", {}).get("video_url") or final.get("video_url") or final.get("status")
        print("HeyGen Video Generation Complete")
        print("Video ID: " + video_id)
        if video_url:
            print("Video URL: " + video_url)
        else:
            print("Full response: " + str(final))
        print("")

if __name__ == "__main__":
    main()
