import hashlib
import urllib.request


def grab(url):
    with urllib.request.urlopen(url, timeout=90) as r:
        return r.read()


urls = {
    "ru_misha": "https://huggingface.co/Misha24-10/F5-TTS_RUSSIAN/resolve/main/F5TTS_v1_Base/vocab.txt",
    "base_swivid": "https://huggingface.co/SWivid/F5-TTS/resolve/main/F5TTS_v1_Base/vocab.txt",
}

data = {}
for k, u in urls.items():
    try:
        b = grab(u)
        data[k] = b
        txt = b.decode("utf-8")
        lines = [ln for ln in txt.splitlines() if ln]
        cyr = [c for c in lines if any("\u0400" <= ch <= "\u04FF" for ch in c)]
        print(f"{k}: bytes={len(b)} sha1={hashlib.sha1(b).hexdigest()[:12]} entries={len(lines)} cyrillic_entries={len(cyr)}")
        print("   cyrillic sample:", cyr[:15])
    except Exception as e:  # noqa: BLE001
        print(k, "ERROR", e)

if len(data) == 2:
    a, b = data["ru_misha"], data["base_swivid"]
    print("\nidentical:", a == b)
    if a != b:
        sa = set(a.decode("utf-8").splitlines())
        sb = set(b.decode("utf-8").splitlines())
        print("only in ru:", sorted(sa - sb)[:40])
        print("only in base:", sorted(sb - sa)[:40])
