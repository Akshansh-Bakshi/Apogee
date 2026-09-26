"""Text cleaning and chunking (app.core.content). Pure functions: no database needed."""

import pytest

from app.core.content import (
    DEFAULT_CHUNK_OVERLAP_CHARS,
    DEFAULT_CHUNK_SIZE_CHARS,
    MIN_CLEANED_TEXT_LENGTH,
    Chunk,
    ContentRejectedError,
    chunk_text,
    clean_text,
)

PARAGRAPH = (
    "Apogee is a temporal-semantic personal web-memory system. "
    "It captures what you read, cleans the text, and later makes it searchable by meaning."
)  # well over MIN_CLEANED_TEXT_LENGTH


# --- clean_text: whitespace and line endings ---------------------------------------------------


def test_horizontal_whitespace_is_collapsed() -> None:
    raw = "Hello    world,\tthis   is\ttext " + "x" * 20
    assert clean_text(raw) == "Hello world, this is text " + "x" * 20


def test_crlf_and_cr_line_endings_are_normalised() -> None:
    raw = "Line one.\r\nLine two.\rLine three, which is long enough to pass the minimum length check."
    assert "\r" not in clean_text(raw)


def test_leading_and_trailing_whitespace_is_stripped() -> None:
    assert clean_text("   \n\n  " + PARAGRAPH + "  \n\n  ") == PARAGRAPH


@pytest.mark.parametrize("space", ["\u00a0", "\u200b"])
def test_unicode_space_variants_are_collapsed(space: str) -> None:
    text = f"Hello{space}world, this sentence is long enough to clear the minimum length by a margin."
    assert space not in clean_text(text)


def test_control_characters_are_removed_but_newlines_survive() -> None:
    raw = "First paragraph of real content here.\n\x00\x07Second paragraph, also real content, long enough."
    cleaned = clean_text(raw)
    assert "\x00" not in cleaned and "\x07" not in cleaned
    assert "\n" in cleaned


# --- clean_text: blank lines ---------------------------------------------------------------------


def test_runs_of_blank_lines_collapse_to_one() -> None:
    raw = "First real paragraph, long enough on its own.\n\n\n\n\nSecond real paragraph, also long enough."
    cleaned = clean_text(raw)
    assert "\n\n\n" not in cleaned
    assert cleaned.count("\n\n") == 1


# --- clean_text: boilerplate and duplicate lines --------------------------------------------------


@pytest.mark.parametrize("line", ["Menu", "menu", "MENU", "Home", "Sign in", "Accept all cookies"])
def test_exact_boilerplate_lines_are_dropped(line: str) -> None:
    cleaned = clean_text(f"{line}\n{PARAGRAPH}")
    assert line.lower() not in cleaned.lower().split("\n")
    assert PARAGRAPH in cleaned


def test_a_word_that_only_resembles_boilerplate_is_kept() -> None:
    # "Home renovation..." is not the whole-line match "home", so it must survive untouched.
    raw = "Home renovation tips that go well beyond a single boilerplate word on its own line."
    assert clean_text(raw) == raw


def test_immediately_repeated_lines_are_collapsed_to_one() -> None:
    cleaned = clean_text(f"{PARAGRAPH}\n{PARAGRAPH}\n{PARAGRAPH}")
    assert cleaned == PARAGRAPH


def test_non_adjacent_repeated_lines_are_both_kept() -> None:
    other = "A completely different paragraph placed in between the two repeats, long enough on its own."
    cleaned = clean_text(f"{PARAGRAPH}\n{other}\n{PARAGRAPH}")
    assert cleaned.count(PARAGRAPH) == 2


# --- clean_text: rejection ------------------------------------------------------------------------


@pytest.mark.parametrize("raw", ["", "   ", "\n\n\n", "hi", "Menu\nHome\nSearch\nSign in\nLog in"])
def test_empty_or_near_empty_content_is_rejected(raw: str) -> None:
    with pytest.raises(ContentRejectedError):
        clean_text(raw)


def test_content_right_at_the_minimum_length_is_accepted() -> None:
    text = "x" * MIN_CLEANED_TEXT_LENGTH
    assert clean_text(text) == text


def test_content_one_under_the_minimum_length_is_rejected() -> None:
    with pytest.raises(ContentRejectedError):
        clean_text("x" * (MIN_CLEANED_TEXT_LENGTH - 1))


# --- chunk_text: basic shape -----------------------------------------------------------------------


