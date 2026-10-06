"""
Nightly run:  python graph.py
Start it ~10 PM; it sends the Telegram report at 11 PM Pakistan time.

open_portal -> saved_search(tomorrow) -> collect_lots -> process_lots -> report
"""
import asyncio
import os
import traceback
from datetime import datetime
from typing import TypedDict
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from langgraph.graph import END, StateGraph
from playwright.async_api import async_playwright

load_dotenv()

import notify                                   # noqa: E402
import portal                                   # noqa: E402
import store                                    # noqa: E402
from car_agent import process_lot               # noqa: E402

PKT = ZoneInfo("Asia/Karachi")
REPORT_AT_HOUR = 23
MIN_CREDITS = 10                                # stop clicking GET IMAGES below this

CTX: dict = {}                                  # browser objects (not stored in graph state)


class State(TypedDict, total=False):
    day: str
    lots: list
    prefiltered: int
    results: list
    credits: int


# ---------------- Nodes ----------------
async def n_search(state: State) -> State:
    CTX["credits"] = await portal.read_image_credits(CTX["page"])
    if os.getenv("MODE", "auto") == "attach":
        await CTX["page"].go_back()              # back to your search results
    day = await portal.run_saved_search(CTX["page"])
    return {"day": day or "", "credits": CTX["credits"]}


async def n_collect(state: State) -> State:
    if not state["day"]:
        return {"lots": [], "prefiltered": 0}
    lots = [l for l in await portal.collect_lots(CTX["page"]) if not store.is_seen(l["url"])]
    keep, skipped = [], 0
    for lot in lots:
        if portal.prefilter(lot):
            skipped += 1
            store.mark_seen(lot["url"], "prefiltered")
        else:
            keep.append(lot)
    return {"lots": keep, "prefiltered": skipped}


async def n_process(state: State) -> State:
    results, credits = [], state.get("credits")
    lot_page = await CTX["context"].new_page()
    oliac_page = await CTX["context"].new_page()

    for lot in state["lots"]:                    # one at a time, on purpose
        can_click = credits is None or credits > MIN_CREDITS
        try:
            r = await process_lot(lot_page, oliac_page, lot,
                                  portal.SELECTORS["sheet_image"], can_click)
        except Exception as e:
            r = {**lot, "decision": "manual", "reasons": [f"error: {e}"]}
        if r.get("used_credit") and credits is not None:
            credits -= 1
        results.append(r)
        if r["decision"] != "manual":            # manual lots are retried tomorrow
            store.mark_seen(lot["url"], r["decision"])
        await portal.pause()
    return {"results": results, "credits": credits}


async def n_report(state: State) -> State:
    # Wait until 11 PM Pakistan time if we finished early
    now = datetime.now(PKT)
    target = now.replace(hour=REPORT_AT_HOUR, minute=0, second=0, microsecond=0)
    if now < target:
        await asyncio.sleep((target - now).total_seconds())

    if not state["day"]:
        notify.send_text("No auctions tomorrow.")
        return {}
    res = state.get("results", [])
    notify.send_report(
        day=state["day"],
        passed=[r for r in res if r["decision"] == "pass"],
        manual=[r for r in res if r["decision"] == "manual"],
        rejected=sum(r["decision"] == "reject" for r in res),
        credits_left=state.get("credits"),
        prefiltered=state.get("prefiltered", 0),
    )
    if state.get("credits") is not None and state["credits"] <= MIN_CREDITS:
        notify.send_text(f"⚠️ Only {state['credits']} image credits left. "
                         "USS lots are now sent to manual check until you top up.")
    return {}


def build_graph():
    g = StateGraph(State)
    g.add_node("search", n_search)
    g.add_node("collect", n_collect)
    g.add_node("process", n_process)
    g.add_node("report", n_report)
    g.set_entry_point("search")
    g.add_edge("search", "collect")
    g.add_edge("collect", "process")
    g.add_edge("process", "report")
    g.add_edge("report", END)
    return g.compile()


async def main():
    async with async_playwright() as pw:
        try:
            CTX["browser"], CTX["context"], CTX["page"] = await portal.open_portal(pw)
            await build_graph().ainvoke({})
        except Exception as e:
            traceback.print_exc()
            notify.send_error(f"{type(e).__name__}: {e}")
        finally:
            if os.getenv("MODE", "auto") != "attach" and CTX.get("browser"):
                await CTX["browser"].close()


if __name__ == "__main__":
    asyncio.run(main())
