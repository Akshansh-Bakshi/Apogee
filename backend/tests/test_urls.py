"""URL normalisation and domain extraction. Pure functions, so no database is needed."""

import random

import pytest

from app.core.urls import (
    MAX_CANONICAL_URL_LENGTH,
    TRACKING_PARAMETERS,
    InvalidUrlError,
    extract_domain,
    normalize_url,
)

# --- accepted schemes, host, fragment ---------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("http://example.com/page", "http://example.com/page"),
        ("https://example.com/page", "https://example.com/page"),
        ("HTTPS://EXAMPLE.COM/Page", "https://example.com/Page"),  # host lowercased, path kept
        ("https://Docs.Python.ORG/3/tutorial/", "https://docs.python.org/3/tutorial/"),
        ("  https://example.com/a \n", "https://example.com/a"),  # surrounding whitespace ignored
        ("https://example.com./a", "https://example.com/a"),  # trailing dot on the host
        ("https://münchen.de/", "https://xn--mnchen-3ya.de/"),  # IDN -> punycode
        ("https://medium.com/@user/post", "https://medium.com/@user/post"),  # '@' in a path
    ],
)
def test_scheme_and_host_are_normalised(raw: str, expected: str) -> None:
    assert normalize_url(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://example.com/a#section1", "https://example.com/a"),
        ("https://example.com/a?id=1#top", "https://example.com/a?id=1"),
        ("https://example.com/a#", "https://example.com/a"),
        ("https://example.com/#/inbox", "https://example.com/"),  # documented SPA trade-off
    ],
)
def test_fragments_are_removed(raw: str, expected: str) -> None:
    assert normalize_url(raw) == expected


# --- tracking parameters vs legitimate parameters ---------------------------------------------


def test_a_single_tracking_parameter_is_removed() -> None:
    assert normalize_url("https://example.com/a?utm_source=google") == "https://example.com/a"


def test_all_documented_tracking_parameters_are_removed() -> None:
    for name in sorted(TRACKING_PARAMETERS):
        assert normalize_url(f"https://example.com/a?{name}=x") == "https://example.com/a", name

    required = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "gclid", "fbclid"}
    assert required <= TRACKING_PARAMETERS


def test_multiple_tracking_parameters_are_removed() -> None:
    url = (
        "https://example.com/a?utm_source=a&utm_medium=b&utm_campaign=c"
        "&utm_term=d&utm_content=e&gclid=1&fbclid=2"
    )
    assert normalize_url(url) == "https://example.com/a"


def test_tracking_parameters_mixed_with_legitimate_ones() -> None:
    url = "https://example.com/tutorial?id=42&utm_source=google&page=2&fbclid=xyz&sort=asc"
    assert normalize_url(url) == "https://example.com/tutorial?id=42&page=2&sort=asc"


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/list?page=2",
        "https://example.com/item?id=123",
        "https://example.com/find?query=fastapi",
        "https://example.com/find?search=vector+database",  # '+' must survive
        "https://example.com/find?q=a%26b",  # encoded '&' must not become a separator
        "https://example.com/r?next=/a/b?c=d",  # reserved characters inside a value
        "https://example.com/a?tag=x&tag=y",  # repeated legitimate parameters keep order
        "https://example.com/a?flag&empty=",  # bare key and empty value
        "https://example.com/a?ref=nav&source=blog",  # look similar to tracking, are not
    ],
)
def test_legitimate_query_parameters_are_preserved(url: str) -> None:
    assert normalize_url(url) == url


def test_repeated_tracking_parameters_are_all_removed() -> None:
    url = "https://example.com/a?utm_source=x&id=1&utm_source=y&id=2"
    assert normalize_url(url) == "https://example.com/a?id=1&id=2"


def test_tracking_parameter_names_are_matched_case_insensitively() -> None:
    url = "https://example.com/a?UTM_Source=x&Q=1&GCLID=2"
    assert normalize_url(url) == "https://example.com/a?Q=1"  # other names keep their case


def test_an_encoded_tracking_parameter_name_is_still_recognised() -> None:
    assert normalize_url("https://example.com/a?utm%5Fsource=x&id=1") == "https://example.com/a?id=1"


@pytest.mark.parametrize(
    "raw",
    [
        "https://example.com/?",
        "https://example.com/?&&",
        "https://example.com/?utm_source=x",
        "https://example.com/?utm_source=x&gclid=y",
    ],
)
def test_a_query_left_empty_loses_its_question_mark(raw: str) -> None:
    assert normalize_url(raw) == "https://example.com/"


