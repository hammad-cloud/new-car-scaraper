"""Sends the nightly result to your Telegram."""
import html
import os

import httpx

API = "https://api.telegram.org/bot{token}/{method}"


def _call(method: str, **kwargs) -> None:
    url = API.format(token=os.environ["TELEGRAM_BOT_TOKEN"], method=method)
    r = httpx.post(url, timeout=60, **kwargs)
    r.raise_for_status()


def send_text(text: str) -> None:
    for i in range(0, len(text), 3900):                  # Telegram limit ~4096 chars
        _call("sendMessage", data={"chat_id": os.environ["TELEGRAM_CHAT_ID"],
                                   "text": text[i:i + 3900], "parse_mode": "HTML"})


def send_photo(png: bytes, caption: str) -> None:
    _call("sendPhoto", data={"chat_id": os.environ["TELEGRAM_CHAT_ID"],
                             "caption": caption[:1000], "parse_mode": "HTML"},
          files={"photo": ("sheet.png", png, "image/png")})


def car_line(r: dict) -> str:
    e = lambda v: html.escape(str(v)) if v is not None else "?"
    return (f"<b>Lot {e(r.get('lot_number'))}</b> · {e(r.get('auction'))}\n"
            f"Chassis: {e(r.get('chassis'))} · OLIAC year: {e(r.get('oliac_year'))}\n"
            f"Colour: {e(r.get('colour_code'))} · {e(r.get('mileage_km'))} km · "
            f"Grade {e(r.get('grade'))} · {e(r.get('grade_name'))}\n"
            f"{r['url']}")


def send_report(day: str, passed: list, manual: list, rejected: int,
                credits_left, prefiltered: int) -> None:
    head = (f"🚗 <b>Mira e:S auction report – {html.escape(day)}</b>\n"
            f"✅ Passed: {len(passed)}   ⚠️ Manual check: {len(manual)}   "
            f"❌ Rejected: {rejected + prefiltered}\n"
            f"🖼 Image credits left: {credits_left if credits_left is not None else '?'}")
    send_text(head)

    for r in passed:                                     # each passed car with its sheet
        send_photo(r["sheet_png"], "✅ " + car_line(r))

    if manual:
        body = "⚠️ <b>Needs manual check</b>\n\n" + "\n\n".join(
            car_line(r) + "\nWhy: " + html.escape("; ".join(r["reasons"])) for r in manual)
        send_text(body)

    if not passed and not manual:
        send_text("No matching cars tonight.")


def send_error(msg: str) -> None:
    send_text(f"🔴 <b>Car agent failed</b>\n{html.escape(msg)}")
