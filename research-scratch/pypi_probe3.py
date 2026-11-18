import json
import urllib.request

d = json.load(urllib.request.urlopen("https://pypi.org/pypi/f5-tts/1.1.22/json", timeout=60))
i = d["info"]
print("version:", i["version"])
print("requires_python:", i["requires_python"])
print("upload:", d["urls"][0]["upload_time_iso_8601"] if d["urls"] else None)
print("deps:", i["requires_dist"])

d2 = json.load(urllib.request.urlopen("https://pypi.org/pypi/coqui-tts/json", timeout=60))
i2 = d2["info"]
print("\ncoqui-tts:", i2["version"], "requires_python:", i2["requires_python"], "license:", i2["license"])
print("classifiers py:", [c for c in i2["classifiers"] if "Python :: 3." in c])
print("deps subset:", [x for x in (i2["requires_dist"] or []) if "torch" in x.lower() or "spacy" in x.lower()])
print("upload:", d2["urls"][0]["upload_time_iso_8601"] if d2["urls"] else None)