def test_the_issue_example_resolves_to_one_canonical_url() -> None:
    first = normalize_url("https://example.com/tutorial?id=42&utm_source=google#section1")
    second = normalize_url("https://example.com/tutorial?id=42&utm_source=twitter#section2")

    assert first == second == "https://example.com/tutorial?id=42"


def test_different_legitimate_parameters_stay_different_pages() -> None:
    assert normalize_url("https://example.com/a?id=1") != normalize_url("https://example.com/a?id=2")
    assert normalize_url("https://example.com/a?a=1&b=2") != normalize_url("https://example.com/a?b=2&a=1")


# --- ports ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("http://example.com:80/x", "http://example.com/x"),  # default port dropped
        ("https://example.com:443/x", "https://example.com/x"),
        ("https://example.com:8443/x", "https://example.com:8443/x"),  # explicit port kept
        ("http://localhost:3000/", "http://localhost:3000/"),
        ("http://example.com:443/", "http://example.com:443/"),  # 443 is not http's default
        ("https://example.com:80/", "https://example.com:80/"),  # 80 is not https's default
        ("https://example.com:/x", "https://example.com/x"),  # empty port
        ("http://[::1]:8080/x", "http://[::1]:8080/x"),  # IPv6 keeps its brackets
        ("http://[0:0:0:0:0:0:0:1]/", "http://[::1]/"),
    ],
)
def test_ports_are_handled_correctly(raw: str, expected: str) -> None:
    assert normalize_url(raw) == expected


# --- trailing slashes -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://example.com", "https://example.com/"),  # empty path -> "/"
        ("https://example.com?id=1", "https://example.com/?id=1"),
        ("https://example.com/docs/", "https://example.com/docs/"),  # preserved
        ("https://example.com/docs", "https://example.com/docs"),  # preserved, not merged
    ],
)
def test_trailing_slash_policy(raw: str, expected: str) -> None:
    assert normalize_url(raw) == expected


def test_paths_with_and_without_a_trailing_slash_stay_distinct() -> None:
    assert normalize_url("https://example.com/docs") != normalize_url("https://example.com/docs/")


# --- percent-encoding -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://example.com/caf%C3%A9", "https://example.com/caf%C3%A9"),  # already canonical
        ("https://example.com/café", "https://example.com/caf%C3%A9"),  # raw UTF-8 is escaped
        ("https://example.com/caf%c3%a9", "https://example.com/caf%C3%A9"),  # hex upper-cased
        ("https://example.com/%7Euser", "https://example.com/~user"),  # unreserved is decoded
        ("https://example.com/%41%62", "https://example.com/Ab"),
        ("https://example.com/a%2Fb", "https://example.com/a%2Fb"),  # reserved stays escaped
        ("https://example.com/a%2fb", "https://example.com/a%2Fb"),
        ("https://example.com/a b", "https://example.com/a%20b"),  # raw space is escaped
        ("https://example.com/100%", "https://example.com/100%25"),  # stray '%' is escaped
        ("https://example.com/%zz", "https://example.com/%25zz"),  # invalid escape
        ("https://example.com/a;b=c", "https://example.com/a;b=c"),  # path parameters kept
        ("https://example.com/s?q=caf%C3%A9", "https://example.com/s?q=caf%C3%A9"),
        ("https://example.com/s?q=café", "https://example.com/s?q=caf%C3%A9"),
        ("https://example.com/s?q=%41", "https://example.com/s?q=A"),
        ("https://example.com/s?q=100%", "https://example.com/s?q=100%25"),
        ("https://example.com/s?q=a%2Bb", "https://example.com/s?q=a%2Bb"),  # %2B is not '+'
    ],
)
def test_percent_encoding_is_canonicalised_safely(raw: str, expected: str) -> None:
    assert normalize_url(raw) == expected


def test_equivalent_encodings_resolve_to_the_same_url() -> None:
    assert normalize_url("https://example.com/café") == normalize_url("https://example.com/caf%c3%a9")


