import json
import urllib.request


def files(pkg, ver=None):
    base = f"https://pypi.org/pypi/{pkg}" + (f"/{ver}" if ver else "") + "/json"
    d = json.load(urllib.request.urlopen(base, timeout=60))
    fs = d["urls"] if ver else d["releases"][d["info"]["version"]]
    return d["info"]["version"], [f["filename"] for f in fs]


for pkg in ["torchaudio"]:
    v, names = files(pkg)
    print(f"== {pkg} {v}")
    for n in names:
        print("  ", n)

# find newest torchaudio release that ships a cp313 win_amd64 wheel
d = json.load(urllib.request.urlopen("https://pypi.org/pypi/torchaudio/json", timeout=60))
hits = []
for ver, fs in d["releases"].items():
    for f in fs:
        fn = f["filename"]
        if "cp313" in fn and "win_amd64" in fn:
            hits.append((f["upload_time_iso_8601"], ver, fn))
hits.sort()
print("\n== torchaudio cp313 win_amd64 total:", len(hits))
for h in hits[-6:]:
    print("  ", h)

# same for torch, to know the range
d = json.load(urllib.request.urlopen("https://pypi.org/pypi/torch/json", timeout=60))
hits = []
for ver, fs in d["releases"].items():
    for f in fs:
        fn = f["filename"]
        if "cp313" in fn and "win_amd64" in fn:
            hits.append((f["upload_time_iso_8601"], ver))
hits.sort()
print("\n== torch cp313 win_amd64 total:", len(hits), "first:", hits[0] if hits else None, "last:", hits[-1] if hits else None)
