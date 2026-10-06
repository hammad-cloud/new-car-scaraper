"""
Per-lot steps for the auction agent. Uses the rules in car_rules.py.

Order for every lot (nothing is reported until step 4 is done):
  1. USS lot? -> click GET IMAGES, wait at least 60 s for all images
  2. Save the auction sheet image
  3. Vision LLM reads the sheet (chassis number, colour code, marks...)
  4. Chassis number -> OLIAC -> manufacture year   (ALWAYS, before any result)
  5. decide() -> pass / reject / manual
"""
import asyncio
import re
from typing import Optional

from playwright.async_api import Page

from car_rules import SheetData, decide, extract_sheet

USS_IMAGE_WAIT_MS = 60_000        # minimum wait after clicking GET IMAGES
OLIAC_URL = "https://oliac.com/autos/"


# ---------- Step 0: pick TOMORROW's auctions (left-side day buttons) ----------
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

DAY_CODES = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]


def target_auction_day(now: Optional[datetime] = None) -> str:
    """Pakistan date + 1. Monday 11 PM -> 'TUE', Tuesday 11 PM -> 'WED'.
    Uses Pakistan time, NOT the portal's Tokyo clock: at 11 PM in Pakistan it is
    already 3 AM next day in Tokyo, so Tokyo date + 1 would skip a day."""
    now = now or datetime.now(ZoneInfo("Asia/Karachi"))
    return DAY_CODES[(now + timedelta(days=1)).weekday()]


async def select_auction_day(page: Page) -> Optional[str]:
    """Clicks tomorrow's day button. Returns None if that day has no auctions."""
    day = target_auction_day()
    btn = page.get_by_text(day, exact=True).first      # adjust if needed
    if await btn.count() == 0:
        return None                                    # e.g. no Sunday button -> no auctions
    await btn.click()
    await page.wait_for_load_state("networkidle")
    return day


# ---------- Step 1: USS images ----------
async def load_uss_images(page: Page) -> None:
    await page.click("text=GET IMAGES")
    await page.wait_for_timeout(USS_IMAGE_WAIT_MS)       # never less than 1 minute

    # After the minute, keep waiting until the image count stops changing
    last = -1
    for _ in range(12):                                  # up to 1 extra minute
        count = await page.locator("img").count()
        if count == last:
            break
        last = count
        await page.wait_for_timeout(5_000)


# ---------- Step 4: OLIAC year check ----------
async def get_oliac_year(page: Page, chassis: str) -> Optional[int]:
    """Returns the manufacture year from OLIAC, or None if not found."""
    await page.goto(OLIAC_URL, wait_until="domcontentloaded")
    await page.locator("#searchInput").wait_for(state="visible")
    before = set((await page.inner_text("body")).splitlines())

    await page.fill("#searchInput", chassis)
    await page.click("#searchBtn")
    await page.wait_for_timeout(5_000)

    # Only read NEW text, so the page's own "1984 TO 2025" banner is ignored
    after = (await page.inner_text("body")).splitlines()
    new_text = " ".join(line for line in after if line not in before)

    years = re.findall(r"\b(19[89]\d|20[0-3]\d)\b", new_text)
    return int(years[0]) if years else None


# ---------- One lot, start to finish ----------
async def process_lot(lot_page: Page, oliac_page: Page, lot: dict,
                      sheet_selector: str, can_use_image_credit: bool) -> dict:
    # Don't wait for every photo to load (can take >30 s); the sheet image is all we need
    await lot_page.goto(lot["url"], wait_until="domcontentloaded", timeout=60_000)
    await lot_page.locator(sheet_selector).first.wait_for(state="visible", timeout=60_000)

    # 1. USS lots need the green button + at least 1 minute wait (costs 1 image credit)
    used_credit = False
    if "USS" in lot["auction"].upper():
        if not can_use_image_credit:
            return {**lot, "decision": "manual", "used_credit": False,
                    "reasons": ["image credits low, open this USS lot by hand"]}
        await load_uss_images(lot_page)
        used_credit = True

    # 2. Auction sheet image
    # Download the original (800x800 JPEG); an element screenshot comes out blank while it lazy-loads
    src = await lot_page.locator(sheet_selector).first.get_attribute("src")
    resp = await lot_page.context.request.get(src)
    if not resp.ok:
        raise RuntimeError(f"auction sheet download failed: HTTP {resp.status}")
    sheet_bytes = await resp.body()

    # 3. Read the sheet
    sheet: SheetData = extract_sheet(sheet_bytes)
    base = {**lot, "used_credit": used_credit, "sheet_png": sheet_bytes,
            "chassis": sheet.chassis_number, "colour_code": sheet.colour_code,
            "mileage_km": sheet.mileage_km, "grade": sheet.auction_grade,
            "grade_name": sheet.grade_name}

    # 4. OLIAC check is mandatory before any result
    if not sheet.chassis_number:
        return {**base, "decision": "manual",
                "reasons": ["chassis number unreadable, OLIAC check not possible"]}

    oliac_year = await get_oliac_year(oliac_page, sheet.chassis_number)
    await asyncio.sleep(3)                                # be gentle with OLIAC

    if oliac_year is None:
        return {**base, "decision": "manual", "reasons": ["OLIAC returned no year, check by hand"]}

    # 5. Apply all your rules (colour, year, mileage, grade, wiper, camera, banned marks)
    decision, reasons = decide(sheet, oliac_year)
    return {**base, "decision": decision, "oliac_year": oliac_year, "reasons": reasons}