# --- rejected input ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "not a url",
        "example.com/path",  # no scheme
        "//example.com/path",  # scheme-relative
        "http://",
        "https:///path",  # no host
        "http:/example.com",
        "http://exa mple.com/",  # space in host
        "http://exa\nmple.com/",  # control character
        "http://exa\x00mple.com/",
        "http://[::1/",  # unbalanced IPv6 bracket
        "http://[not-an-ip]/",
        "http://example.com:notaport/",
        "http://example.com:99999/",  # port out of range
        "http://example.com:0/",
        "http://.example.com/",  # empty label
        "http://exa..mple.com/",
        "http://" + "a" * 64 + ".com/",  # label longer than 63
        "http://exa$mple.com/",  # character not allowed in a host
        "https://example.com/\ud800",  # lone surrogate
    ],
)
def test_malformed_urls_are_rejected(raw: str) -> None:
    with pytest.raises(InvalidUrlError):
        normalize_url(raw)


@pytest.mark.parametrize(
    "raw",
    [
        "ftp://example.com/file",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "data:text/html,hello",
        "chrome://settings",
        "about:blank",
        "mailto:someone@example.com",
        "ws://example.com/socket",
    ],
)
def test_unsupported_schemes_are_rejected(raw: str) -> None:
    with pytest.raises(InvalidUrlError, match="http or https"):
        normalize_url(raw)


@pytest.mark.parametrize(
    "raw",
    [
        "https://user:hunter2@example.com/",
        "https://user@example.com/",
        "https://@example.com/",
    ],
)
def test_urls_with_credentials_are_rejected(raw: str) -> None:
    with pytest.raises(InvalidUrlError, match="credentials"):
        normalize_url(raw)


def test_error_messages_never_contain_the_url() -> None:
    secret = "https://user:hunter2@example.com/?token=abc123"
    with pytest.raises(InvalidUrlError) as excinfo:
        normalize_url(secret)

    assert "hunter2" not in str(excinfo.value)
    assert "abc123" not in str(excinfo.value)


def test_urls_longer_than_the_database_column_are_rejected() -> None:
    with pytest.raises(InvalidUrlError, match="longer than"):
        normalize_url("https://example.com/" + "a" * MAX_CANONICAL_URL_LENGTH)


def test_long_tracking_noise_does_not_make_a_url_too_long() -> None:
    # The limit applies to the canonical form, after tracking parameters are removed.
    raw = "https://example.com/a?utm_source=" + "x" * 5000
    assert normalize_url(raw) == "https://example.com/a"


# --- properties -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "https://example.com",
        "HTTP://Example.com:80/A%7e?b=%2f&utm_source=x#frag",
        "https://münchen.de/café?q=ü&gclid=1",
        "http://[0:0:0:0:0:0:0:1]:8080/a b?x=100%",
        "https://example.com/a?tag=x&tag=y&flag&empty=",
    ],
)
def test_normalisation_is_idempotent(raw: str) -> None:
    once = normalize_url(raw)
    assert normalize_url(once) == once


def test_random_input_never_escapes_as_anything_but_invalid_url_error() -> None:
    rng = random.Random(20260101)  # fixed seed: deterministic
    alphabet = list("abcXYZ019-._~:/?#[]@!$&'()*+,;=% \t\n") + ["é", "%2F", "%zz", "xn--", "utm_source=", "http://"]
    for _ in range(3000):
        raw = rng.choice(["http://", "https://", ""]) + "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 40)))
        try:
            canonical = normalize_url(raw)
        except InvalidUrlError:
            continue
        assert canonical.startswith(("http://", "https://"))
        assert "#" not in canonical
        assert len(canonical) <= MAX_CANONICAL_URL_LENGTH
        assert normalize_url(canonical) == canonical  # idempotent


# --- domain extraction ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://example.com/path", "example.com"),
        ("https://docs.python.org/3/tutorial/", "docs.python.org"),  # subdomain kept
        ("https://a.b.c.example.co.uk/", "a.b.c.example.co.uk"),  # no organisational inference
        ("http://example.com:8080/x", "example.com"),  # port excluded
        ("http://localhost:3000/", "localhost"),
        ("http://[::1]:8080/x", "::1"),
        ("HTTP://Example.COM/", "example.com"),  # lowercased
    ],
)
def test_extract_domain(url: str, expected: str) -> None:
    assert extract_domain(url) == expected


def test_extract_domain_from_a_normalised_url() -> None:
    canonical = normalize_url("HTTPS://Docs.Python.org:443/3/tutorial/?utm_source=x#top")

    assert extract_domain(canonical) == "docs.python.org"


@pytest.mark.parametrize("url", ["", "not a url", "https:///path", "http://[::1/"])
def test_extract_domain_rejects_urls_without_a_host(url: str) -> None:
    with pytest.raises(InvalidUrlError):
        extract_domain(url)
