"""Help cards, WP1 (the spec's §5, §13 *Logic, light*): why Surasura did something by itself — one `Cause` shape, one
time rule (`causes.when`), recorded where the work starts (the job registry's `cause`), and read by the phase strip.

What a wrong answer would cost a learner: a *Why:* that names the wrong trigger ("Surasura opened" for a sync you
didn't cause), a time from another day read as today's, a cause on a job they pressed themselves, or an ended job's
*Last:* line losing the reason it ran.
"""
import time

from app.services import causes, jobs, phase
from app.services.journey import why as journey_why


def _at(y, mo, d, h, mi):
    return time.mktime((y, mo, d, h, mi, 0, 0, 0, -1))


# --- the one time rule ---------------------------------------------------------------------------------------------- #
def test_when_writes_today_yesterday_older_and_none_in_their_own_words():
    now = _at(2026, 11, 6, 23, 40)
    assert causes.when(_at(2026, 11, 6, 14, 2), now) == "14:02"
    assert causes.when(_at(2026, 11, 5, 21, 14), now) == "yesterday 21:14"
    assert causes.when(_at(2026, 10, 30, 21, 14), now) == "Oct 30, 21:14"
    assert causes.when(_at(2026, 10, 3, 9, 5), now) == "Oct 3, 09:05"        # never "Oct 03"
    assert causes.when(None, now) == ""


def test_when_on_the_first_of_a_month_and_a_year_still_finds_yesterday():
    # (the day before 1 Nov is 31 Oct, before 1 Jan the year before: never "older" for last night)
    assert causes.when(_at(2026, 10, 31, 22, 0), _at(2026, 11, 1, 8, 0)) == "yesterday 22:00"
    assert causes.when(_at(2025, 12, 31, 23, 59), _at(2026, 1, 1, 0, 1)) == "yesterday 23:59"


def test_a_time_ahead_of_now_from_another_pcs_clock_reads_as_today():
    now = _at(2026, 11, 6, 9, 0)
    assert causes.when(_at(2026, 11, 7, 1, 0), now) == "01:00"


def test_said_is_one_line_with_its_time_and_carries_its_card():
    now = _at(2026, 11, 6, 23, 40)
    c = causes.Cause("you moved 葬送のフリーレン ep 3", _at(2026, 11, 6, 14, 2), "junban")
    assert causes.said(c, now) == "Why: you moved 葬送のフリーレン ep 3 · 14:02"
    assert causes.said(c._replace(at=None), now) == "Why: you moved 葬送のフリーレン ep 3"
    assert causes.said(None, now) == "" and causes.said(causes.Cause(""), now) == ""
    assert c.card == "junban"


# --- the registry ---------------------------------------------------------------------------------------------- #
def test_a_jobs_cause_defaults_to_none_and_survives_its_end():
    reg = jobs.JobRegistry()
    plain = reg.submit("indexer", "Indexing", start=lambda j: None, automatic=True)
    assert plain.view().cause is None                              # every existing caller: unchanged
    why = causes.Cause(causes.when.__name__, 1.0, "generate")
    job = reg.record("library-maintain", "Tidying your library", cause=why)
    assert job.view().cause == why
    job.finish(ok=True)
    ended = [v for v in reg.snapshot() if v.id == job.id][0]
    assert ended.state == jobs.DONE and ended.cause == why        # the strip's *Last:* reads it after the end


def test_an_old_jobview_with_no_cause_field_still_builds():
    # a test's or a caller's positional JobView without the new field: its default is None
    v = jobs.JobView(1, "anki-sync", "Updating known words from Anki", jobs.RUNNING, None, None, None, 0.0, None, True,
                     "detach", False, True)
    assert v.cause is None and v.needs is None


# --- the phase strip's rule ---------------------------------------------------------------------------------------- #
def _view(kind, cause=None, automatic=True, state=jobs.RUNNING, started=0.0, ended=None, label="Re-ordering Anki"):
    return jobs.JobView(7, kind, label, state, None, None, None, started, ended, automatic, "wait", False, True, None,
                        True, None, cause)


def test_the_strip_pairs_each_live_jobs_line_with_its_cause_and_a_users_job_has_none():
    why = causes.Cause("Generate ended, and Re-order after Generate is on", 100.0, "junban")
    got = phase.read([_view("junban", why)], now=50.0)
    assert got[phase.JUNBAN].why == (("Re-ordering Anki", why),)
    mine = phase.read([_view("junban", None, automatic=False)], now=50.0)
    assert mine[phase.JUNBAN].why == ()


def test_an_ended_jobs_cause_rides_on_its_last_line():
    why = causes.Cause("You came back to Surasura (at most once every 5 minutes)", 10.0, "known")
    done = _view("anki-sync", why, state=jobs.DONE, started=1.0, ended=20.0, label="Updating known words from Anki")
    last = phase.fold({}, [done])
    st = phase.read([], last=last, now=30.0)[phase.ANKI]
    assert st.last.state == "done" and st.last.cause == why


# --- the triggers -------------------------------------------------------------------------------------------------- #
def test_the_journeys_background_generate_names_its_newest_reason():
    at = _at(2026, 11, 6, 14, 2)
    assert journey_why(["store", "level"], at=at).line == "Your level changed"
    assert journey_why(["level", "stone"]).line == "You marked an episode watched"
    assert journey_why(["store"], deferred=True).line.startswith("Your journey catches up with your moves")
    assert journey_why(["store"], wanted=True).line.startswith("You asked for your journey")
    assert journey_why(["journey", "settled"]).line == "Your library changed"     # (looks name nothing)
    c = journey_why(["level"], at=at)
    assert c.at == at and c.card == "generate"
