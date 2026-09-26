"""Cleaning and chunking of page text captured by the browser extension. Pure functions: no I/O.

Cleaning policy
----------------
A small, documented set of heuristics, not an NLP pipeline: normalise line endings and control
characters, collapse runs of horizontal whitespace and blank lines, drop lines that exactly match
a short list of common navigation/boilerplate phrases (case-insensitive, whole line only, so real
sentences that merely contain a word like "menu" are never touched), and collapse immediately
repeated lines (a common artifact of naively-extracted navigation). Content that is empty or still
very short after cleaning is rejected rather than silently stored, so a broken extraction never
produces a near-empty page that looks captured but is not useful.

Chunking policy
----------------
Fixed-size character windows with a fixed character overlap, moving left to right with a constant
step (``chunk_size - overlap``); this guarantees termination, a stable chunk count, and identical
output for identical input. Chunks are not snapped to word or sentence boundaries: for text meant
to be embedded later, a chunk occasionally starting or ending mid-word is an acceptable trade-off
for a simple, obviously-correct algorithm today. Word/sentence-aware chunking can replace this
later without changing anything that depends on chunk shape (index, ordering, page relationship).
"""

import re
from typing import NamedTuple

MIN_CLEANED_TEXT_LENGTH = 40  # a real sentence or two; below this, extraction likely failed
DEFAULT_CHUNK_SIZE_CHARS = 1000
DEFAULT_CHUNK_OVERLAP_CHARS = 150

# Exact, case-insensitive whole-line matches only, so this never touches ordinary prose that
# happens to contain one of these words. Not exhaustive; a deliberately small starting set.
BOILERPLATE_LINES = frozenset(
    {
        "skip to content",
        "skip to main content",
        "home",
        "menu",
        "search",
        "subscribe",
        "sign in",
        "log in",
        "log out",
        "sign up",
        "accept cookies",
        "accept all cookies",
        "accept all",
        "reject all",
        "cookie policy",
        "privacy policy",
        "terms of service",
        "back to top",
        "share this page",
        "advertisement",
    }
)

_CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")  # keep \t \n
_HORIZONTAL_WHITESPACE = re.compile(r"[ \t\u00a0\u200b]+")  # plain space/tab, NBSP, zero-width space
_MULTIPLE_BLANK_LINES = re.compile(r"\n{3,}")


class ContentRejectedError(ValueError):
    """Content is empty, or still too short after cleaning, to be worth storing."""


def clean_text(raw: str) -> str:
    """Return a normalised version of ``raw``, or raise ``ContentRejectedError``."""
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL_CHARACTERS.sub("", text)
    text = _HORIZONTAL_WHITESPACE.sub(" ", text)

    lines: list[str] = []
    previous: str | None = None
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            lines.append("")  # preserve the paragraph break; collapsed below
            previous = None  # a blank line always resets duplicate-detection
            continue
        if stripped.lower() in BOILERPLATE_LINES:
            continue
        if stripped == previous:  # an immediately repeated line (e.g. duplicated nav markup)
            continue
        lines.append(stripped)
        previous = stripped

    text = _MULTIPLE_BLANK_LINES.sub("\n\n", "\n".join(lines)).strip()
    if len(text) < MIN_CLEANED_TEXT_LENGTH:
        raise ContentRejectedError(
            f"content is empty or too short after cleaning (minimum {MIN_CLEANED_TEXT_LENGTH} characters)"
        )
    return text


class Chunk(NamedTuple):
    index: int  # 0-based, stable ordering within the page
    text: str
    start: int  # character offsets into the cleaned text this chunk was cut from
    end: int


def chunk_text(
    cleaned_text: str,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE_CHARS,
    overlap: int = DEFAULT_CHUNK_OVERLAP_CHARS,
) -> list[Chunk]:
    """Split already-cleaned text into fixed-size, overlapping chunks. Deterministic.

    Intended to run on the output of ``clean_text``; raises ``ContentRejectedError`` if given
    empty text so a caller cannot accidentally chunk unvalidated input.
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if not (0 <= overlap < chunk_size):
        raise ValueError("overlap must satisfy 0 <= overlap < chunk_size")
    if not cleaned_text:
        raise ContentRejectedError("cannot chunk empty text")

    step = chunk_size - overlap  # always > 0, so `start` strictly advances: this always terminates
    length = len(cleaned_text)
    chunks: list[Chunk] = []
    start = 0
    index = 0
    while start < length:
        end = min(start + chunk_size, length)
        chunks.append(Chunk(index=index, text=cleaned_text[start:end], start=start, end=end))
        index += 1
        if end == length:
            break
        start += step
    return chunks
