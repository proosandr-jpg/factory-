import json
import urllib.request

for pkg in ["bitsandbytes", "rjieba", "safetensors", "torchaudio"]:
    d = json.load(urllib.request.urlopen(f"https://pypi.org/pypi/{pkg}/json", timeout=90))
    v = d["info"]["version"]
    names = [f["filename"] for f in d["releases"][v]]
    win = [n for n in names if "win" in n.lower()]
    print(f"== {pkg} {v} ({len(names)} files) win wheels:")
    for n in win[:12]:
        print("   ", n)
    if not win:
        print("    (none)", names[:6])
