"""Which trading window is it right now? (ADR-019)

Every hour of the week has exactly one execution path:

    premarket    Mon-Fri 4:00 AM - 9:30 AM ET    Alpaca, limit + extended_hours
    regular      Mon-Fri 9:30 AM - 4:00 PM ET    Alpaca, any order type
    afterhours   Mon-Fri 4:00 PM - 8:00 PM ET    Alpaca, limit + extended_hours
    overnight    Sun-Thu 8:00 PM - 4:00 AM ET    Alpaca 24/5 (Blue Ocean ATS),
                                                 limit only - pending the
                                                 sandbox test in ADR-019
    weekend      Fri 8:00 PM - Sun 8:00 PM ET    the ERR engine (Jupiter price,
                                                 reserve, escrow, Monday hedge)

Jupiter is never used for execution while any regulated session is open.

KNOWN LIMIT: market holidays are not modelled. On a holiday the schedule
says "regular" while Alpaca is closed, so an order queues at the broker
instead of routing to the ERR engine. Recorded as an open item in ADR-019.

THE DEV OVERRIDE. The weekend simulator is the real engine plus a fake
clock: a dev-only switch forces the session to "weekend" so the whole app
behaves as it will on a real Saturday - Jupiter quotes, reserve maths,
escrow journals - on a Tuesday afternoon. The override lives in process
memory (it is a development toggle, not state worth persisting) and every
entry point refuses it unless APP_ENV is "development".
"""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from config import settings

ET = ZoneInfo("America/New_York")

PREMARKET = "premarket"
REGULAR = "regular"
AFTERHOURS = "afterhours"
OVERNIGHT = "overnight"
WEEKEND = "weekend"

_PRE_START = dt.time(4, 0)
_REGULAR_START = dt.time(9, 30)
_REGULAR_END = dt.time(16, 0)
_AFTER_END = dt.time(20, 0)  # also the weekend boundary on Friday and Sunday


def scheduled_session(now: dt.datetime | None = None) -> str:
    """The session the calendar dictates, ignoring any dev override.

    `now` must be timezone-aware; it defaults to the current UTC moment.
    """
    moment = (now or dt.datetime.now(dt.timezone.utc)).astimezone(ET)
    weekday = moment.weekday()  # Monday = 0 ... Sunday = 6
    clock = moment.time()

    # The dead zone no regulated venue serves: Friday 8 PM to Sunday 8 PM ET.
    if weekday == 5:  # all of Saturday
        return WEEKEND
    if weekday == 4 and clock >= _AFTER_END:  # Friday evening
        return WEEKEND
    if weekday == 6 and clock < _AFTER_END:  # Sunday until 8 PM
        return WEEKEND

    if _PRE_START <= clock < _REGULAR_START:
        return PREMARKET
    if _REGULAR_START <= clock < _REGULAR_END:
        return REGULAR
    if _REGULAR_END <= clock < _AFTER_END:
        return AFTERHOURS
    # 8 PM - midnight and midnight - 4 AM on weeknights, Sunday 8 PM included.
    return OVERNIGHT


# ---------------------------------------------------------------------------
# The dev override (the weekend simulator's fake clock)
# ---------------------------------------------------------------------------

_simulate_weekend = False


def dev_override_allowed() -> bool:
    return settings.app_env == "development"


def set_weekend_override(on: bool) -> None:
    """Flip the simulator. Raises outside development - there is no
    production code path that may reach this."""
    if not dev_override_allowed():
        raise RuntimeError("the weekend override exists only in development")
    global _simulate_weekend
    _simulate_weekend = on


def weekend_override() -> bool:
    """True only in development with the switch on. In production this is
    False by construction, whatever the module-level flag says."""
    return _simulate_weekend if dev_override_allowed() else False


def effective_session(now: dt.datetime | None = None) -> dict:
    """What the app should act on: the scheduled session, unless the dev
    override forces "weekend".

    Returns {"session", "scheduled", "simulated"}; `simulated` is True only
    when the override is on and the calendar disagrees with it.
    """
    scheduled = scheduled_session(now)
    if weekend_override():
        return {
            "session": WEEKEND,
            "scheduled": scheduled,
            "simulated": scheduled != WEEKEND,
        }
    return {"session": scheduled, "scheduled": scheduled, "simulated": False}


def weekend_trading_active(now: dt.datetime | None = None) -> bool:
    """True when an order placed now belongs to the ERR engine, not Alpaca."""
    return effective_session(now)["session"] == WEEKEND
