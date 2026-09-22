"""URL normalisation and hostname extraction. Pure functions: no I/O, no network, no HTML.

Normalisation policy
--------------------
The goal is a *conservative* canonical form: two URLs are merged only when they are equivalent
by the URL standards or differ solely in well-known tracking noise. When unsure, they stay
different. A missed merge costs a duplicate page; a wrong merge loses information for good.

Applied:
  * scheme must be ``http`` or ``https`` (lowercased); everything else is rejected
  * credentials in the URL (``user:pass@host``) are rejected, never stored
  * host is lowercased, IDNA (punycode) encoded, and a single trailing dot is removed
  * the default port (80 for http, 443 for https) is dropped; other ports are kept
  * the fragment (``#...``) is removed
  * an empty path becomes ``/``; other paths are otherwise left as they are
  * percent-encoding is canonicalised: escapes of unreserved characters are decoded
    (``%7E`` -> ``~``), other escapes are upper-cased (``%c3%a9`` -> ``%C3%A9``), and
    characters that must be escaped (non-ASCII, spaces, a stray ``%``) are escaped as UTF-8.
    Reserved characters are never decoded, so ``%2F`` stays distinct from ``/``.
  * tracking parameters (see ``TRACKING_PARAMETERS``) are removed wherever they appear,
    matched case-insensitively; every other parameter is kept with its order, duplicates,
    ``+`` signs and empty values intact. A query left empty loses its ``?``.

Deliberately NOT done (each would risk merging pages that differ):
  * trailing slashes are preserved: ``/docs`` and ``/docs/`` stay distinct (servers may treat
    them as different resources); only the empty path is rewritten to ``/``
  * query parameters are not sorted (order can matter to a server)
  * dot segments (``/a/../b``) are not resolved (browsers already resolve them)
  * path/query case is not changed; ``www.`` is not stripped; ``http`` is not upgraded to ``https``
  * nothing is fetched: no redirects are followed and no HTML is inspected for a canonical link

Known trade-off: removing fragments makes hash-routed single-page apps (``/#/inbox``,
``/#/settings``) collapse into one page.
"""

import ipaddress
import re
import string
from urllib.parse import urlsplit

# Must not exceed the pages.canonical_url column (VARCHAR(2048)).
MAX_CANONICAL_URL_LENGTH = 2048
MAX_HOSTNAME_LENGTH = 253  # DNS limit

# Query parameters that identify a campaign or click rather than the page. Matched
# case-insensitively. Extending this set is the only change needed to recognise more.
TRACKING_PARAMETERS = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "utm_id",
        "gclid",
        "fbclid",
        "dclid",
        "gbraid",
        "wbraid",
        "msclkid",
        "yclid",
        "mc_cid",
        "mc_eid",
    }
)

_DEFAULT_PORTS = {"http": 80, "https": 443}

_UNRESERVED = frozenset(string.ascii_letters + string.digits + "-._~")
_PATH_SAFE = _UNRESERVED | frozenset("!$&'()*+,;=:@/")
_QUERY_SAFE = _PATH_SAFE | frozenset("?")
_HEX_DIGITS = frozenset(string.hexdigits)

_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")
_HOSTNAME = re.compile(r"[a-z0-9_-]+(?:\.[a-z0-9_-]+)*")


class InvalidUrlError(ValueError):
    """The URL is malformed or not acceptable. Messages never contain the URL itself."""


