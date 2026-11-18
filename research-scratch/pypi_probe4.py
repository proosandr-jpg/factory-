import json
import urllib.request


def info(pkg):
    d = json.load(urllib.request.urlopen(f"https://pypi.org/pypi/{pkg}/json", timeout=90))
    v = d["info"]["version"]
    fs = d["releases"][v]
    names = [f["filename"] for f in fs]
    anyw = [n for n in names if n.endswith(".whl") and ("py3-none-any" in n or "py2.py3-none-any" in n)]
    cp313win = [n for n in names if "cp313" in n and "win_amd64" in n]
    pure = bool(anyw) and not any("cp3" in n for n in names)
    return v, d["info"].get("requires_python"), pure, cp313win[:2], len(names)


for p in [
    "bitsandbytes",
    "soundfile",
    "pydantic-core",
    "numpy",
    "scipy",
    "matplotlib",
    "cached-path",
    "vocos",
    "torchdiffeq",
    "ema-pytorch",
    "x-transformers",
    "hydra-core",
    "omegaconf",
    "rjieba",
    "pypinyin",
    "pydub",
    "unidecode",
    "tomli",
    "safetensors",
]:
    try:
        v, rp, pure, cp, n = info(p)
        kind = "pure-python" if pure else ("cp313-win ok" if cp else "NO cp313 win wheel")
        print(f"{p:16s} {v:10s} requires_python={str(rp):12s} {kind}")
    except Exception as e:  # noqa: BLE001
        print(f"{p:16s} ERROR {e}")
