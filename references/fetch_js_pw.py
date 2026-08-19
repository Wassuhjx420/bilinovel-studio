import sys
import os
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
profile_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".edge_profile")

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        user_data_dir=profile_dir,
        channel="msedge",
        headless=False,
        args=["--disable-blink-features=AutomationControlled"]
    )
    for script in ["/scripts/zation.js?v1004a4", "/themes/zhmb/js/readtools.js?few8a0", "/scripts/common.js?v0922a3", "/themes/zhmb/js/chapterlog.js?v1006c1.82"]:
        url = f"https://www.bilinovel.com{script}"
        resp = ctx.request.get(url, headers={"Referer": "https://www.bilinovel.com/novel/5131/316496.html"})
        fname = script.split("?")[0].split("/")[-1]
        with open(fname, "w", encoding="utf-8") as f:
            f.write(resp.text())
        print(f"Saved {fname} ({len(resp.text())} chars)")
    ctx.close()
