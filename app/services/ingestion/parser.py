import asyncio
import hashlib
import logging
import re
from typing import Final

import httpx
import trafilatura
from bs4 import BeautifulSoup

async_playwright = None
Stealth = None
try:
    from playwright.async_api import async_playwright
    from playwright_stealth import Stealth
    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    _PLAYWRIGHT_AVAILABLE = False

CurlSession = None
try:
    from curl_cffi.requests import AsyncSession as CurlSession
    _CURL_CFFI_AVAILABLE = True
except ImportError:
    _CURL_CFFI_AVAILABLE = False

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Mimics a real Chrome browser on macOS.
# Websites inspect this header to decide whether to serve full HTML or a
# bot-detection page. A raw "python-httpx/x.y.z" agent often gets blocked.
_USER_AGENT: Final[str] = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# Full browser Accept headers prevent servers from returning stripped-down
# responses intended for non-browser clients.
_DEFAULT_HEADERS: Final[dict[str, str]] = {
    "User-Agent": _USER_AGENT,
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, zstd",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

# Granular timeout splits: connect (TCP handshake), read (response body),
# write (request upload — small for GET requests), pool (wait for a free
# connection slot from the shared client pool).
_TIMEOUT: Final[httpx.Timeout] = httpx.Timeout(
    connect=5.0,
    read=10.0,
    write=5.0,
    pool=5.0,
)

# Retry configuration — keeps fetch_url predictable under transient failures
# without hammering a server that is genuinely down.
_MAX_RETRIES: Final[int] = 3
_RETRY_BACKOFF_BASE: Final[float] = 1.5   # seconds: 1.5 → 2.25 → 3.375
_RETRY_BACKOFF_MAX: Final[float] = 10.0

# HTTP status codes that are safe to retry — server-side transient errors.
# 4xx codes (except 429 Too Many Requests) are NOT retried because the
# request itself is the problem, not the server state.
_RETRYABLE_STATUS_CODES: Final[frozenset[int]] = frozenset({
    429,  # Too Many Requests  — back off and retry
    500,  # Internal Server Error
    502,  # Bad Gateway
    503,  # Service Unavailable
    504,  # Gateway Timeout
})

# Maximum HTML response size accepted (10 MB).
# Protects the pipeline from accidentally ingesting a huge binary response
# that slipped past Content-Type checks.
_MAX_RESPONSE_BYTES: Final[int] = 10 * 1024 * 1024

# Minimum character count accepted from strip_boilerplate.
# A real job posting is never shorter than this; anything less is a
# JS-rendered shell, a CAPTCHA page, or a bot-detection stub.
_MIN_CONTENT_CHARS: Final[int] = 200

# Structural tags that never contain job posting content.
# Decomposed by the BeautifulSoup fallback before text extraction so that
# navigation links, cookie banners, and form labels don't pollute the output.
_BS4_BOILERPLATE_TAGS: Final[frozenset[str]] = frozenset({
    "script", "style", "noscript",
    "nav", "header", "footer", "aside",
    "form", "figure", "iframe", "svg",
})

class FetchError(Exception):
    """Base class for all fetch_url failures.
    Catching this single type at the route layer covers every failure
    mode from fetch_url without needing to import httpx there.
    """

class FetchTimeoutError(FetchError):
    """Raised when a fetch_url operation times out."""

class FetchHTTPError(FetchError):
    """Server returned a non-2xx status code after all retries."""
    def __init__(self, status_code: int, url: str) -> None:
        self.status_code = status_code
        self.url = url
        super().__init__(f"HTTP {status_code} error for URL: {url}")

class FetchNetworkError(FetchError):
    """Network-level failure — DNS resolution, connection refused, etc."""


class FetchContentError(FetchError):
    """Response was received but the content is unusable — not HTML or too large."""

class FetchBlockedError(FetchContentError):
    """Site actively blocked the request — WAF, bot-protection, or CAPTCHA."""

async def fetch_url(url: str) -> str:
    """Fetch raw HTML from a URL.

    First attempts a plain HTTP fetch. If the response appears to be a
    JavaScript-rendered shell (empty body), falls back to Playwright to
    execute JavaScript and return the fully-rendered HTML.

    Raises:
        FetchTimeoutError:   Server did not respond within the timeout window.
        FetchHTTPError:      Server returned a non-2xx status after all retries.
        FetchNetworkError:   DNS failure, connection refused, or other network error.
        FetchContentError:   Response is not HTML, too large, or a JS shell that
                             Playwright also could not render.
    """
    _validate_url(url)
    logger.info("Starting fetch for URL: %s", url)

    html: str | None = None
    try:
        async with httpx.AsyncClient(
            headers=_DEFAULT_HEADERS,
            timeout=_TIMEOUT,
            follow_redirects=True,
            max_redirects=3,
        ) as client:
            html = await _fetch_with_retry(client, url)
    except FetchHTTPError as exc:
        if exc.status_code != 403:
            raise
        logger.info("Got 403 from %s — retrying with Chrome TLS impersonation", url)

    # Layer 2: curl_cffi with Chrome TLS fingerprint — bypasses TLS-based WAF blocks.
    if html is None or _is_js_shell(html):
        if _CURL_CFFI_AVAILABLE:
            logger.info("Trying curl_cffi for %s", url)
            html = await _fetch_with_curl_cffi(url)

    # Layer 3: Playwright — full JS execution for CSR/SPA pages.
    if html is None or _is_js_shell(html):
        logger.info("JS shell after curl_cffi — falling back to Playwright for %s", url)
        html = await _fetch_with_playwright(url)

    return html
    
def _is_js_shell(html: str) -> bool:
    """Return True when the fetched HTML has no renderable body text.

    A body with fewer than 200 visible characters strongly indicates a
    client-side-rendered (CSR/SPA) page where the real content is injected
    by JavaScript — there is nothing useful for the text extractors to work with.
    """
    soup = BeautifulSoup(html, "lxml")
    body = soup.find("body")
    if body is None:
        return True
    visible = body.get_text(separator=" ", strip=True)
    return len(visible) < 200


_WAF_MARKERS: Final[frozenset[str]] = frozenset({
    "access denied",
    "you don't have permission",
    "403 forbidden",
    "error 1020",   # Cloudflare
    "checking your browser",
    "enable javascript and cookies",
    "recaptcha",
    "captcha",
})


def _is_waf_block(html: str) -> bool:
    """Return True when the page is a WAF / bot-protection block page."""
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(separator=" ", strip=True).lower()
    return any(marker in text for marker in _WAF_MARKERS)


async def _fetch_with_curl_cffi(url: str) -> str | None:
    """Fetch a URL using curl_cffi with Chrome TLS fingerprint impersonation.

    Bypasses CDN/WAF blocks that rely on TLS fingerprint (JA3/JA4) matching.
    Returns None if the response is still a 403 so the caller can escalate to
    Playwright. Does NOT raise on 403 — that is not an error at this layer.
    """
    assert CurlSession is not None
    try:
        async with CurlSession() as session:
            r = await session.get(
                url,
                impersonate="chrome136",
                allow_redirects=True,
                timeout=15,
                headers={k: v for k, v in _DEFAULT_HEADERS.items() if k != "Accept-Encoding"},
            )
        logger.info("curl_cffi got HTTP %d for %s (%d bytes)", r.status_code, url, len(r.content))
        if r.status_code == 403:
            return None
        if r.status_code >= 400:
            raise FetchHTTPError(r.status_code, url)
        return r.text
    except FetchHTTPError:
        raise
    except Exception as exc:
        logger.warning("curl_cffi failed for %s: %s", url, exc)
        return None


async def _fetch_with_playwright(url: str) -> str:
    """Render a JavaScript-heavy page with a stealth headless Chromium browser.

    Raises:
        FetchContentError: Playwright is not installed, the browser was blocked
                           (e.g. Akamai/Cloudflare WAF), or the rendered page
                           is still empty after JS execution.
    """
    if not _PLAYWRIGHT_AVAILABLE:
        raise FetchContentError(
            f"Page at {url} requires JavaScript rendering but the 'playwright' "
            "package is not installed. Run: pip install playwright && playwright install chromium"
        )

    assert async_playwright is not None and Stealth is not None
    logger.info("Launching Playwright for %s", url)
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            page = await browser.new_page()
            await Stealth().apply_stealth_async(page)
            await page.set_extra_http_headers({
                "Accept-Language": "en-US,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            })
            response = await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            await page.wait_for_timeout(3_000)
            status = response.status if response else 0
            html = await page.content()
            await browser.close()
    except Exception as exc:
        raise FetchContentError(
            f"Playwright failed to render {url}: {exc}"
        ) from exc

    if status not in (0, 200, 301, 302, 303, 307, 308):
        raise FetchBlockedError(
            f"Playwright got HTTP {status} from {url} — page is inaccessible."
        )

    if _is_waf_block(html):
        raise FetchBlockedError(
            f"Page at {url} is protected by a WAF / bot-detection system (e.g. Akamai, Cloudflare). "
            "Automated access is blocked. This site requires an authenticated browser session."
        )

    if _is_js_shell(html):
        raise FetchBlockedError(
            f"Page at {url} rendered an empty body even after JavaScript execution. "
            "The site may require login or use aggressive bot-protection."
        )

    logger.info("Playwright rendered %d bytes for %s", len(html), url)
    return html


def _validate_url(url: str) -> None:
    """Fail fast on obviously invalid URLs before making any network call."""
    if not url or not isinstance(url, str):
        raise ValueError("URL must be a non-empty string.")
    if not url.startswith(("http://", "https://")):
        raise ValueError("URL must start with http:// or https://")
    if len(url) > 2048:
        raise ValueError("URL length exceeds maximum of 2048 characters.")
    
async def _fetch_with_retry(client: httpx.AsyncClient, url: str) -> str:
    """Execute the HTTP GET with exponential backoff on retryable failures.
    Separating retry logic from fetch_url keeps each function focused on
    one responsibility and makes the retry behaviour independently testable.
    """
    last_exec: Exception | None = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            logger.debug("Fetching url attempt %d/%d: %s", attempt, _MAX_RETRIES, url)
            return await _execute_request(client, url)
        except httpx.TimeoutException as exc:
            last_exc = FetchTimeoutError(
                f"Timeout on attempt {attempt}/{_MAX_RETRIES}: {url}"
            )
            logger.warning("Timeout fetching %s (attempt %d/%d)", url, attempt, _MAX_RETRIES)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in _RETRYABLE_STATUS_CODES:
                # Non-retryable HTTP error (e.g. 403, 404) — fail immediately.
                raise FetchHTTPError(exc.response.status_code, url) from exc
            last_exc = FetchHTTPError(exc.response.status_code, url)
            logger.warning(
                "HTTP %d on attempt %d/%d: %s",
                exc.response.status_code, attempt, _MAX_RETRIES, url,
            )

        except httpx.RequestError as exc:
            # DNS failure, connection refused, SSL error, etc.
            # These are usually not transient, but we retry once in case of
            # a brief network blip.
            last_exc = FetchNetworkError(f"Network error fetching {url}: {exc}") 
            logger.warning("Network error fetching %s (attempt %d/%d): %s", url, attempt, _MAX_RETRIES, exc)

        if attempt < _MAX_RETRIES:
            backoff = min(_RETRY_BACKOFF_BASE * (2 ** (attempt - 1)), _RETRY_BACKOFF_MAX)
            logger.debug("Backing off %.2fs before retry %d", backoff, attempt + 1)
            await asyncio.sleep(backoff)
    
    # All retries exhausted — raise the last recorded exception.
    raise last_exc  # type: ignore[misc]  — always set after at least one attempt

async def _execute_request(client: httpx.AsyncClient, url: str) -> str:
    """Execute a single HTTP GET and validate the response content.
    Separated from retry logic so each layer has exactly one concern:
    _fetch_with_retry handles when to try, _execute_request handles how.
    """
    response = await client.get(url)
    response.raise_for_status()
    logger.debug("Received HTTP response: %s", response)

    _validate_response(response, url)

    logger.info(
        "Fetched %s — status=%d size=%d bytes",
        url, response.status_code, len(response.content),
    )
    return response.text

def _validate_response(response: httpx.Response, url: str) -> None:
    """Guard against responses that are technically 200 but unusable.
    Some servers return 200 with a CAPTCHA page or a binary file.
    Catching this here prevents silent failures downstream in the
    parser and embedding stages.
    """
    content_type = response.headers.get("Content-Type", "")
    if "text/html" not in content_type and "text/plain" not in content_type:
        raise FetchContentError(
            f"Expected HTML response, got Content-Type: {content_type!r} from {url}"
        )

    if len(response.content) > _MAX_RESPONSE_BYTES:
        raise FetchContentError(
            f"Response from {url} exceeds {_MAX_RESPONSE_BYTES // (1024*1024)} MB limit "
            f"({len(response.content)} bytes)"
        )

    if len(response.content) < 500:
        # A job posting page with less than 500 bytes of content is almost
        # certainly an error page, a redirect stub, or a CAPTCHA challenge.
        raise FetchContentError(
            f"Response from {url} is suspiciously small ({len(response.content)} bytes) "
            "— likely a bot-detection or error page"
        )
    
def compute_url_hash(url: str) -> str:
    """Compute a stable SHA-256 hash of the URL for deduplication fast-path.
    Placed here because the URL is normalised by the time fetch_url runs
    (after redirect resolution). Using the final URL — not the submitted URL
    — means two different input URLs that redirect to the same page will
    correctly hash to the same value.
    Returns:
        64-character lowercase hex string.
    """
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Content extraction
# ---------------------------------------------------------------------------

def strip_boilerplate(html: str) -> str:
    """Extract the main text body from raw HTML, discarding navigation, ads,
    and other boilerplate.
    Strategy:
      1. Trafilatura — ML-based extractor trained on web pages. Handles most
         standard ATS platforms (Greenhouse, Lever, Workable) accurately.
      2. BeautifulSoup fallback — structural tag removal for pages where
         Trafilatura returns nothing (JS-rendered shells, unusual layouts).
    Args:
        html: Raw HTML string as returned by fetch_url().
    Returns:
        Plain text of the job posting body. Whitespace is normalised.
    """
    # --- 1. Trafilatura ---
    text = trafilatura.extract(
        html,
        include_comments=False,  # public comment sections are noise
        include_tables=True,     # salary bands, benefits grids
        include_formatting=False,
        favor_recall=True,       # capture more; precision matters less for embedding
        deduplicate=False,
    )

    if text and len(text.strip()) >= _MIN_CONTENT_CHARS:
        return _collapse_whitespace(text)

    logger.debug(
        "Trafilatura returned %d chars — falling back to BeautifulSoup",
        len(text.strip()) if text else 0,
    )

    # --- 2. BeautifulSoup fallback ---
    text = _bs4_extract(html)
    if len(text) >= _MIN_CONTENT_CHARS:
        return text

    raise FetchContentError(
        f"strip_boilerplate: both extractors returned fewer than "
        f"{_MIN_CONTENT_CHARS} characters ({len(text)} extracted) "
        "— page may be a JS shell, CAPTCHA, or bot-detection stub"
    )


def _bs4_extract(html: str) -> str:
    """Remove structural boilerplate tags then return all remaining text."""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all(_BS4_BOILERPLATE_TAGS):
        tag.decompose()
    return _collapse_whitespace(soup.get_text(separator="\n"))


def _collapse_whitespace(text: str) -> str:
    """Normalise whitespace for consistent downstream tokenisation.
    - Collapses 3+ consecutive newlines to one blank line.
    - Collapses tabs and multiple spaces within a line to a single space.
    """
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()