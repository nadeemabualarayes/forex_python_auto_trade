import pandas as pd

from candles import add_patterns


def frame(rows):
    """rows: list of (open, high, low, close); a flat 10-bar prelude fixes the average body."""
    prelude = [(100, 101, 99, 100.5)] * 10
    df = pd.DataFrame(prelude + rows, columns=["open", "high", "low", "close"])
    df["atr"] = 1.0
    return add_patterns(df)


def last(rows):
    df = frame(rows)
    return df["bull_pattern"].iloc[-1], df["bear_pattern"].iloc[-1]


class TestSingleBar:
    def test_doji(self):
        assert last([(100.5, 102.0, 99.0, 100.55)]) == ("doji", "doji")     # wide range, hairline body

    def test_hammer_is_bullish_and_hanging_man_is_bearish(self):
        assert last([(100.0, 100.1, 98.0, 100.05)]) == ("hammer", "hanging_man")   # tiny body, long lower wick

    def test_shooting_star(self):
        assert last([(100.0, 102.0, 99.9, 99.95)]) == ("inverted_hammer", "shooting_star")

    def test_plain_bar_has_no_pattern(self):
        assert last([(100, 101, 99, 100.8)]) == ("", "")


class TestTwoBar:
    def test_bullish_engulfing(self):
        assert last([(101, 101.2, 99.8, 100), (99.9, 101.6, 99.7, 101.5)])[0] == "bullish_engulfing"

    def test_bearish_engulfing(self):
        assert last([(100, 101.2, 99.8, 101), (101.1, 101.4, 99.3, 99.5)])[1] == "bearish_engulfing"

    def test_bullish_harami_and_cross(self):
        assert last([(102, 102.2, 98.8, 99), (100, 100.6, 99.6, 100.4)])[0] == "bullish_harami"
        assert last([(102, 102.2, 98.8, 99), (100, 100.6, 99.6, 100.02)])[0] == "bullish_harami"   # doji inside

    def test_piercing_and_dark_cloud(self):
        assert last([(102, 102.2, 99.8, 100), (99.5, 101.8, 99.4, 101.5)])[0] == "piercing"
        assert last([(100, 102.2, 99.8, 102), (102.5, 102.6, 100.2, 100.5)])[1] == "dark_cloud"

    def test_tweezers(self):
        assert last([(101, 101.2, 99.0, 99.5), (99.6, 101.3, 99.02, 101.1)])[0] == "tweezer_bottom"
        assert last([(99.5, 101.0, 99.3, 100.8), (100.7, 101.05, 99.2, 99.3)])[1] == "tweezer_top"


class TestThreeBar:
    def test_morning_star(self):
        rows = [(102, 102.2, 98.8, 99), (98.9, 99.2, 98.6, 99.0), (99.1, 101.4, 99.0, 101.2)]
        assert last(rows)[0] == "morning_star"

    def test_evening_star(self):
        rows = [(99, 102.2, 98.8, 102), (102.1, 102.4, 101.8, 102.0), (101.9, 102.0, 99.6, 99.8)]
        assert last(rows)[1] == "evening_star"

    def test_three_white_soldiers_and_black_crows(self):
        up = [(100, 101.1, 99.9, 101), (100.5, 102.1, 100.4, 102), (101.5, 103.1, 101.4, 103)]
        assert last(up)[0] == "three_white_soldiers"
        down = [(103, 103.1, 101.9, 102), (102.5, 102.6, 100.9, 101), (101.5, 101.6, 99.9, 100)]
        assert last(down)[1] == "three_black_crows"


def test_columns_exist_and_are_strings_for_short_frames():
    df = add_patterns(pd.DataFrame({"open": [1.0], "high": [1.2], "low": [0.9], "close": [1.1]}))
    assert list(df["bull_pattern"]) == [""] and list(df["bear_pattern"]) == [""]
