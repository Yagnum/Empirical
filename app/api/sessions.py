"""Which trading window is it right now? (ADR-019)

Every hour of the week has exactly one execution path:

    premarket    Mon-Fri 4:00 AM - 9:30 AM ET    Alpaca, limit + extended_hours
    regular      Mon-Fri 9:30 AM - 4:00 PM ET    Alpaca, any order type
    afterhours   Mon-Fri 4:00 PM - 8:00 PM ET    Alpaca, limit + extended_hours
    overnight    Sun-Thu 8:00 PM - 4:00 AM ET    orders queue at Alpaca until
                                                 4:00 AM premarket (24/5 is not
                                                 executable in the sandbox -
                                                 ADR-024)
    weekend      Fri 8:00 PM - Sun 8:00 PM ET    the ERR engine (Jupiter price,
                                                 reserve, escrow, Monday hedge)

Jupiter is never used for execution while any regulated session is open.

MARKET HOLIDAYS (ADR-021). A holiday belongs to the ERR engine, exactly
like a weekend: no venue is open, and the overnight session that would
trade *into* a holiday is closed too. The trading days come from Alpaca's
calendar endpoint, cached for a day; if the calendar cannot be fetched at
all, the router falls back to pure weekday arithmetic - the pre-ADR-021
behaviour, in which a holiday order harmlessly queues at the broker.
KNOWN LIMIT: early-close days (1:00 PM closes around Thanksgiving and
Christmas) are still routed as full days; an afternoon order then queues
instead of routing to the engine.

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

import alpaca
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


# The trading-day calendar, fetched once per day. Holding yesterday's copy
# through an Alpaca outage beats having none: holidays are known months out.
_calendar_cache: tuple[dt.date, frozenset[dt.date]] | None = None


def _trading_days() -> frozenset[dt.date] | None:
    """The trading dates around today, or None when they cannot be known."""
    global _calendar_cache
    today = dt.datetime.now(ET).date()
    if _calendar_cache and _calendar_cache[0] == today:
        return _calendar_cache[1]
    try:
        rows = alpaca.get_calendar(
            (today - dt.timedelta(days=7)).isoformat(),
            (today + dt.timedelta(days=30)).isoformat(),
        )
    except alpaca.AlpacaError:
        return _calendar_cache[1] if _calendar_cache else None
    days = frozenset(
        dt.date.fromisoformat(str(row["date"])) for row in rows if row.get("date")
    )
    if not days:
        return _calendar_cache[1] if _calendar_cache else None
    _calendar_cache = (today, days)
    return days


def _is_trading_day(day: dt.date, trading_days: frozenset[dt.date] | None) -> bool:
    # Unknown calendar: assume every weekday trades - the pre-ADR-021
    # behaviour, in which a holiday order queues harmlessly at the broker.
    if trading_days is None:
        return day.weekday() < 5
    return day in trading_days


def scheduled_session(
    now: dt.datetime | None = None,
    *,
    trading_days: frozenset[dt.date] | None = None,
) -> str:
    """The session the calendar dictates, ignoring any dev override.

    `now` must be timezone-aware; it defaults to the current UTC moment.
    `trading_days` is for tests; by default Alpaca's calendar is consulted
    (cached daily) so market holidays route to the weekend engine.
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
        session, owner = PREMARKET, moment.date()
    elif _REGULAR_START <= clock < _REGULAR_END:
        session, owner = REGULAR, moment.date()
    elif _REGULAR_END <= clock < _AFTER_END:
        session, owner = AFTERHOURS, moment.date()
    elif clock >= _AFTER_END:
        # 8 PM - midnight: this overnight session trades INTO tomorrow, so
        # tomorrow is the day that must be a trading day (Sunday 8 PM opens
        # the week only because Monday trades - and does not before a
        # holiday Monday).
        session, owner = OVERNIGHT, moment.date() + dt.timedelta(days=1)
    else:
        # Midnight - 4 AM: the tail of the overnight session, owned by today.
        session, owner = OVERNIGHT, moment.date()

    days = trading_days if trading_days is not None else _trading_days()
    if not _is_trading_day(owner, days):
        return WEEKEND
    return session


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
