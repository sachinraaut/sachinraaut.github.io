"""Marathi formatting helpers: Devanagari digits, month names, reading time."""
from __future__ import annotations

import re
from datetime import datetime

MONTHS = ["जानेवारी", "फेब्रुवारी", "मार्च", "एप्रिल", "मे", "जून", "जुलै", "ऑगस्ट", "सप्टेंबर", "ऑक्टोबर",
          "नोव्हेंबर", "डिसेंबर"]
DIGITS = str.maketrans("0123456789", "०१२३४५६७८९")
DEVANAGARI = re.compile(r"[ऀ-ॿ]")
LETTERS = re.compile(r"[A-Za-zऀ-ॿ]")
WORDS_PER_MINUTE = 150


def num(n) -> str:
    return str(n).translate(DIGITS)


def date(d: datetime) -> str:
    return f"{num(d.day)} {MONTHS[d.month - 1]} {num(d.year)}"


def month_year(d: datetime) -> str:
    return f"{MONTHS[d.month - 1]} {num(d.year)}"


def word_count(text: str) -> int:
    return len(re.findall(r"\S+", text))


def reading_minutes(text: str) -> int:
    return max(1, round(word_count(text) / WORDS_PER_MINUTE))


def devanagari_ratio(text: str) -> float:
    """Share of Devanagari letters among all Latin+Devanagari letters."""
    letters = LETTERS.findall(text)
    if not letters:
        return 0.0
    return len(DEVANAGARI.findall(text)) / len(letters)
