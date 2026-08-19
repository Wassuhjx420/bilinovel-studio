import requests
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Referer": "https://www.bilinovel.com/novel/5131/316496.html"
}

for script in ["/scripts/zation.js?v1004a4", "/themes/zhmb/js/readtools.js?few8a0", "/scripts/common.js?v0922a3", "/themes/zhmb/js/chapterlog.js?v1006c1.82"]:
    url = f"https://www.bilinovel.com{script}"
    r = requests.get(url, headers=headers)
    fname = script.split("?")[0].split("/")[-1]
    with open(fname, "w", encoding="utf-8") as f:
        f.write(r.text)
    print(f"Saved {fname} ({len(r.text)} chars)")
