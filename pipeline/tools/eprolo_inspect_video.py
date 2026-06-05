#!/usr/bin/env python3
"""Discover product video(s) on EPROLO carousel.

Dumps:
  • <video> elements + their src / <source> children
  • data-* attributes that hold video URLs
  • inline JSON keys: video, videoUrl, video_url, mainVideo, media with mp4
  • any URL ending .mp4 / .webm / .mov in the page HTML
"""
import asyncio, os, re, sys, json
from pathlib import Path
try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except: pass
from dotenv import load_dotenv
from playwright.async_api import async_playwright
REPO = Path(__file__).resolve().parents[2]
load_dotenv(REPO / ".env", override=True)
STATE = os.environ.get("EPROLO_STATE_FILE")


async def go(url):
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True)
        c = await b.new_context(storage_state=STATE)
        page = await c.new_page()
        await page.goto(url, wait_until="networkidle", timeout=60_000)
        await page.wait_for_timeout(3500)

        print("=" * 60)
        print("1. <video> elements")
        print("=" * 60)
        vids = await page.query_selector_all('video')
        print(f"  {len(vids)} <video> elements")
        for i, v in enumerate(vids):
            src = await v.get_attribute('src')
            poster = await v.get_attribute('poster')
            sources = await v.query_selector_all('source')
            src_list = [await s.get_attribute('src') for s in sources]
            print(f"  [{i}] src={src} poster={(poster or '')[:50]}")
            for s in src_list:
                print(f"      <source>={s}")

        print("\n" + "=" * 60)
        print("2. data-* attrs with 'video' or .mp4")
        print("=" * 60)
        els = await page.query_selector_all('[class*="video"], [class*="Video"], [data-video], [class*="player"]')
        seen = set()
        for el in els[:15]:
            cls = await el.get_attribute('class') or ''
            tag = await el.evaluate('e => e.tagName')
            if cls in seen: continue
            seen.add(cls)
            print(f"  <{tag}> class='{cls[:70]}'")

        print("\n" + "=" * 60)
        print("3. Inline JSON video keys")
        print("=" * 60)
        html = await page.content()
        for pat_name, pat in [
            ("video_url", r'"video_?url"\s*:\s*"([^"]+)"'),
            ("videoUrl", r'"videoUrl"\s*:\s*"([^"]+)"'),
            ("video", r'"video"\s*:\s*"([^"]+\.(?:mp4|webm|mov)[^"]*)"'),
            ("mainVideo", r'"mainVideo"\s*:\s*"([^"]+)"'),
            ("videoList", r'"video_?list"\s*:\s*\[([^\]]{5,300})\]'),
            ("media_video", r'"media[^"]*"\s*:\s*"([^"]+\.mp4[^"]*)"'),
        ]:
            for m in re.finditer(pat, html, re.IGNORECASE):
                print(f"  [{pat_name}] {m.group(1)[:120]}")

        print("\n" + "=" * 60)
        print("4. Any *.mp4 / *.webm / *.mov URLs in HTML")
        print("=" * 60)
        media_urls = re.findall(r'https?://[^\s"\'<>\)]+\.(?:mp4|webm|mov)(?:\?[^\s"\'<>]*)?', html, re.IGNORECASE)
        media_urls = list(dict.fromkeys(media_urls))
        print(f"  {len(media_urls)} unique media URLs")
        for u in media_urls[:15]:
            print(f"    {u[:140]}")

        # Also try clicking carousel to reveal video (often first slide)
        print("\n" + "=" * 60)
        print("5. After clicking carousel thumbnails (look for video)")
        print("=" * 60)
        thumbs = await page.query_selector_all('[class*="thumb"], [class*="carousel"] img, [class*="swiper"] img')
        print(f"  {len(thumbs)} carousel thumbnails")
        for i, t in enumerate(thumbs[:6]):
            try:
                await t.click(timeout=2000)
                await page.wait_for_timeout(800)
                vids2 = await page.query_selector_all('video')
                for v in vids2:
                    src = await v.get_attribute('src')
                    srcs = [await s.get_attribute('src') for s in await v.query_selector_all('source')]
                    if src or any(srcs):
                        print(f"    thumb[{i}] click → video src={src} sources={srcs}")
            except Exception:
                pass

        await b.close()

asyncio.run(go(sys.argv[1]))
