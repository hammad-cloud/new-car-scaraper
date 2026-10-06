"""
Everything that touches auc.alubaidmotors.com.

MODE=auto   -> agent logs in itself and runs the saved search (fully automatic)
MODE=attach -> you log in + run the saved search in Chrome, agent takes over that window

!! All selectors marked TODO must be checked with:
   playwright codegen https://auc.alubaidmotors.com
"""
import os
import random
import re
from pathlib import Path
from typing import Optional

from playwright.async_api import Browser, BrowserContext, Page, Playwright

from car_agent import select_auction_day

BASE = "https://auc.alubaidmotors.com"
SESSION_FILE = Path("session.json")          # saved login, reused every night

SELECTORS = {
    # --- login (checked 2026-10-05; the form exists twice on the page, hence :visible) ---
    "login_user": "input[name='username']:visible",
    "login_pass": "#auth_passwd:visible",
    "login_submit": "input.ajneo3:visible",
    "login_form": "#auth_passwd:visible",     # visible = logged OUT ('logout' text is always in the page, hidden)
    # --- saved search page ---
    "saved_search_btn": "text=DAIHATSU MIRA E S",
    # --- results table (checked 2026-10-05) ---
    "result_row": "tr[id^='aj_view']:has(a.my_bids)",     # aj_view00 is the header row
    "row_lot_link": "a.my_bids[href^='aj-']",
    "next_page": "a[title='forward']",
    # --- lot page (TODO) ---
    "sheet_image": "img.table_main2_500",
    "cookie_accept": "#acceptCookies",
}

# Colour NAMES from the results list that can never be W19 / W25 / S28.
# Lots with these are skipped BEFORE spending a GET IMAGES credit.
NEVER_OK_COLOURS = ("RED", "WINE", "BLUE", "BLACK", "BROWN", "GREEN", "YELLOW",
                    "ORANGE", "PINK", "PURPLE", "BEIGE", "GOLD", "IVORY")


async def pause(min_s: float = 5, max_s: float = 10) -> None:
    """Human-like pause between page actions."""
    import asyncio
    await asyncio.sleep(random.uniform(min_s, max_s))


# ---------------- Getting a browser page on the portal ----------------
async def open_portal(pw: Playwright) -> tuple[Browser, BrowserContext, Page]:
    mode = os.getenv("MODE", "auto")

    if mode == "attach":
        # Start Chrome yourself with:  chrome.exe --remote-debugging-port=9222
        browser = await pw.chromium.connect_over_cdp("http://localhost:9222")
        context = browser.contexts[0]
        page = next(p for p in context.pages if "alubaidmotors" in p.url)
        return browser, context, page

    browser = await pw.chromium.launch(headless=os.getenv("HEADLESS", "1") == "1")
    context = await browser.new_context(
        storage_state=str(SESSION_FILE) if SESSION_FILE.exists() else None)
    page = await context.new_page()
    await page.goto(BASE)
    await page.wait_for_load_state("networkidle")
    if await page.locator(SELECTORS["cookie_accept"]).is_visible():   # banner covers the auction sheet
        await page.click(SELECTORS["cookie_accept"])

    if await page.locator(SELECTORS["login_form"]).count() > 0:
        await page.fill(SELECTORS["login_user"], os.environ["PORTAL_USER"])
        await page.fill(SELECTORS["login_pass"], os.environ["PORTAL_PASS"])
        await page.click(SELECTORS["login_submit"])
        await page.wait_for_load_state("networkidle")
        await page.wait_for_timeout(3000)
        if await page.locator(SELECTORS["login_form"]).count() > 0:
            raise RuntimeError("Login failed")
        await context.storage_state(path=str(SESSION_FILE))   # log in once, reuse after
    return browser, context, page


# ---------------- Image credits ----------------
async def read_image_credits(page: Page) -> Optional[int]:
    await page.goto(f"{BASE}/my")
    await page.wait_for_load_state("networkidle")
    m = re.search(r"IMAGES-CLEAR\s*(\d+)", await page.inner_text("body"), re.I)
    return int(m.group(1)) if m else None


# ---------------- Saved search + tomorrow's day ----------------
async def run_saved_search(page: Page) -> Optional[str]:
    """Returns the day selected (e.g. 'TUE'), or None if no auctions tomorrow."""
    if os.getenv("MODE", "auto") == "attach":
        return "selected by you"                  # you already did this part

    await page.goto(f"{BASE}/search")
    await pause()
    # The button opens a new tab (target=_blank), so open its link in this tab instead
    href = await page.locator(SELECTORS["saved_search_btn"]).first.get_attribute("href")
    await page.goto(href if href.startswith("http") else f"{BASE}/{href.lstrip('/')}")
    await page.wait_for_load_state("networkidle")
    await pause()
    return await select_auction_day(page)


# ---------------- Collect lots from all result pages ----------------
def parse_row_text(text: str) -> dict:
    t = " ".join(text.split())
    year = re.search(r"\b(20[12]\d)\s+LA3\d0S", t)
    auction = re.search(r"(USS [A-Za-z ]+?|TAA [A-Za-z]+|CAA [A-Za-z]+|JU [A-Za-z]+|"
                        r"HAA [A-Za-z]+|ARAI [A-Za-z ]+?|AUCNET|BAYAUC|Honda AA [A-Za-z]+|"
                        r"LUM [A-Za-z]+(?: Nyusatsu)?|ORIX [A-Za-z]+(?: Nyusatsu)?)"
                        r"(?=\s|$)", t)
    return {
        "row_text": t,
        "year": int(year.group(1)) if year else None,
        "auction": auction.group(1).strip() if auction else "UNKNOWN",
    }


async def collect_lots(page: Page, max_pages: int = 30) -> list[dict]:
    lots, seen_urls = [], set()
    for _ in range(max_pages):
        before = len(lots)
        rows = page.locator(SELECTORS["result_row"])
        for i in range(await rows.count()):
            row = rows.nth(i)
            link = row.locator(SELECTORS["row_lot_link"]).first
            href = await link.get_attribute("href")
            if not href:
                continue
            url = href if href.startswith("http") else f"{BASE}/{href.lstrip('/')}"
            if url in seen_urls:
                continue
            seen_urls.add(url)
            lots.append({"url": url, "lot_number": (await link.inner_text()).strip(),
                         **parse_row_text(await row.inner_text())})

        nxt = page.locator(SELECTORS["next_page"])
        if len(lots) == before or await nxt.count() == 0:   # no new lots = last page
            break
        await nxt.first.click()
        await page.wait_for_load_state("networkidle")
        await pause()
    return lots


# ---------------- Cheap pre-filter (no image credit spent) ----------------
def prefilter(lot: dict) -> Optional[str]:
    """Returns a reject reason, or None if the lot should be opened."""
    # Year is NOT checked here: the list's year column can differ from the sheet
    # (your saved search already filters 2023-2025; the sheet + OLIAC decide).
    t = lot["row_text"].upper()
    for c in NEVER_OK_COLOURS:
        if re.search(rf"\b{c}\b", t) and not re.search(r"\b(WHITE|PEARL|SILVER)\b", t):
            return f"colour {c.lower()}"
    return None