def test_short_text_becomes_a_single_chunk() -> None:
    text = "x" * 100
    chunks = chunk_text(text, chunk_size=1000, overlap=150)
    assert chunks == [Chunk(index=0, text=text, start=0, end=100)]


def test_text_exactly_one_chunk_long_stays_one_chunk() -> None:
    text = "x" * 1000
    chunks = chunk_text(text, chunk_size=1000, overlap=150)
    assert len(chunks) == 1
    assert (chunks[0].start, chunks[0].end) == (0, 1000)


def test_chunking_is_deterministic() -> None:
    text = ("word " * 500).strip()
    assert chunk_text(text, chunk_size=200, overlap=40) == chunk_text(text, chunk_size=200, overlap=40)


def test_chunk_indices_are_sequential_from_zero() -> None:
    chunks = chunk_text("x" * 2500, chunk_size=200, overlap=40)
    assert [c.index for c in chunks] == list(range(len(chunks)))
    assert len(chunks) > 1


def test_the_first_chunk_starts_at_zero_and_the_last_ends_at_the_text_length() -> None:
    text = "x" * 2537
    chunks = chunk_text(text, chunk_size=200, overlap=40)
    assert chunks[0].start == 0
    assert chunks[-1].end == len(text)


def test_consecutive_chunks_advance_by_chunk_size_minus_overlap() -> None:
    chunks = chunk_text("x" * 2537, chunk_size=200, overlap=40)
    for earlier, later in zip(chunks, chunks[1:]):
        assert later.start == earlier.start + (200 - 40)


def test_overlap_between_consecutive_full_size_chunks_matches_the_requested_overlap() -> None:
    text = "".join(str(i % 10) for i in range(2537))  # distinct digits so substrings are comparable
    chunks = chunk_text(text, chunk_size=200, overlap=40)
    for earlier, later in zip(chunks, chunks[1:-1]):  # exclude the possibly-shorter final chunk
        assert earlier.text[-40:] == later.text[:40]


def test_every_chunk_text_matches_its_own_offsets() -> None:
    text = "".join(str(i % 10) for i in range(2537))
    for chunk in chunk_text(text, chunk_size=200, overlap=40):
        assert chunk.text == text[chunk.start : chunk.end]


def test_no_chunk_exceeds_the_requested_size() -> None:
    for chunk in chunk_text("x" * 2537, chunk_size=200, overlap=40):
        assert len(chunk.text) <= 200


def test_chunks_cover_the_full_text_with_no_gap() -> None:
    chunks = chunk_text("x" * 2537, chunk_size=200, overlap=40)
    for earlier, later in zip(chunks, chunks[1:]):
        assert later.start <= earlier.end


def test_zero_overlap_produces_back_to_back_chunks() -> None:
    chunks = chunk_text("x" * 500, chunk_size=100, overlap=0)
    assert [c.start for c in chunks] == [0, 100, 200, 300, 400]
    assert [c.end for c in chunks] == [100, 200, 300, 400, 500]


def test_default_chunk_size_and_overlap_are_used_when_not_specified() -> None:
    text = "x" * (DEFAULT_CHUNK_SIZE_CHARS * 2)
    assert chunk_text(text) == chunk_text(text, chunk_size=DEFAULT_CHUNK_SIZE_CHARS, overlap=DEFAULT_CHUNK_OVERLAP_CHARS)


# --- chunk_text: rejection / invalid parameters -----------------------------------------------------


def test_chunking_empty_text_is_rejected() -> None:
    with pytest.raises(ContentRejectedError):
        chunk_text("")


@pytest.mark.parametrize("chunk_size", [0, -1, -100])
def test_a_non_positive_chunk_size_is_rejected(chunk_size: int) -> None:
    with pytest.raises(ValueError, match="chunk_size"):
        chunk_text("x" * 500, chunk_size=chunk_size, overlap=0)


@pytest.mark.parametrize("overlap", [-1, 100])  # overlap == chunk_size (100) is also invalid
def test_an_invalid_overlap_is_rejected(overlap: int) -> None:
    with pytest.raises(ValueError, match="overlap"):
        chunk_text("x" * 500, chunk_size=100, overlap=overlap)


def test_chunk_text_is_independent_of_the_cleaning_length_threshold() -> None:
    # chunk_text does not re-apply MIN_CLEANED_TEXT_LENGTH: that check belongs to clean_text only.
    assert chunk_text("short", chunk_size=100, overlap=10) == [Chunk(index=0, text="short", start=0, end=5)]
