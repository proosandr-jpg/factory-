import json
import urllib.request


def probe(pkg, ver=None):
    base = f"https://pypi.org/pypi/{pkg}" + (f"/{ver}" if ver else "") + "/json"
    d = json.load(urllib.request.urlopen(base, timeout=60))
    files = d["urls"] if ver else d["releases"][d["info"]["version"]]
    names = [f["filename"] for f in files]
    cp313 = [n for n in names if "cp313" in n]
    win = [n for n in cp313 if "win" in n.lower()]
    return d["info"]["version"], d["info"].get("requires_python"), len(names), cp313[:4], win[:4]


for p in [
    "torch",
    "torchaudio",
    "torchcodec",
    "vocos",
    "x-transformers",
    "torchdiffeq",
    "ema-pytorch",
    "pydantic",
    "gradio",
    "f5-tts",
    "coqui-tts",
    "TTS",
]:
    try:
        v, rp, n, cp, win = probe(p)
        print(f"{p}: version={v} requires_python={rp} files={n}")
        print(f"   cp313 sample={cp}")
        print(f"   cp313-win sample={win}")
    except Exception as e:  # noqa: BLE001
        print(f"{p}: ERROR {e}")
