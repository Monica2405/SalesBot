from datetime import date, time

import pytest

from salesbot_core.text.when import ClockTime, bare_number, parse_when

# Monday 7 January 2030
TODAY = date(2030, 1, 7)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("today", TODAY),
        ("aaj", TODAY),
        ("tomorrow", date(2030, 1, 8)),
        ("kal", date(2030, 1, 8)),
        ("कल", date(2030, 1, 8)),
        ("udya", date(2030, 1, 8)),
        ("उद्या", date(2030, 1, 8)),
        ("day after tomorrow", date(2030, 1, 9)),
        ("parso", date(2030, 1, 9)),
        ("परवा", date(2030, 1, 9)),
        # A weekday name is the nearest such day, today included.
        ("monday", TODAY),
        ("wednesday", date(2030, 1, 9)),
        ("शुक्रवार", date(2030, 1, 11)),
        ("shanivar", date(2030, 1, 12)),
        ("next monday", date(2030, 1, 14)),
        ("agle somvar", date(2030, 1, 14)),
        ("पुढच्या सोमवारी", date(2030, 1, 14)),
        ("26 jan", date(2030, 1, 26)),
        ("26th january", date(2030, 1, 26)),
        ("jan 26", date(2030, 1, 26)),
        ("26/1", date(2030, 1, 26)),
        ("26-01-2030", date(2030, 1, 26)),
        # Passed this year: next year.
        ("5 jan", date(2031, 1, 5)),
        ("3/1", date(2031, 1, 3)),
        ("26 tarikh", date(2030, 1, 26)),
        # The 3rd has passed this month: next month.
        ("3 tarikh", date(2030, 2, 3)),
        ("२६ जनवरी", date(2030, 1, 26)),
    ],
)
def test_days(text, expected):
    assert parse_when(text, TODAY).day == expected


def test_next_week_lists_from_next_monday():
    when = parse_when("next week", TODAY)
    assert when.day is None
    assert when.from_day == date(2030, 1, 14)
    assert not when.empty


def test_invalid_date_is_ignored():
    assert parse_when("31/2", TODAY).day is None


@pytest.mark.parametrize(
    ("text", "candidates"),
    [
        ("11:30", [time(11, 30), time(23, 30)]),
        ("11:30 am", [time(11, 30)]),
        ("5 pm", [time(17, 0)]),
        ("5pm", [time(17, 0)]),
        ("17:00", [time(17, 0)]),
        ("12 baje", [time(12, 0)]),
        ("5 baje", [time(5, 0), time(17, 0)]),
        ("११ बजे", [time(11, 0), time(23, 0)]),
        ("10 vajta", [time(10, 0), time(22, 0)]),
        ("sakali 10", [time(10, 0)]),
        ("sham 5 baje", [time(17, 0)]),
        ("संध्याकाळी 6 वाजता", [time(18, 0)]),
        ("dopahar 2 baje", [time(14, 0)]),
        ("dupari 12", [time(12, 0)]),
        ("sade 10", [time(10, 30), time(22, 30)]),
        ("sava 10", [time(10, 15), time(22, 15)]),
        ("paune 10", [time(9, 45), time(21, 45)]),
        ("साडे दहा", [time(10, 30), time(22, 30)]),
        ("dedh baje", [time(1, 30), time(13, 30)]),
        ("das baje", [time(10, 0), time(22, 0)]),
        ("noon", [time(12, 0)]),
    ],
)
def test_times(text, candidates):
    when = parse_when(text, TODAY)
    assert when.time is not None
    assert when.time.candidates() == candidates


def test_day_and_time_together():
    when = parse_when("kal sakali 11 baje", TODAY)
    assert when.day == date(2030, 1, 8)
    assert when.time == ClockTime(11, 0, None, "morning")
    assert when.time.candidates() == [time(11, 0)]
    # The part of day is folded into the time.
    assert when.part is None


def test_part_of_day_without_time():
    when = parse_when("kal sham", TODAY)
    assert when.day == date(2030, 1, 8)
    assert when.time is None
    assert when.part == "evening"


def test_date_digits_are_not_a_time():
    when = parse_when("26 jan", TODAY)
    assert when.day == date(2030, 1, 26)
    assert when.time is None
    assert parse_when("26/1", TODAY).time is None
    assert parse_when("26 tarikh", TODAY).time is None


def test_date_and_time():
    when = parse_when("26 jan 5 pm", TODAY)
    assert when.day == date(2030, 1, 26)
    assert when.time is not None and when.time.candidates() == [time(17, 0)]


def test_lone_number_is_an_option_not_a_time():
    assert parse_when("2", TODAY).empty
    assert parse_when("2", TODAY, bare_number_is_time=True).time == ClockTime(2, 0)
    # Next to a day it is a time.
    assert parse_when("tomorrow 11", TODAY).time == ClockTime(11, 0)


def test_number_words_need_a_time_cue():
    # "do" (two) is also an everyday Hindi word: no cue, no time.
    assert parse_when("kar do", TODAY).empty
    assert parse_when("do baje", TODAY).time == ClockTime(2, 0)


def test_nothing_found():
    assert parse_when("hello there", TODAY).empty
    assert parse_when("", TODAY).empty


@pytest.mark.parametrize(
    ("text", "expected"), [("2", 2), (" 3 ", 3), ("२", 2), ("10", 10), ("2 pm", None), ("", None)]
)
def test_bare_number(text, expected):
    assert bare_number(text) == expected
