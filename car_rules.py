"""
Auction sheet extraction + filter rules for the Mira e:S auction agent.

Flow per lot:  sheet image -> extract_sheet() -> decide() -> pass / reject / manual
Only "pass" lots go into the 11 PM alert; "manual" lots go in a separate section.
"""
import base64
import re
from typing import Literal, Optional

from pydantic import BaseModel, Field
from langchain_anthropic import ChatAnthropic

# ---------------- YOUR RULES ----------------
ALLOWED_COLOURS = {"W19", "W25", "S28"}            # white, pearl white, silver
ALLOWED_YEARS = {2023, 2024, 2025}
MIN_MILEAGE_KM = 2_000                              # below this = counted as a new car in Pakistan
MAX_MILEAGE_KM = 20_000                             # must be UNDER this
MIN_GRADE = 4.0                                     # 4, 4.5, 5, 6 (and S) pass
BANNED_MARKS = {"W1", "W2", "W3", "XX", "X1", "U3"} # any one = reject, no exceptions
REQUIRE_LIMITED = False                             # set True to also require the Limited grade


# ---------------- WHAT THE VISION LLM MUST RETURN ----------------
class SheetData(BaseModel):
    chassis_number: Optional[str] = Field(None, description="e.g. LA350S-0448211")
    first_reg_era: Optional[str] = Field(None, description="Reiwa year as written, e.g. 'R7'")
    mileage_km: Optional[int] = Field(None, description="走行 value converted to km")
    auction_grade: Optional[str] = Field(None, description="評価点 exactly as written: 4, 4.5, 5, 6, S, R, RA...")
    colour_code: Optional[str] = Field(None, description="カラーNo exactly as written, e.g. W19, W25, S28. Null if not clearly written")
    grade_name: Optional[str] = Field(None, description="グレード text, e.g. 'X SA III', 'X リミテッド SA III'")
    has_rear_wiper: Optional[bool] = Field(None, description="True if リアワイパー is written; False if clearly absent; null if unsure")
    has_back_camera: Optional[bool] = Field(None, description="True if バックカメラ or バックモニター is written; null if unsure")
    defect_marks: list[str] = Field(default_factory=list, description="Every damage code on the car diagram (展開図), e.g. A1, U2, W1, XX")
    diagram_readable: bool = Field(..., description="False if the car diagram is too blurry to read every mark")


EXTRACT_PROMPT = """You are reading a Japanese used-car auction sheet.
Extract the fields exactly as written. Do not guess.
- Colour code is in the カラーNo box (NOT the 色 name). Return null if not clearly written.
- Defect marks are ONLY the codes drawn on the car diagram. Never include the colour code there.
- Look for リアワイパー (rear wiper) and バックカメラ / バックモニター (back camera) anywhere on the sheet.
- If the diagram is blurry, set diagram_readable to false."""

import os

if os.getenv("LLM_PROVIDER", "anthropic").lower() == "google":
    from langchain_google_genai import ChatGoogleGenerativeAI      # uses GOOGLE_API_KEY
    _base = ChatGoogleGenerativeAI(model=os.getenv("GOOGLE_MODEL", "gemini-3.8-flash"))
else:
    _base = ChatAnthropic(model="claude-sonnet-5-5")              # uses ANTHROPIC_API_KEY

llm = _base.with_structured_output(SheetData)


def extract_sheet(image_bytes: bytes) -> SheetData:
    img = base64.b64encode(image_bytes).decode()
    mime = ("image/jpeg" if image_bytes[:3] == b"\xff\xd8\xff" else
            "image/webp" if image_bytes[8:12] == b"WEBP" else "image/png")
    return llm.invoke([
        {"role": "user", "content": [
            {"type": "text", "text": EXTRACT_PROMPT},
            {"type": "image", "source_type": "base64", "data": img, "mime_type": mime},
        ]}
    ])


# ---------------- HELPERS ----------------
def norm(code: str) -> str:
    """'w 1' -> 'W1', 'x x' -> 'XX'. Exact codes only, so W19 never matches W1."""
    return re.sub(r"\s+", "", code).upper()


def reiwa_to_year(era: Optional[str]) -> Optional[int]:
    m = re.fullmatch(r"R\s*(\d{1,2})", (era or "").strip().upper())
    return 2018 + int(m.group(1)) if m else None      # R5=2023, R6=2024, R7=2025


def grade_ok(grade: Optional[str]) -> Optional[bool]:
    if not grade:
        return None
    g = norm(grade)
    if g == "S":
        return True
    try:
        return float(g) >= MIN_GRADE
    except ValueError:
        return False                                  # R, RA, *** etc. = repaired/unknown -> reject


# ---------------- THE DECISION ----------------
Decision = Literal["pass", "reject", "manual"]


def decide(s: SheetData, oliac_year: Optional[int]) -> tuple[Decision, list[str]]:
    rejects, unsure = [], []

    # 1. Banned marks: reject no matter the mileage or condition
    found = {norm(m) for m in s.defect_marks} & BANNED_MARKS
    if found:
        rejects.append(f"banned marks on sheet: {sorted(found)}")
    if not s.diagram_readable:
        unsure.append("car diagram unreadable, can't confirm no W1/W2/W3/XX/X1/U3")

    # 2. Colour code must be clearly on the sheet
    colour = norm(s.colour_code) if s.colour_code else None
    if colour not in ALLOWED_COLOURS:
        rejects.append(f"colour code {colour or 'not clearly mentioned'}")

    # 3. Year: sheet (Reiwa) and OLIAC must both be 2023-2025
    sheet_year = reiwa_to_year(s.first_reg_era)
    for label, yr in (("sheet", sheet_year), ("OLIAC", oliac_year)):
        if yr is None:
            unsure.append(f"{label} year missing")
        elif yr not in ALLOWED_YEARS:
            rejects.append(f"{label} year {yr}")

    # 4. Mileage: 2,000 km or more (below = new car in Pakistan) and under 20,000 km
    if s.mileage_km is None:
        unsure.append("mileage unreadable")
    elif s.mileage_km < MIN_MILEAGE_KM:
        rejects.append(f"mileage {s.mileage_km:,} km is below 2,000 (counts as new car)")
    elif s.mileage_km >= MAX_MILEAGE_KM:
        rejects.append(f"mileage {s.mileage_km:,} km is 20,000 or more")

    # 5. Auction grade 4 and above
    g = grade_ok(s.auction_grade)
    if g is None:
        unsure.append("auction grade unreadable")
    elif not g:
        rejects.append(f"auction grade {s.auction_grade}")

    # 6. Rear wiper + back camera both required
    for label, val in (("rear wiper", s.has_rear_wiper), ("back camera", s.has_back_camera)):
        if val is False:
            rejects.append(f"no {label}")
        elif val is None:
            unsure.append(f"{label} not found on sheet, check photos")

    # 7. Optional: Limited grade
    if REQUIRE_LIMITED and not re.search(r"limited|リミテッド", s.grade_name or "", re.I):
        rejects.append(f"grade name '{s.grade_name}' is not Limited")

    if rejects:
        return "reject", rejects
    if unsure:
        return "manual", unsure
    return "pass", ["all rules passed"]