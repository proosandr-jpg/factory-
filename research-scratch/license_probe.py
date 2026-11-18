"""Scratch: fetch specific license/config artifacts and print the decisive lines."""
import re
import urllib.request

TARGETS = [
    ("piper COPYING", "https://raw.githubusercontent.com/OHF-voice/piper1-gpl/main/COPYING", 6),
    ("cosyvoice LICENSE", "https://raw.githubusercontent.com/FunAudioLLM/CosyVoice/main/LICENSE", 6),
    ("fish LICENSE", "https://raw.githubusercontent.com/fishaudio/fish-speech/main/LICENSE", 40),
    ("silero models.yml", "https://raw.githubusercontent.com/snakers4/silero-models/master/models.yml", 0),
]

for name, url, head in TARGETS:
    print(f"\n########## {name}")
    try:
        txt = urllib.request.urlopen(url, timeout=40).read().decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001
        print("ERR", type(exc).__name__, exc)
        continue
    lines = txt.splitlines()
    if head:
        for ln in lines[:head]:
            if ln.strip():
                print("|", ln.strip()[:200])
    if name.startswith("fish"):
        for i, ln in enumerate(lines):
            if re.search(r"commercial|non-commercial|research", ln, re.I):
                print(f"L{i}: {ln.strip()[:300]}")
    if name.startswith("silero"):
        cur = None
        for ln in lines:
            m = re.match(r"^\s{2}(\w[\w-]*):\s*$", ln)
            if m:
                cur = m.group(1)
            if re.search(r"v5_ru|v4_ru|v5_cis_base", ln) and len(ln.strip()) < 300:
                print(f"[{cur}] {ln.strip()[:200]}")
        for ln in lines:
            if re.search(r"\.pt|size|bytes", ln, re.I) and len(ln.strip()) < 200:
                print("SIZE?", ln.strip()[:200])