def normalize_url(raw_url: str) -> str:
    """Return the canonical form of an http(s) URL, or raise ``InvalidUrlError``."""
    url = raw_url.strip()
    if not url:
        raise InvalidUrlError("URL must not be empty")
    if _CONTROL_CHARACTERS.search(url):
        # Checked before parsing: urlsplit silently deletes tabs and newlines.
        raise InvalidUrlError("URL must not contain control characters")

    try:
        parts = urlsplit(url)
        port = parts.port
        hostname = parts.hostname
    except ValueError:
        raise InvalidUrlError("URL is malformed") from None

    scheme = parts.scheme  # urlsplit lowercases it
    if scheme not in _DEFAULT_PORTS:
        raise InvalidUrlError("URL scheme must be http or https")
    if "@" in parts.netloc:
        raise InvalidUrlError("URLs containing credentials are not accepted")
    if not hostname:
        raise InvalidUrlError("URL must include a host")

    host = _normalize_hostname(hostname)
    netloc = f"[{host}]" if ":" in host else host
    if port is not None:
        if port == 0:
            raise InvalidUrlError("URL port is invalid")
        if port != _DEFAULT_PORTS[scheme]:
            netloc = f"{netloc}:{port}"

    canonical = f"{scheme}://{netloc}{_normalize_component(parts.path, _PATH_SAFE) or '/'}"
    query = _normalize_query(parts.query)
    if query:
        canonical = f"{canonical}?{query}"

    if len(canonical) > MAX_CANONICAL_URL_LENGTH:
        raise InvalidUrlError(f"URL is longer than {MAX_CANONICAL_URL_LENGTH} characters")
    return canonical


def extract_domain(url: str) -> str:
    """Return the lowercase hostname of ``url`` (no port, no userinfo).

    Intended for URLs already returned by ``normalize_url``. This is the hostname, not the
    registrable/organisational domain: ``docs.python.org`` stays ``docs.python.org``. Grouping by
    organisation would need the public-suffix list and is deliberately out of scope; callers depend
    only on this function's signature, so a smarter implementation can replace it later.
    """
    try:
        hostname = urlsplit(url).hostname
    except ValueError:
        raise InvalidUrlError("URL is malformed") from None
    if not hostname:
        raise InvalidUrlError("URL must include a host")
    return hostname


def _normalize_hostname(hostname: str) -> str:
    if ":" in hostname:  # IPv6 literal; urlsplit has already removed the brackets
        if "%" in hostname:  # zone identifiers are not meaningful outside one machine
            raise InvalidUrlError("URL host is invalid")
        try:
            return str(ipaddress.IPv6Address(hostname))
        except ValueError:
            raise InvalidUrlError("URL host is invalid") from None

    try:
        ascii_host = hostname.encode("idna").decode("ascii")
    except UnicodeError:  # empty or over-long label, unencodable characters
        raise InvalidUrlError("URL host is invalid") from None

    ascii_host = ascii_host.lower().removesuffix(".")
    if len(ascii_host) > MAX_HOSTNAME_LENGTH or not _HOSTNAME.fullmatch(ascii_host):
        raise InvalidUrlError("URL host is invalid")
    return ascii_host


def _normalize_query(query: str) -> str:
    kept: list[str] = []
    for pair in query.split("&"):
        if not pair:
            continue
        normalized = _normalize_component(pair, _QUERY_SAFE)
        name = normalized.split("=", 1)[0]
        if name.lower() not in TRACKING_PARAMETERS:
            kept.append(normalized)
    return "&".join(kept)


def _normalize_component(component: str, safe: frozenset[str]) -> str:
    """Canonicalise percent-encoding without changing what the component means."""
    out: list[str] = []
    i, length = 0, len(component)
    while i < length:
        char = component[i]
        if (
            char == "%"
            and i + 2 < length
            and component[i + 1] in _HEX_DIGITS
            and component[i + 2] in _HEX_DIGITS
        ):
            byte = int(component[i + 1 : i + 3], 16)
            decoded = chr(byte)
            out.append(decoded if decoded in _UNRESERVED else f"%{byte:02X}")
            i += 3
            continue
        if char in safe:
            out.append(char)
        else:
            try:
                out.extend(f"%{byte:02X}" for byte in char.encode("utf-8"))
            except UnicodeEncodeError:  # lone surrogate
                raise InvalidUrlError("URL contains invalid characters") from None
        i += 1
    return "".join(out)
