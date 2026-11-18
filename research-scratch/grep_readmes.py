"""Scratch: grep raw README text from GitHub for specific claims (read-only research)."""
import re
import sys
import urllib.request

PAIRS = [
    ("torch-pypi", "https://pypi.org/pypi/torch/json"),  # handled separately
    ("chatterbox", "https://raw.githubusercontent.com/resemble-ai/chatterbox/master/README.md"),
    ("f5tts", "https://raw.githubusercontent.com/SWivid/F5-TTS/main/README.md"),
    ("fish", "https://raw.githubusercontent.com/fishaudio/fish-speech/main/README.md"),
    ("cosyvoice", "https://raw.githubusercontent.com/FunAudioLLM/CosyVoice/main/README.md"),
]

PAT = re.compile(r"russian|ru\b|license|licence|commercial|cpu|python 3|language", re.I)

for name, url in PAIRS:
    if name == "torch-pypi":
        continue
    print(f"\n########## {name}: {url}")
    try:
        txt = urllib.request.urlopen(url, timeout=40).read().decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001
        print("ERR", type(exc).__name__, exc)
        continue
    seen = set()
    for i, line in enumerate(txt.splitlines()):
        s = line.strip()
        if not s or s.startswith("![") or s.startswith("[!["):
            continue
        if PAT.search(s) and len(s) < 400:
            key = s[:80]
            if key in seen:
                continue
            seen.add(key)
            print(f"L{i}: {s[:380]}")
