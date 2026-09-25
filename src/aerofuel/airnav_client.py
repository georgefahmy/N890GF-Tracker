#!/usr/bin/env python3
"""
airnav_client.py
Robust AirNav scraper, parser, and caching client for AeroFuel IQ.
Parses retail FBO fuel pricing (100LL SS/FS, UL94, 100UL, 100R, Mogas, Jet-A)
from AirNav (https://www.airnav.com/airport/{ICAO}).
Provides caching with TTL and polite request throttling.
"""

import html
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 "
    "(AeroFuel-IQ/2.4; Aviation-Research-Tool)"
)

DEFAULT_CACHE_TTL = 259200  # 3 days (3 * 24 * 3600 seconds)
DEFAULT_REQUEST_DELAY = 1.0  # 1 second between requests

NON_FBO_SLUGS = {
    'update-fuel', 'reportlinks', 'comment', 'link', 'subscribe',
    'ratings', 'submitphoto', 'comments', 'weather', 'charts',
    'notams', 'contacts', 'links', 'feed'
}


def _get_ssl_context(verify=True):
    """
    Build an SSLContext using certifi (if available) or system CA certs when verify=True,
    or an unverified SSLContext when verify=False.
    """
    if not verify:
        if hasattr(ssl, "_create_unverified_context"):
            return ssl._create_unverified_context()
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx

    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _urlopen_with_ssl_fallback(req, timeout=15):
    """
    Safely execute urllib.request.urlopen with SSL verification fallback.
    If SSL verification fails (e.g. self-signed certificates in chain, corporate proxy/VPN inspection,
    or missing root certificates), retries with an unverified SSL context so data fetching succeeds.
    """
    # Check if user explicitly disabled SSL verification via environment variable
    if os.environ.get("AIRNAV_SSL_VERIFY", "1").lower() in ("0", "false", "no"):
        try:
            return urllib.request.urlopen(req, timeout=timeout, context=_get_ssl_context(verify=False))
        except (TypeError, ValueError):
            return urllib.request.urlopen(req, timeout=timeout)

    try:
        ctx = _get_ssl_context(verify=True)
        return urllib.request.urlopen(req, timeout=timeout, context=ctx)
    except (TypeError, ValueError):
        # When mocked by unit tests that don't accept `context` keyword argument
        try:
            return urllib.request.urlopen(req, timeout=timeout)
        except Exception:
            raise
    except urllib.error.URLError as e:
        err_str = str(e)
        reason_str = str(getattr(e, "reason", ""))
        is_ssl_err = (
            "CERTIFICATE_VERIFY_FAILED" in err_str or
            "certificate verify failed" in err_str or
            "self-signed certificate" in err_str or
            "CERTIFICATE_VERIFY_FAILED" in reason_str or
            "certificate verify failed" in reason_str or
            "self-signed certificate" in reason_str or
            "SSLError" in type(getattr(e, "reason", None)).__name__ or
            isinstance(getattr(e, "reason", None), ssl.SSLError)
        )
        if is_ssl_err:
            try:
                return urllib.request.urlopen(req, timeout=timeout, context=_get_ssl_context(verify=False))
            except (TypeError, ValueError):
                return urllib.request.urlopen(req, timeout=timeout)
        raise
    except Exception as e:
        err_str = str(e)
        if "CERTIFICATE_VERIFY_FAILED" in err_str or "certificate verify failed" in err_str or "self-signed certificate" in err_str:
            try:
                return urllib.request.urlopen(req, timeout=timeout, context=_get_ssl_context(verify=False))
            except (TypeError, ValueError):
                return urllib.request.urlopen(req, timeout=timeout)
        raise


class AirNavHTMLStripper(HTMLParser):
    """Utility to strip tags and convert HTML table rows into structured cell lists."""
    def __init__(self):
        super().__init__()
        self.reset()
        self.strict = False
        self.convert_charrefs = True
        self.tables = []
        self._table_stack = []
        self._row_stack = []
        self._cell_stack = []

    @property
    def _current_table(self):
        return self._table_stack[-1] if self._table_stack else None

    @property
    def _current_row(self):
        return self._row_stack[-1] if self._row_stack else None

    @property
    def _current_cell(self):
        return self._cell_stack[-1] if self._cell_stack else None

    def handle_starttag(self, tag, attrs):
        t = tag.lower()
        if t == 'table':
            new_table = []
            self.tables.append(new_table)
            self._table_stack.append(new_table)
        elif t == 'tr':
            if self._table_stack:
                # Close any unclosed cells or rows for current table depth
                while len(self._row_stack) >= len(self._table_stack):
                    if len(self._cell_stack) >= len(self._row_stack):
                        self._cell_stack.pop()
                    self._row_stack.pop()
                new_row = []
                self._table_stack[-1].append(new_row)
                self._row_stack.append(new_row)
        elif t in ('td', 'th'):
            if self._table_stack:
                # If no active row in current table, automatically create one (browser-like auto tr)
                if len(self._row_stack) < len(self._table_stack):
                    new_row = []
                    self._table_stack[-1].append(new_row)
                    self._row_stack.append(new_row)

                while len(self._cell_stack) >= len(self._row_stack):
                    self._cell_stack.pop()
                new_cell = []
                self._row_stack[-1].append(new_cell)
                self._cell_stack.append(new_cell)

                # Check colspan attribute
                colspan = 1
                for attr_k, attr_v in attrs:
                    if attr_k.lower() == 'colspan' and attr_v:
                        try:
                            colspan = int(attr_v)
                        except (ValueError, TypeError):
                            colspan = 1
                if colspan > 1:
                    for _ in range(colspan - 1):
                        self._row_stack[-1].append([])
        elif t in ('br', 'p', 'div'):
            if self._cell_stack:
                for c in self._cell_stack:
                    c.append(' ')
        elif t == 'a':
            if self._cell_stack:
                for attr_k, attr_v in attrs:
                    if attr_k.lower() == 'href' and attr_v:
                        for c in self._cell_stack:
                            c.append(f' <a href="{attr_v}"> ')
        elif t == 'img':
            if self._cell_stack:
                alt_text = None
                for attr_k, attr_v in attrs:
                    if attr_k.lower() == 'alt' and attr_v and attr_v.strip():
                        alt_text = attr_v.strip()
                        break
                if not alt_text:
                    for attr_k, attr_v in attrs:
                        if attr_k.lower() == 'title' and attr_v and attr_v.strip():
                            alt_text = attr_v.strip()
                            break
                if alt_text:
                    for c in self._cell_stack:
                        c.append(f' {alt_text} ')

    def handle_endtag(self, tag):
        t = tag.lower()
        if t == 'table':
            if self._table_stack:
                self._table_stack.pop()
            if self._row_stack and len(self._row_stack) > len(self._table_stack):
                self._row_stack.pop()
            if self._cell_stack and len(self._cell_stack) > len(self._row_stack):
                self._cell_stack.pop()
        elif t == 'tr':
            if self._cell_stack and len(self._cell_stack) >= len(self._row_stack):
                self._cell_stack.pop()
            if self._row_stack:
                self._row_stack.pop()
        elif t in ('td', 'th'):
            if self._cell_stack and len(self._cell_stack) >= len(self._row_stack):
                self._cell_stack.pop()
        elif t in ('p', 'div'):
            if self._cell_stack:
                for c in self._cell_stack:
                    c.append(' ')
        elif t == 'a':
            if self._cell_stack:
                for c in self._cell_stack:
                    c.append(' </a> ')

    def handle_data(self, data):
        if self._cell_stack:
            for c in self._cell_stack:
                c.append(data)


def clean_text(text):
    """Normalize whitespace, strip embedded HTML tags, and unescape entities."""
    if not text:
        return ""
    text = html.unescape(text)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def normalize_fuel_type(raw_type):
    """
    Standardize raw fuel string to canonical aviation grade:
    - '100LL', '94UL', '100UL', '100R', 'Mogas', 'SAF', 'Jet-A'
    """
    if not raw_type:
        return None
    raw_lower = str(raw_type).lower().strip()

    # Sustainable Aviation Fuel (SAF)
    if 'saf' in raw_lower or 'sustainable aviation' in raw_lower:
        return 'SAF'

    # Jet-A / Turbine
    if 'jet' in raw_lower or 'turbine' in raw_lower:
        return 'Jet-A'

    # Unleaded / Alternative fuels
    if '94ul' in raw_lower or 'ul94' in raw_lower or '94 ul' in raw_lower or 'ul 94' in raw_lower or 'ul_94' in raw_lower or ('94' in raw_lower and ('unleaded' in raw_lower or 'octane' in raw_lower or 'ul' in raw_lower)):
        return '94UL'
    if '100ul' in raw_lower or 'ul100' in raw_lower or 'g100ul' in raw_lower or '100 ul' in raw_lower or 'ul_100' in raw_lower or ('100' in raw_lower and ('unleaded' in raw_lower or 'ul' in raw_lower) and 'll' not in raw_lower):
        return '100UL'
    if '100r' in raw_lower or 'r100' in raw_lower or 'swift 100r' in raw_lower or '100r swift' in raw_lower or 'swift fuel' in raw_lower or '100_r' in raw_lower:
        return '100R'
    if 'mogas' in raw_lower or 'autogas' in raw_lower or 'auto gas' in raw_lower or 'auto_gas' in raw_lower or 'auto fuel' in raw_lower or 'auto_fuel' in raw_lower or 'ethanol-free' in raw_lower or 'ethanol_free' in raw_lower or 'mo-gas' in raw_lower:
        return 'Mogas'

    # 100LL / Standard Avgas
    if ('100ll' in raw_lower or '100-ll' in raw_lower or '100_ll' in raw_lower or '100 ll' in raw_lower or
            'avgas' in raw_lower or 'low lead' in raw_lower or 'lowlead' in raw_lower or 'blue' in raw_lower or
            raw_lower.startswith('ll') or '_ll' in raw_lower or 'll_' in raw_lower):
        return '100LL'

    return None


def normalize_service_type(raw_service, default="Self-Serve"):
    """
    Standardize raw service string to 'Self-Serve' or 'Full-Serve'.
    """
    if not raw_service:
        return default
    raw_lower = str(raw_service).lower().replace('_', ' ').replace('-', ' ').strip()
    if re.search(r'\b(full|fs|truck|assisted|line|full service|full serve)\b', raw_lower) or raw_lower.startswith('full') or 'full' in raw_lower or 'assisted' in raw_lower or 'truck' in raw_lower:
        return "Full-Serve"
    if re.search(r'\b(self|ss|island|24/7|card|kiosk|self service|self serve|24 hr|24 hour)\b', raw_lower) or raw_lower.startswith('self') or 'self' in raw_lower or 'island' in raw_lower:
        return "Self-Serve"
    return default


def parse_price_val(raw_price):
    """Extract float fuel price from strings like '$6.15', '6.15/gal', '$5.999', '$6.5', '$6'."""
    if raw_price is None:
        return None
    if isinstance(raw_price, (int, float)):
        if 1.0 <= raw_price <= 35.0:
            return round(float(raw_price), 2)
        return None

    price_str = str(raw_price).strip()
    # Reject explicit negative prices like "$-5.00" or "-5.00"
    if re.search(r'-\s*\$?[0-9]', price_str):
        return None

    match = re.search(r'\$?\s*([0-9]+(?:\.[0-9]{1,3})?)', price_str)
    if match:
        try:
            val = float(match.group(1))
            if 1.0 <= val <= 35.0:  # Sensible physical bounds for aviation fuel
                return round(val, 2)
        except ValueError:
            pass
    return None


class AirNavClient:
    """
    Client for fetching and parsing aviation fuel rates from AirNav.com.
    Features:
    - Robust HTML table, matrix grid, and regex parsing for all FBOs and fuel grades
    - Multi-tier caching (memory + local file cache) with configurable TTL & stale fallback
    - Polite rate throttling between sequential requests
    """

    def __init__(self, cache_dir=None, cache_ttl=DEFAULT_CACHE_TTL, request_delay=DEFAULT_REQUEST_DELAY, user_agent=DEFAULT_USER_AGENT):
        self.base_url = "https://www.airnav.com"
        self.cache_ttl = cache_ttl
        self.request_delay = request_delay
        self.user_agent = user_agent
        self.last_request_time = 0.0

        if cache_dir is None:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            self.cache_dir = os.path.join(base_dir, ".airnav_cache")
        else:
            self.cache_dir = cache_dir

        self._memory_cache = {}

    def _throttle(self):
        """Ensure minimum delay between consecutive network calls to AirNav."""
        now = time.time()
        elapsed = now - self.last_request_time
        if elapsed < self.request_delay:
            time.sleep(self.request_delay - elapsed)
        self.last_request_time = time.time()

    def _get_cache_path(self, icao):
        clean_icao = re.sub(r'[^A-Z0-9]', '', icao.upper())
        return os.path.join(self.cache_dir, f"{clean_icao}.json")

    def get_from_cache(self, icao, allow_expired=False):
        """Retrieve airport fuel data from memory or disk cache."""
        clean_icao = icao.upper().strip()
        now = time.time()

        # 1. Check in-memory cache
        if clean_icao in self._memory_cache:
            entry, timestamp = self._memory_cache[clean_icao]
            if allow_expired or (now - timestamp < self.cache_ttl):
                return entry

        # 2. Check on-disk cache
        cache_file = self._get_cache_path(clean_icao)
        if os.path.exists(cache_file):
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    cached_obj = json.load(f)
                cached_time = cached_obj.get('_cached_at', 0)
                if allow_expired or (now - cached_time < self.cache_ttl):
                    data = cached_obj.get('data')
                    if data:
                        self._memory_cache[clean_icao] = (data, cached_time)
                        return data
            except Exception:
                pass
        return None

    def save_to_cache(self, icao, data):
        clean_icao = icao.upper().strip()
        now = time.time()
        self._memory_cache[clean_icao] = (data, now)
        try:
            os.makedirs(self.cache_dir, exist_ok=True)
            cache_file = self._get_cache_path(clean_icao)
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump({'_cached_at': now, 'icao': clean_icao, 'data': data}, f, indent=2)
        except Exception:
            pass

    def clear_cache(self):
        """Clear memory and disk cache."""
        self._memory_cache.clear()
        if os.path.exists(self.cache_dir):
            for fname in os.listdir(self.cache_dir):
                if fname.endswith('.json'):
                    try:
                        os.remove(os.path.join(self.cache_dir, fname))
                    except Exception:
                        pass

    def fetch_airport_html(self, icao):
        """Fetch raw HTML from AirNav for the given ICAO code."""
        clean_ident = icao.strip().upper()
        # In AirNav, US 4-letter ICAO starting with K can be queried directly e.g. /airport/KSQL
        url = f"{self.base_url}/airport/{clean_ident}"

        self._throttle()

        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
                "Sec-Ch-Ua-Mobile": "?0",
                "Sec-Ch-Ua-Platform": '"macOS"',
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Upgrade-Insecure-Requests": "1"
            }
        )

        try:
            with _urlopen_with_ssl_fallback(req, timeout=12) as response:
                html_bytes = response.read()
                return html_bytes.decode('utf-8', errors='ignore')
        except urllib.error.HTTPError as e:
            if e.code == 404:
                # If K-prefixed failed, try 3-letter FAA LID if applicable (e.g. K0Q5 -> 0Q5)
                if clean_ident.startswith('K') and len(clean_ident) in (4, 5):
                    alt_ident = clean_ident[1:]
                    alt_url = f"{self.base_url}/airport/{alt_ident}"
                    try:
                        req_alt = urllib.request.Request(alt_url, headers={"User-Agent": self.user_agent})
                        with _urlopen_with_ssl_fallback(req_alt, timeout=12) as response:
                            return response.read().decode('utf-8', errors='ignore')
                    except Exception:
                        pass
            raise
        except Exception as e:
            raise RuntimeError(f"Failed to fetch AirNav page for {icao}: {e}") from e

    def parse_airport_fuel(self, html_content, icao=None):
        """
        Parse AirNav airport HTML content and extract all FBO fuel rates, contact info, and airport specs.
        Returns a standardized dictionary ready for AeroFuel IQ.
        """
        if not html_content:
            return None

        html_str = html_content

        # 1. Basic Airport Metadata Extraction
        found_icao = icao
        if not found_icao:
            m_title = re.search(r'<title>AirNav:\s*([A-Z0-9]+)\s*-\s*([^<]+)</title>', html_str, re.IGNORECASE)
            if m_title:
                found_icao = m_title.group(1).upper()
            else:
                m_ident = re.search(r'FAA\s+Identifier:\s*</td>\s*<td[^>]*>([A-Z0-9]+)</td>', html_str, re.IGNORECASE)
                if m_ident:
                    found_icao = m_ident.group(1).upper()

        found_icao = (found_icao or "UNKNOWN").upper()

        # Airport Name
        name_match = re.search(r'<h1>([^<]+)</h1>', html_str, re.IGNORECASE)
        apt_name = clean_text(name_match.group(1)) if name_match else ""

        # CTAF / UNICOM
        ctaf_match = re.search(r'CTAF:\s*</td>\s*<td[^>]*>([0-9]{3}\.[0-9]{1,3})', html_str, re.IGNORECASE)
        ctaf_freq = float(ctaf_match.group(1)) if ctaf_match else None

        unicom_match = re.search(r'UNICOM:\s*</td>\s*<td[^>]*>([0-9]{3}\.[0-9]{1,3})', html_str, re.IGNORECASE)
        unicom_freq = float(unicom_match.group(1)) if unicom_match else None

        # 2. Extract FBO Sections
        fbos = []
        piston_prices = []
        fuels_available_set = set()

        fbo_blocks = self._extract_fbo_blocks(html_str, found_icao)

        for block in fbo_blocks:
            fbo_obj = self._parse_single_fbo_block(block, found_icao)
            if fbo_obj and (fbo_obj["fuels"] or (fbo_obj["name"] and fbo_obj["name"] != "Airport Fuel Facility")):
                fbos.append(fbo_obj)
                for f_key, f_data in fbo_obj["fuels"].items():
                    if f_data.get("price"):
                        fuels_available_set.add(f_data.get("type"))
                        if f_data.get("type") not in ("Jet-A", "SAF"):
                            piston_prices.append(f_data["price"])

        # Fallback table scanning if structured FBO block extraction returned 0 fuels
        if not piston_prices:
            fallback_fuels, fallback_fbo = self._scan_fuel_tables_fallback(html_str)
            if fallback_fuels:
                fbos.append(fallback_fbo)
                for f_key, f_data in fallback_fuels.items():
                    if f_data.get("price"):
                        fuels_available_set.add(f_data.get("type"))
                        if f_data.get("type") not in ("Jet-A", "SAF"):
                            piston_prices.append(f_data["price"])

        best_price = min(piston_prices) if piston_prices else None
        if "100LL" in fuels_available_set:
            primary_fuel = "100LL"
        elif piston_prices:
            piston_only = [f for f in sorted(list(fuels_available_set)) if f not in ("Jet-A", "SAF")]
            primary_fuel = piston_only[0] if piston_only else "None"
        else:
            primary_fuel = "None"

        return {
            "icao": found_icao,
            "name": apt_name,
            "ctaf_freq": ctaf_freq,
            "unicom_freq": unicom_freq,
            "fbos": fbos,
            "best_price": round(best_price, 2) if best_price else None,
            "primary_fuel": primary_fuel,
            "fuels_available": sorted(list(fuels_available_set)),
            "last_updated": time.strftime("%Y-%m-%d"),
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "source": "AirNav Live Feed"
        }

    def _extract_fbo_blocks(self, html_str, icao):
        """Split HTML into distinct FBO candidate blocks."""
        blocks = []
        if not html_str:
            return blocks

        # Match FBO anchor links /airport/{ICAO}/{SLUG} or /airport/{ALT_IDENT}/{SLUG}
        icao_alt = icao[1:] if icao.startswith('K') and len(icao) in (4, 5) else icao
        pat_icao = f"(?:{re.escape(icao)}|{re.escape(icao_alt)})"

        pattern = re.compile(
            r'<a\s+[^>]*href=["\'](?:https?://[^/]+)?/airport/' + pat_icao + r'/([A-Za-z0-9_\-]+)["\'][^>]*>([\s\S]*?)</a>',
            re.IGNORECASE
        )

        matches = []
        for m in pattern.finditer(html_str):
            slug = m.group(1).lower()
            if slug not in NON_FBO_SLUGS:
                matches.append(m)

        if matches:
            seen_slugs = set()
            unique_matches = []
            for m in matches:
                slug = m.group(1).lower()
                if slug not in seen_slugs:
                    seen_slugs.add(slug)
                    unique_matches.append(m)

            splits = [m.start() for m in unique_matches]
            splits.append(len(html_str))
            for i in range(len(splits) - 1):
                chunk = html_str[splits[i]:splits[i+1]]
                blocks.append(chunk)
        else:
            # Look for general FBO tables
            table_matches = re.findall(r'(<table[^>]*>.*?</table>)', html_str, re.IGNORECASE | re.DOTALL)
            for tm in table_matches:
                if any(k in tm.lower() for k in ('100ll', 'jet a', 'ul94', '100ul', '100r', 'mogas', 'fuel prices', 'self service', 'full service')):
                    blocks.append(tm)

        return blocks

    def _parse_single_fbo_block(self, block_html, icao):
        """Parse FBO name, phone, radio freq, notes, and fuel table from an FBO block."""
        # 1. FBO Name
        fbo_name = "Airport Fuel Facility"
        m_name = re.search(r'<a\s+[^>]*href=["\'](?:https?://[^/"\'>]+)?/airport/[^/]+/([A-Za-z0-9_\-]+)["\'][^>]*>([\s\S]*?)</a>', block_html, re.IGNORECASE)
        if m_name:
            cand = clean_text(re.sub(r'<[^>]+>', '', m_name.group(2)))
            if not cand:
                m_alt = re.search(r'<img\s+[^>]*\b(?:alt|title)=["\']([^"\']+)["\']', m_name.group(2), re.IGNORECASE)
                if m_alt:
                    cand = clean_text(m_alt.group(1))
            slug = m_name.group(1).lower()
            if cand and slug not in NON_FBO_SLUGS and "more info" not in cand.lower():
                fbo_name = cand
            else:
                sub_anchors = re.findall(r'<a\s+[^>]*href=["\'](?:https?://[^/"\'>]+)?/airport/[^/]+/' + re.escape(m_name.group(1)) + r'["\'][^>]*>([\s\S]*?)</a>', block_html, re.IGNORECASE)
                for sa in sub_anchors:
                    t = clean_text(re.sub(r'<[^>]+>', '', sa))
                    if not t:
                        m_sa_alt = re.search(r'<img\s+[^>]*\b(?:alt|title)=["\']([^"\']+)["\']', sa, re.IGNORECASE)
                        if m_sa_alt:
                            t = clean_text(m_sa_alt.group(1))
                    if t and "more info" not in t.lower():
                        fbo_name = t
                        break

        if fbo_name == "Airport Fuel Facility":
            m_header = re.search(r'<h[234][^>]*>([^<]+)</h[234]>', block_html, re.IGNORECASE)
            if m_header:
                fbo_name = clean_text(m_header.group(1))
            else:
                m_bold = re.search(r'<b>([^<]+)</b>', block_html, re.IGNORECASE)
                if m_bold:
                    cand = clean_text(m_bold.group(1))
                    if len(cand) > 3 and not any(k in cand.lower() for k in ('fuel', 'price', 'phone', 'unicom', 'guaranteed')):
                        fbo_name = cand

        # 2. Phone Number
        phone = "N/A"
        m_phone = re.search(r'(?:Phone|Tel|Telephone)?\s*:?\s*(\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4})', block_html, re.IGNORECASE)
        if m_phone:
            phone = m_phone.group(1).strip()

        # 3. Radio / UNICOM
        unicom = None
        m_freq = re.search(r'(?:UNICOM|Frequency|Freq|ASR|ARINC)\s*:?\s*([1-9]\d{2}\.\d{1,3})', block_html, re.IGNORECASE)
        if m_freq:
            unicom = m_freq.group(1).strip()

        # 4. Notes / Guarantee / Brand / Hours
        notes_parts = []
        fbo_brand = ""
        for brand in ('Titan', 'Phillips 66', 'Shell', 'Avfuel', 'AVFUEL', 'Epic', 'World Fuel Services', 'World Fuel', 'Chevron', 'ExxonMobil'):
            if brand.lower() in block_html.lower():
                fbo_brand = brand
                notes_parts.append(brand)
                break

        if '24/7' in block_html or '24-hour' in block_html or '24 hr' in block_html:
            notes_parts.append("24/7 self-serve access")

        if 'guaranteed' in block_html.lower():
            m_guar = re.search(r'Guaranteed\s+(?:price\s+)?through\s+([A-Za-z0-9\-\s,]+)', block_html, re.IGNORECASE)
            if m_guar:
                notes_parts.append(f"Guaranteed through {clean_text(m_guar.group(1))}")
            else:
                notes_parts.append("Guaranteed Price")

        quote_date = None
        m_quote = re.search(r'(?:Quote|Updated|As of)[:\s]+([0-9]{1,2}-[A-Za-z]{3}(?:-[0-9]{2,4})?|[0-9]{1,2}/[0-9]{1,2}(?:/[0-9]{2,4})?)', block_html, re.IGNORECASE)
        if m_quote:
            quote_date = m_quote.group(1)
            notes_parts.append(f"Quote: {quote_date}")
        else:
            m_date = re.search(r'(?<!through\s)\b([0-9]{1,2}-[A-Za-z]{3}(?:-[0-9]{2,4})?|[0-9]{1,2}/[0-9]{1,2}(?:/[0-9]{2,4})?)\b', block_html, re.IGNORECASE)
            if m_date and m_date.group(1).lower() not in ('jet-a', '100-ll'):
                quote_date = m_date.group(1)
                notes_parts.append(f"Quote: {quote_date}")

        if unicom:
            notes_parts.append(f"UNICOM: {unicom}")

        notes = " • ".join(notes_parts) if notes_parts else "Retail FBO Fuel & Line Services"

        # 5. Extract Fuels
        fuels_dict = self._extract_fuels_from_text_or_table(block_html)

        return {
            "name": fbo_name,
            "brand": fbo_brand,
            "phone": phone,
            "notes": notes,
            "quote_date": quote_date,
            "fuels": fuels_dict
        }

    def _extract_fuels_from_text_or_table(self, html_snippet):
        """Extract fuel dictionary with standardized keys (100LL_SS, 100LL_FS, etc.)."""
        fuels = {}

        # 1. First try structured HTML table parsing
        parser = AirNavHTMLStripper()
        try:
            parser.feed(html_snippet)
        except Exception:
            pass

        for table in parser.tables:
            matrix_parsed = self._parse_matrix_table(table, fuels)
            if not matrix_parsed:
                for row in table:
                    cells = [clean_text("".join(c)) for c in row]
                    if any(cells):
                        self._parse_row_into_fuels(cells, fuels)

        # 2. Also use robust regex search for standalone lines / text blocks
        fuel_patterns = [
            r'(?:^|[^\w])(100LL|94UL|UL94|100UL|G100UL|100R|MOGAS|SAF|JET[\s\-]?A)\s*(?:\(([^)]+)\)|([A-Za-z\s]+))?[:\s]+\$?\s*([0-9]+(?:\.[0-9]{1,3})?)',
            r'\$?\s*([0-9]+(?:\.[0-9]{1,3})?)\s+(?:for\s+)?(100LL|94UL|UL94|100UL|G100UL|100R|MOGAS|SAF|JET[\s\-]?A)\s*(?:\(([^)]+)\)|([A-Za-z\s]+))?'
        ]

        for pat in fuel_patterns:
            for m in re.finditer(pat, html_snippet, re.IGNORECASE):
                groups = m.groups()
                if '(100LL' in pat:
                    raw_type, s1, s2, raw_price = groups[0], groups[1], groups[2], groups[3]
                    raw_svc = s1 or s2 or ""
                else:
                    raw_price, raw_type, s1, s2 = groups[0], groups[1], groups[2], groups[3]
                    raw_svc = s1 or s2 or ""

                f_type = normalize_fuel_type(raw_type)
                price_val = parse_price_val(raw_price)
                if f_type and price_val:
                    svc = normalize_service_type(raw_svc, default="Self-Serve" if f_type != "Jet-A" else "Full-Serve")
                    self._add_fuel_entry(fuels, f_type, svc, price_val)

        return fuels

    def _parse_matrix_table(self, table, fuels_dict):
        """
        Parses AirNav matrix fuel tables where columns represent fuel grades
        and rows represent service types (FS, SS) with prices, or vice-versa.
        Maintains strict 1-to-1 column alignment across all empty and populated cells.
        """
        if not table or len(table) < 2:
            return False

        # Pattern A: Columns are fuel grades, rows are service types (Full-Serve, Self-Serve)
        header_row_idx = -1
        fuel_cols = {}

        for r_idx, row in enumerate(table):
            cells_text = [clean_text("".join(c)) for c in row]
            row_str = " ".join(cells_text).lower()
            if any(k in row_str for k in ('100ll', '94ul', 'ul94', '100ul', 'g100ul', '100r', 'mogas', 'jet', 'saf')):
                header_row_idx = r_idx
                current_fuel = None
                for c_idx, cell in enumerate(row):
                    c_text = clean_text("".join(cell))
                    f_type = normalize_fuel_type(c_text)
                    if f_type:
                        current_fuel = f_type
                        fuel_cols[c_idx] = f_type
                    elif current_fuel and not c_text:
                        fuel_cols[c_idx] = current_fuel
                    else:
                        current_fuel = None
                if fuel_cols:
                    break

        if header_row_idx != -1 and fuel_cols:
            found_any = False
            for row in table[header_row_idx + 1:]:
                cells_text = [clean_text("".join(c)) for c in row]
                if not any(cells_text):
                    continue

                # Determine service type for this row
                service_type = None
                first_cell = cells_text[0].lower() if cells_text else ""
                if any(k in first_cell for k in ('fs', 'full', 'line', 'truck', 'assisted')):
                    service_type = "Full-Serve"
                elif any(k in first_cell for k in ('ss', 'self', 'island', 'card', '24/7', 'kiosk')):
                    service_type = "Self-Serve"

                if not service_type:
                    # Check non-fuel cells in this row for service type indicator
                    for c_idx, c_text in enumerate(cells_text):
                        if c_idx not in fuel_cols:
                            c_low = c_text.lower()
                            if any(k in c_low for k in ('fs', 'full', 'line', 'truck', 'assisted')):
                                service_type = "Full-Serve"
                                break
                            elif any(k in c_low for k in ('ss', 'self', 'island', 'card', '24/7', 'kiosk')):
                                service_type = "Self-Serve"
                                break

                if not service_type:
                    continue

                for c_idx, f_type in fuel_cols.items():
                    if c_idx < len(row):
                        cell_text = clean_text("".join(row[c_idx]))
                        if not cell_text or any(dash in cell_text for dash in ('---', '--', 'n/a', 'none')):
                            continue
                        p_val = parse_price_val(cell_text)
                        if p_val is not None:
                            self._add_fuel_entry(fuels_dict, f_type, service_type, p_val)
                            found_any = True

            if found_any:
                return True

        # Pattern B: Columns are service types (Self-Serve, Full-Serve), rows are fuel grades (94UL, Jet A, etc.)
        svc_header_row_idx = -1
        svc_cols = {}

        for r_idx, row in enumerate(table):
            cells_text = [clean_text("".join(c)) for c in row]
            row_str = " ".join(cells_text).lower()
            if any(k in row_str for k in ('self', 'full', 'ss', 'fs')):
                for c_idx, cell in enumerate(row):
                    c_text = clean_text("".join(cell))
                    c_low = c_text.lower()
                    if any(k in c_low for k in ('fs', 'full', 'line', 'truck')):
                        svc_cols[c_idx] = "Full-Serve"
                    elif any(k in c_low for k in ('ss', 'self', 'island', 'card')):
                        svc_cols[c_idx] = "Self-Serve"
                if svc_cols:
                    svc_header_row_idx = r_idx
                    break

        if svc_header_row_idx != -1 and svc_cols:
            found_any = False
            for row in table[svc_header_row_idx + 1:]:
                cells_text = [clean_text("".join(c)) for c in row]
                if not any(cells_text):
                    continue

                # Find fuel type in this row
                f_type = None
                for c_idx, c_text in enumerate(cells_text):
                    if c_idx not in svc_cols:
                        cand = normalize_fuel_type(c_text)
                        if cand:
                            f_type = cand
                            break

                if not f_type:
                    continue

                for c_idx, svc in svc_cols.items():
                    if c_idx < len(row):
                        cell_text = clean_text("".join(row[c_idx]))
                        if not cell_text or any(dash in cell_text for dash in ('---', '--', 'n/a', 'none')):
                            continue
                        p_val = parse_price_val(cell_text)
                        if p_val is not None:
                            self._add_fuel_entry(fuels_dict, f_type, svc, p_val)
                            found_any = True

            if found_any:
                return True

        return False

    def _parse_row_into_fuels(self, cells, fuels_dict):
        """Analyze a list of table cells in a row to detect fuel type, price, and service."""
        row_text = " ".join(cells).lower()
        if not any(k in row_text for k in ('100ll', '94ul', 'ul94', '100ul', 'g100ul', '100r', 'mogas', 'saf', 'jet a', 'jet-a', 'jeta', 'turbine', 'avgas')):
            return

        # Check if individual cells contain distinct fuel types + prices
        distinct_fuels_found = False
        for cell in cells:
            cand_type = normalize_fuel_type(cell)
            cand_price = parse_price_val(cell)
            if cand_type and cand_price:
                svc = normalize_service_type(cell, default="Full-Serve" if cand_type in ("Jet-A", "SAF") else "Self-Serve")
                self._add_fuel_entry(fuels_dict, cand_type, svc, cand_price)
                distinct_fuels_found = True

        if distinct_fuels_found:
            return

        # Find the single fuel type in this row
        f_type = None
        f_idx = -1
        for idx, cell in enumerate(cells):
            cand = normalize_fuel_type(cell)
            if cand:
                f_type = cand
                f_idx = idx
                break

        if not f_type:
            return

        # Check if explicit service indicators exist in any cell
        service_type = None
        for cell in cells:
            if any(k in cell.lower() for k in ('self', 'ss', 'island', 'full', 'fs', 'truck')):
                service_type = normalize_service_type(cell)
                break

        sub_cells = cells[f_idx + 1:] if f_idx >= 0 else cells

        # If explicit service was given in the row (e.g. [100LL, $6.15, Self Service] or [100LL (Full Service), $6.85])
        if service_type:
            price_vals = [parse_price_val(c) for c in sub_cells if parse_price_val(c) is not None]
            if price_vals:
                self._add_fuel_entry(fuels_dict, f_type, service_type, price_vals[0])
            return

        # If no explicit service was specified, check positional columns (e.g. [Fuel, SS Price, FS Price])
        if len(sub_cells) == 2:
            p_ss = parse_price_val(sub_cells[0])
            p_fs = parse_price_val(sub_cells[1])
            if p_ss is not None or p_fs is not None:
                if p_ss is not None:
                    self._add_fuel_entry(fuels_dict, f_type, "Self-Serve", p_ss)
                if p_fs is not None:
                    self._add_fuel_entry(fuels_dict, f_type, "Full-Serve", p_fs)
                return

        price_vals = [parse_price_val(c) for c in sub_cells if parse_price_val(c) is not None]
        if price_vals:
            if len(price_vals) >= 2:
                self._add_fuel_entry(fuels_dict, f_type, "Self-Serve", price_vals[0])
                self._add_fuel_entry(fuels_dict, f_type, "Full-Serve", price_vals[1])
            else:
                default_svc = "Full-Serve" if f_type in ("Jet-A", "SAF") else "Self-Serve"
                self._add_fuel_entry(fuels_dict, f_type, default_svc, price_vals[0])

    def _add_fuel_entry(self, fuels_dict, f_type, service, price):
        """Generate canonical key and label for fuels dictionary."""
        svc_code = "SS" if service == "Self-Serve" else "FS"

        if f_type == "100LL":
            key = f"100LL_{svc_code}"
            label = f"100LL Avgas ({service})"
        elif f_type == "94UL":
            key = f"94UL_{svc_code}"
            label = f"94UL Unleaded ({service})"
        elif f_type == "100UL":
            key = f"100UL_{svc_code}"
            label = f"100UL Unleaded ({service})"
        elif f_type == "100R":
            key = f"100R_{svc_code}"
            label = f"100R Swift Fuel ({service})"
        elif f_type == "Mogas":
            key = f"MOGAS_{svc_code}"
            label = f"Mogas (Ethanol-Free {service})"
        elif f_type == "SAF":
            key = "SAF"
            label = f"SAF Sustainable Aviation Fuel ({service})"
        elif f_type == "Jet-A":
            key = "JET_A"
            label = f"Jet-A Turbine Fuel ({service})"
        else:
            key = f"{f_type}_{svc_code}"
            label = f"{f_type} ({service})"

        if key in fuels_dict:
            if price < fuels_dict[key]["price"]:
                fuels_dict[key]["price"] = price
        else:
            fuels_dict[key] = {
                "price": price,
                "type": f_type,
                "service": service,
                "label": label
            }

    def _scan_fuel_tables_fallback(self, html_str):
        """Fallback scanner when no standard FBO block headers were matched."""
        fuels = self._extract_fuels_from_text_or_table(html_str)
        if fuels:
            fbo = {
                "name": "AirNav Reported Fuel Island",
                "phone": "N/A",
                "notes": "AirNav Public Retail Fuel Feed",
                "fuels": fuels
            }
            return fuels, fbo
        return {}, None

    def get_airport_fuel(self, icao, force_refresh=False):
        """
        Fetch real-time fuel data for an airport ICAO.
        Uses cache unless expired or force_refresh is True.
        Uses the direct AirNav single-airport HTML scraper.
        """
        clean_icao = icao.strip().upper()
        if not force_refresh:
            cached = self.get_from_cache(clean_icao, allow_expired=False)
            if cached:
                cached["from_cache"] = True
                return cached

        # Direct AirNav single-airport HTML scraper
        try:
            html_content = self.fetch_airport_html(clean_icao)
            parsed = self.parse_airport_fuel(html_content, icao=clean_icao)
            if parsed:
                parsed["from_cache"] = False
                self.save_to_cache(clean_icao, parsed)
                return parsed
        except Exception as e:
            # If live network fetch failed, check if we have expired cache as emergency fallback
            cached_stale = self.get_from_cache(clean_icao, allow_expired=True)
            if cached_stale:
                cached_stale["from_cache"] = True
                cached_stale["_stale_fallback"] = True
                return cached_stale
            raise

        return None

    # Alias fetch_airport_fuel to get_airport_fuel for consistent API parity
    def fetch_airport_fuel(self, icao, force_refresh=False):
        """Alias for get_airport_fuel to query single-airport fuel prices directly."""
        return self.get_airport_fuel(icao, force_refresh=force_refresh)

    def fetch_local_fuel_html(self, airport_code):
        """
        Fetch raw HTML from AirNav local fuel page for the given airport code.
        Submits an HTTP POST to https://www.airnav.com/fuel/local.html with form-urlencoded body
        (s={airport_code}&maxage=0&submit=) matching AirNav's search form, with automatic
        fallback to HTTP GET query parameters (?s={airport_code}&maxage=0&submit=true).
        """
        clean_ident = airport_code.strip().upper()
        post_url = f"{self.base_url}/fuel/local.html"

        # Form-urlencoded POST payload matching <FORM action="/fuel/local.html" method=post>
        post_data = urllib.parse.urlencode({
            's': clean_ident,
            'maxage': '0',
            'submit': ''
        }).encode('utf-8')

        headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": self.base_url,
            "Referer": f"{self.base_url}/fuel/local.html",
            "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"macOS"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1"
        }

        self._throttle()

        def _is_results_html(html_text):
            if not html_text:
                return False
            lower_text = html_text.lower()
            # Check if this is only the raw search form without result data
            has_form = bool(re.search(r'<form\b[^>]*action=["\']?(?:/fuel/)?local\.html["\']?', lower_text))
            has_results = bool(
                'fuel prices within' in lower_text or
                re.search(r'within\s+[0-9]+(?:\.[0-9]+)?\s*miles', lower_text) or
                re.search(r'/airport/[a-z0-9]{3,5}', lower_text)
            )
            if has_form and not has_results:
                return False
            return True

        # 1. Primary Method: HTTP POST
        html_resp = None
        try:
            req = urllib.request.Request(post_url, data=post_data, headers=headers, method="POST")
            with _urlopen_with_ssl_fallback(req, timeout=15) as response:
                html_resp = response.read().decode('utf-8', errors='ignore')
                if _is_results_html(html_resp):
                    return html_resp
        except urllib.error.HTTPError as e:
            if e.code == 404 and clean_ident.startswith('K') and len(clean_ident) in (4, 5):
                alt_ident = clean_ident[1:]
                alt_post_data = urllib.parse.urlencode({'s': alt_ident, 'maxage': '0', 'submit': ''}).encode('utf-8')
                try:
                    req_alt = urllib.request.Request(post_url, data=alt_post_data, headers=headers, method="POST")
                    with _urlopen_with_ssl_fallback(req_alt, timeout=15) as resp_alt:
                        html_resp = resp_alt.read().decode('utf-8', errors='ignore')
                        if _is_results_html(html_resp):
                            return html_resp
                except Exception:
                    pass
        except Exception:
            pass

        # 2. Fallback Method: HTTP GET with query parameters
        get_url = f"{self.base_url}/fuel/local.html?s={urllib.parse.quote(clean_ident)}&maxage=0&submit=true"
        get_headers = dict(headers)
        get_headers.pop("Content-Type", None)
        get_headers.pop("Origin", None)
        self._throttle()

        try:
            req_get = urllib.request.Request(get_url, headers=get_headers)
            with _urlopen_with_ssl_fallback(req_get, timeout=15) as response:
                html_resp = response.read().decode('utf-8', errors='ignore')
                if _is_results_html(html_resp):
                    return html_resp
        except urllib.error.HTTPError as e:
            if e.code == 404 and clean_ident.startswith('K') and len(clean_ident) in (4, 5):
                alt_ident = clean_ident[1:]
                alt_get_url = f"{self.base_url}/fuel/local.html?s={urllib.parse.quote(alt_ident)}&maxage=0&submit=true"
                try:
                    req_alt_get = urllib.request.Request(alt_get_url, headers=get_headers)
                    with _urlopen_with_ssl_fallback(req_alt_get, timeout=15) as resp_alt_get:
                        html_resp = resp_alt_get.read().decode('utf-8', errors='ignore')
                        if _is_results_html(html_resp):
                            return html_resp
                except Exception:
                    pass
            raise
        except Exception as e:
            raise RuntimeError(f"Failed to fetch AirNav local fuel page for {airport_code}: {e}") from e

        # If html_resp was retrieved, return it (e.g. empty form or error page to be parsed cleanly)
        if html_resp:
            return html_resp

        raise RuntimeError(f"No results found on AirNav local fuel page for {airport_code}")

    def parse_local_fuel_html(self, html_content, source_airport=None):
        """
        Parse AirNav local fuel page (https://www.airnav.com/fuel/local.html)
        and extract all airport listings within the radius, their FBOs, brand networks,
        quote update dates, and fuel rates.
        Returns a standardized dictionary ready for AeroFuel IQ.
        """
        if not html_content:
            return None

        # 1. Extract radius and source airport from title/headers
        radius_miles = None
        extracted_source = None

        # Clean header text snippet to avoid issues with tags, entities (&nbsp;), or linebreaks
        header_sample = html_content[:15000] if html_content else ""
        clean_header = html.unescape(header_sample)
        clean_header = clean_header.replace('\xa0', ' ')
        clean_header = re.sub(r'<[^>]+>', ' ', clean_header)
        clean_header = re.sub(r'\s+', ' ', clean_header)

        # Regex on cleaned text: "Fuel prices within 30 miles of KSQL" / "within 45 NM of KSQL" / "within 30.5 miles of KSQL"
        m_title = re.search(
            r'(?:Fuel\s+prices\s+within|prices\s+within|within)\s+([0-9]+(?:\.[0-9]+)?)\s*(?:miles?|nautical\s+miles?|nm|mi)\s+(?:of|from)\s+([A-Za-z0-9]{3,5})\b',
            clean_header,
            re.IGNORECASE
        )
        if m_title:
            try:
                r_val = float(m_title.group(1))
                radius_miles = int(r_val) if r_val.is_integer() else round(r_val, 1)
            except Exception:
                radius_miles = None
            extracted_source = m_title.group(2).upper().strip()
        else:
            # Try raw HTML pattern matching in case tags weren't fully cleaned
            m_raw = re.search(
                r'(?:Fuel\s+prices\s+within|prices\s+within|within)\s+([0-9]+(?:\.[0-9]+)?)\s*(?:miles?|nautical\s+miles?|nm|mi)\s+(?:of|from)\s+(?:<[^>]+>)*([A-Za-z0-9]{3,5})\b',
                html_content,
                re.IGNORECASE
            )
            if m_raw:
                try:
                    r_val = float(m_raw.group(1))
                    radius_miles = int(r_val) if r_val.is_integer() else round(r_val, 1)
                except Exception:
                    radius_miles = None
                extracted_source = m_raw.group(2).upper().strip()
            else:
                m_rad_only = re.search(
                    r'(?:Fuel\s+prices\s+within|prices\s+within|within)\s+([0-9]+(?:\.[0-9]+)?)\s*(?:miles?|nautical\s+miles?|nm|mi)\b',
                    clean_header,
                    re.IGNORECASE
                )
                if m_rad_only:
                    try:
                        r_val = float(m_rad_only.group(1))
                        radius_miles = int(r_val) if r_val.is_integer() else round(r_val, 1)
                    except Exception:
                        radius_miles = None
                else:
                    m_rad_raw = re.search(
                        r'(?:Fuel\s+prices\s+within|prices\s+within|within)\s+([0-9]+(?:\.[0-9]+)?)\s*(?:miles?|nautical\s+miles?|nm|mi)\b',
                        html_content,
                        re.IGNORECASE
                    )
                    if m_rad_raw:
                        try:
                            r_val = float(m_rad_raw.group(1))
                            radius_miles = int(r_val) if r_val.is_integer() else round(r_val, 1)
                        except Exception:
                            radius_miles = None

        source_ident = (source_airport or extracted_source or "UNKNOWN").upper().strip()
        now_date = time.strftime("%Y-%m-%d")
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        # Check if html_content is just the search form without results
        lower_content = html_content.lower()
        has_form = bool(re.search(r'<form\b[^>]*action=["\']?(?:/fuel/)?local\.html["\']?', lower_content))
        has_results = bool(
            'fuel prices within' in lower_content or
            re.search(r'within\s+[0-9]+(?:\.[0-9]+)?\s*(?:miles?|nm|mi)', lower_content) or
            re.search(r'/airport/[a-z0-9]{3,5}', lower_content)
        )
        if has_form and not has_results:
            return {
                "success": False,
                "source_airport": source_ident,
                "radius_miles": radius_miles if radius_miles is not None else 45,
                "count": 0,
                "fetched_at": now_iso,
                "airports": [],
                "target": None
            }

        # 2. Table parsing using AirNavHTMLStripper
        parser = AirNavHTMLStripper()
        try:
            parser.feed(html_content)
        except Exception:
            pass

        airports_dict = {}  # icao -> apt dict
        current_apt = None

        for table in parser.tables:
            if not table or len(table) < 2:
                continue

            # 1. Ensure appropriate column headers on row 1 of the table to determine fuel types before assigning indices
            header_fuel_cols = []  # list of (col_idx, f_type) from row 1
            header_cells_cleaned = []
            header_row_idx = -1

            for r_idx, row in enumerate(table):
                cells_text = [clean_text("".join(c)) for c in row]
                row_str = " ".join(cells_text).lower()
                if any(k in row_str for k in ('100ll', 'g100ul', '100ul', 'ul94', '94ul', 'jet a', 'jet-a', 'saf', '100r', 'mogas', 'avgas')):
                    header_row_idx = r_idx
                    header_cells_cleaned = cells_text
                    for c_idx, cell in enumerate(row):
                        c_text = clean_text("".join(cell))
                        f_type = normalize_fuel_type(c_text)
                        if f_type:
                            header_fuel_cols.append((c_idx, f_type))
                    if header_fuel_cols:
                        break

            if not header_fuel_cols or header_row_idx == -1:
                continue

            def _build_row_fuel_map(data_row_cells):
                """
                Determine column index to fuel type mapping for a data row based on row 1 headers.
                Computes column offsets relative to the first header fuel column based on leading
                columns (ICAO, FBO name, Brand) to prevent column drift and misalignments.
                """
                if not header_fuel_cols or not data_row_cells:
                    return {}

                fuel_headers = [f_type for _, f_type in header_fuel_cols]
                num_data = len(data_row_cells)

                # Determine where the fuel data columns begin in the data row:
                if re.search(r'\$[0-9]+(?:\.[0-9]+)?|\bSS\b|\bFS\b', data_row_cells[0], re.IGNORECASE):
                    data_fuel_start = 0
                elif len(data_row_cells) >= 2 and re.search(r'\$[0-9]+(?:\.[0-9]+)?|\bSS\b|\bFS\b', data_row_cells[1], re.IGNORECASE):
                    data_fuel_start = 1
                elif len(data_row_cells) >= 4 and data_row_cells[2].strip() and not re.search(r'\$[0-9]+(?:\.[0-9]+)?|\bSS\b|\bFS\b', data_row_cells[2], re.IGNORECASE) and re.search(r'\$[0-9]+(?:\.[0-9]+)?|\bSS\b|\bFS\b', data_row_cells[3], re.IGNORECASE):
                    data_fuel_start = 3
                else:
                    data_fuel_start = 2

                mapping = {}
                for k, f_type in enumerate(fuel_headers):
                    target_col = data_fuel_start + k
                    if target_col < num_data:
                        mapping[target_col] = f_type
                return mapping

            # Process data rows after header
            for row in table[header_row_idx + 1:]:
                cells_text = [clean_text("".join(c)) for c in row]
                if not cells_text or not any(cells_text):
                    continue

                full_row_str = " ".join(cells_text)
                if not full_row_str.strip() or full_row_str.strip() == '---':
                    continue

                # Skip header/summary/average rows that show regional price averages or ranges (e.g. "$6.23—$13.75 average $7.81")
                if 'average' in full_row_str.lower() or 'avg' in full_row_str.lower() or re.search(r'\$?[0-9]+\.[0-9]{2}\s*[\-—–]\s*\$?[0-9]+\.[0-9]{2}', full_row_str):
                    continue

                # 1. First, check if this row contains fuel rates in the fuel columns
                row_fuel_map = _build_row_fuel_map(cells_text)
                row_fuels = {}
                for data_col, f_type in row_fuel_map.items():
                    if data_col < len(row):
                        cell_raw = "".join(row[data_col])
                        cell_text = clean_text(cell_raw)
                        if not cell_text or any(dash in cell_text.lower() for dash in ('---', '--', 'n/a', 'none')):
                            continue

                        # SS prices
                        m_ss = re.findall(r'\bSS\b[^\$0-9]*\$?\s*([0-9]+(?:\.[0-9]{1,3})?)', cell_text, re.IGNORECASE)
                        if not m_ss:
                            m_ss = re.findall(r'\$?\s*([0-9]+(?:\.[0-9]{1,3})?)[^\$0-9]*\bSS\b', cell_text, re.IGNORECASE)

                        # FS prices
                        m_fs = re.findall(r'\bFS\b[^\$0-9]*\$?\s*([0-9]+(?:\.[0-9]{1,3})?)', cell_text, re.IGNORECASE)
                        if not m_fs:
                            m_fs = re.findall(r'\$?\s*([0-9]+(?:\.[0-9]{1,3})?)[^\$0-9]*\bFS\b', cell_text, re.IGNORECASE)

                        all_prices = re.findall(r'\$?\s*([0-9]+\.[0-9]{2})', cell_text)

                        if m_ss or m_fs:
                            for p_str in m_ss:
                                p_val = parse_price_val(p_str)
                                if p_val:
                                    self._add_fuel_entry(row_fuels, f_type, "Self-Serve", p_val)

                            for p_str in m_fs:
                                p_val = parse_price_val(p_str)
                                if p_val:
                                    self._add_fuel_entry(row_fuels, f_type, "Full-Serve", p_val)

                            # Handle extra/discount prices in cell (e.g. nested discount boxes like $7.42 at KCVH)
                            matched_strs = set(m_ss + m_fs)
                            extra_prices = [p for p in all_prices if p not in matched_strs]
                            for p_str in extra_prices:
                                p_val = parse_price_val(p_str)
                                if p_val:
                                    if m_fs and not m_ss:
                                        self._add_fuel_entry(row_fuels, f_type, "Full-Serve", p_val)
                                    elif m_ss and not m_fs:
                                        self._add_fuel_entry(row_fuels, f_type, "Self-Serve", p_val)
                                    else:
                                        svc = "Full-Serve" if ("fs" in cell_text.lower() or "full" in cell_text.lower() or f_type in ("Jet-A", "SAF")) else "Self-Serve"
                                        self._add_fuel_entry(row_fuels, f_type, svc, p_val)
                        else:
                            # Neither m_ss nor m_fs explicitly matched in cell text
                            if len(all_prices) >= 2:
                                p_ss = parse_price_val(all_prices[0])
                                p_fs = parse_price_val(all_prices[1])
                                if p_ss:
                                    self._add_fuel_entry(row_fuels, f_type, "Self-Serve", p_ss)
                                if p_fs:
                                    self._add_fuel_entry(row_fuels, f_type, "Full-Serve", p_fs)
                            elif len(all_prices) == 1:
                                p_val = parse_price_val(all_prices[0])
                                if p_val:
                                    svc = "Full-Serve" if ("fs" in cell_text.lower() or "full" in cell_text.lower() or f_type in ("Jet-A", "SAF")) else "Self-Serve"
                                    self._add_fuel_entry(row_fuels, f_type, svc, p_val)

                # 2. If row has NO fuel rates, check if it's an airport header row
                if not row_fuels:
                    first_cell = cells_text[0] if cells_text else ""
                    raw_row_joined = "".join("".join(c) for c in row)
                    m_link = re.search(r'href=["\']?(?:https?://[^/"\'>]+)?/airport/([A-Za-z0-9]{3,5})(?:/|["\'\s>])', raw_row_joined)
                    cand_icao = None
                    dist_val = None
                    bearing_val = None

                    if m_link and m_link.group(1).upper() not in ('FUEL', 'PRICE', 'LOCAL', 'STATE', 'AIRNAV', 'UPDATE') and m_link.group(1).lower() not in NON_FBO_SLUGS:
                        cand_icao = m_link.group(1).upper()
                    else:
                        m_apt = re.search(r'\b([A-Z0-9]{3,5})\b(?:\s+([0-9]+(?:\.[0-9]+)?)\s*(N|NNE|NE|ENE|E|ESE|SE|SSE|S|SSW|SW|WSW|W|WNW|NW|NNW))?', first_cell)
                        if not m_apt or m_apt.group(1).lower() in NON_FBO_SLUGS or m_apt.group(1).upper() in ('FUEL', 'PRICE', 'LOCAL', 'STATE', 'AIRNAV', 'UPDATE', 'TABLE', 'GUARANTEED', 'AIRBOSS'):
                            m_apt = re.search(r'\b([A-Z0-9]{3,5})\b(?:\s+([0-9]+(?:\.[0-9]+)?)\s*(N|NNE|NE|ENE|E|ESE|SE|SSE|S|SSW|SW|WSW|W|WNW|NW|NNW))?', full_row_str)

                        if m_apt and m_apt.group(1).lower() not in NON_FBO_SLUGS and m_apt.group(1).upper() not in ('FUEL', 'PRICE', 'LOCAL', 'STATE', 'AIRNAV', 'UPDATE', 'TABLE', 'GUARANTEED', 'AIRBOSS'):
                            test_code = m_apt.group(1).upper()
                            if re.search(r',\s*[A-Z]{2}\b', full_row_str) or 'airport' in full_row_str.lower() or m_apt.group(2) or test_code == source_ident or (source_ident and test_code in (source_ident, source_ident[1:] if source_ident.startswith('K') else 'K' + source_ident)):
                                cand_icao = test_code

                    if cand_icao:
                        m_dist = re.search(r'([0-9]+(?:\.[0-9]+)?)\s*(N|NNE|NE|ENE|E|ESE|SE|SSE|S|SSW|SW|WSW|W|WNW|NW|NNW)\b', full_row_str)
                        if m_dist:
                            try:
                                dist_val = float(m_dist.group(1))
                            except Exception:
                                dist_val = None
                            bearing_val = m_dist.group(2)

                        m_loc = re.search(r'([A-Za-z0-9\s.,\'()/-]+(?:Airport|Airfield|Field|Heliport|Seaplane|Municipal|Intl|International|Regional|County|Center|Exec|Executive)[A-Za-z0-9\s.,\'()/-]*?)\s+([A-Za-z\s.]+),\s*([A-Z]{2})\b', full_row_str, re.IGNORECASE)
                        if m_loc:
                            apt_name = clean_text(m_loc.group(1))
                            apt_city = clean_text(m_loc.group(2))
                            apt_state = m_loc.group(3).upper()
                        else:
                            m_city_st = re.search(r'([A-Za-z\s.]+),\s*([A-Z]{2})\b', full_row_str)
                            if m_city_st:
                                apt_city = clean_text(m_city_st.group(1))
                                apt_state = m_city_st.group(2).upper()
                                name_part = full_row_str[:m_city_st.start()]
                                apt_name = clean_text(name_part)
                            else:
                                apt_name = f"{cand_icao} Airport"
                                apt_city = ""
                                apt_state = ""

                        # Strip leading ICAO code and distance/bearing from airport name
                        if apt_name:
                            apt_name = re.sub(r'^\s*' + re.escape(cand_icao) + r'\b', '', apt_name, flags=re.IGNORECASE).strip()
                            if dist_val is not None and bearing_val:
                                dist_int = int(dist_val) if dist_val.is_integer() else dist_val
                                apt_name = re.sub(r'^\s*' + re.escape(str(dist_int)) + r'\s+' + re.escape(bearing_val) + r'\b', '', apt_name, flags=re.IGNORECASE).strip()
                                apt_name = re.sub(r'^\s*' + re.escape(str(dist_val)) + r'\s+' + re.escape(bearing_val) + r'\b', '', apt_name, flags=re.IGNORECASE).strip()
                            apt_name = clean_text(apt_name)

                        clean_faa = cand_icao[1:] if (cand_icao.startswith("K") and len(cand_icao) == 4 and not cand_icao[1:].isdigit()) else cand_icao

                        if cand_icao not in airports_dict:
                            current_apt = {
                                "icao": cand_icao,
                                "faa": clean_faa,
                                "name": apt_name or f"{cand_icao} Airport",
                                "city": apt_city,
                                "state": apt_state,
                                "distance_nm": dist_val,
                                "bearing": bearing_val,
                                "fbos": [],
                                "best_price": None,
                                "primary_fuel": "None",
                                "fuels_available": [],
                                "last_updated": now_date,
                                "fetched_at": now_iso,
                                "source": "AirNav Local Fuel"
                            }
                            airports_dict[cand_icao] = current_apt
                        else:
                            current_apt = airports_dict[cand_icao]
                            if apt_name and (not current_apt.get("name") or current_apt["name"].endswith("Airport")):
                                current_apt["name"] = apt_name
                            if apt_city and not current_apt.get("city"):
                                current_apt["city"] = apt_city
                            if apt_state and not current_apt.get("state"):
                                current_apt["state"] = apt_state

                # 3. If row HAS fuel rates, add FBO to current_apt
                elif row_fuels:
                    first_cell_text = cells_text[0] if cells_text else ""
                    raw_row_joined = "".join("".join(c) for c in row)

                    # Check if this row also contains a new airport header
                    cand_row_icao = None
                    m_link = re.search(r'href=["\']?(?:https?://[^/"\'>]+)?/airport/([A-Za-z0-9]{3,5})(?:/|["\'\s>])', raw_row_joined)
                    if m_link and m_link.group(1).upper() not in ('FUEL', 'PRICE', 'LOCAL', 'STATE', 'AIRNAV', 'UPDATE') and m_link.group(1).lower() not in NON_FBO_SLUGS:
                        cand_row_icao = m_link.group(1).upper()
                    else:
                        m_row_apt = re.search(r'\b([A-Z0-9]{3,5})\b(?:\s+([0-9]+(?:\.[0-9]+)?)\s*(N|NNE|NE|ENE|E|ESE|SE|SSE|S|SSW|SW|WSW|W|WNW|NW|NNW))?', first_cell_text)
                        if m_row_apt and m_row_apt.group(1).lower() not in NON_FBO_SLUGS and m_row_apt.group(1).upper() not in ('FUEL', 'PRICE', 'LOCAL', 'STATE', 'AIRNAV', 'UPDATE', 'TABLE', 'GUARANTEED', 'AIRBOSS', 'SS', 'FS'):
                            if re.search(r',\s*[A-Z]{2}\b', full_row_str) or 'airport' in full_row_str.lower() or m_row_apt.group(2):
                                cand_row_icao = m_row_apt.group(1).upper()

                    if cand_row_icao and (current_apt is None or current_apt.get("icao") != cand_row_icao):
                        clean_faa = cand_row_icao[1:] if (cand_row_icao.startswith("K") and len(cand_row_icao) == 4 and not cand_row_icao[1:].isdigit()) else cand_row_icao
                        m_dist = re.search(r'([0-9]+(?:\.[0-9]+)?)\s*(N|NNE|NE|ENE|E|ESE|SE|SSE|S|SSW|SW|WSW|W|WNW|NW|NNW)\b', first_cell_text)
                        dist_val = float(m_dist.group(1)) if m_dist else None
                        bearing_val = m_dist.group(2) if m_dist else None

                        apt_name = clean_text(re.sub(r'^\s*' + re.escape(cand_row_icao) + r'\b', '', first_cell_text, flags=re.IGNORECASE))
                        if dist_val is not None and bearing_val:
                            dist_int = int(dist_val) if dist_val.is_integer() else dist_val
                            apt_name = clean_text(re.sub(r'^\s*' + re.escape(str(dist_int)) + r'\s+' + re.escape(bearing_val) + r'\b', '', apt_name, flags=re.IGNORECASE))
                            apt_name = clean_text(re.sub(r'^\s*' + re.escape(str(dist_val)) + r'\s+' + re.escape(bearing_val) + r'\b', '', apt_name, flags=re.IGNORECASE))

                        if cand_row_icao not in airports_dict:
                            current_apt = {
                                "icao": cand_row_icao,
                                "faa": clean_faa,
                                "name": apt_name or f"{cand_row_icao} Airport",
                                "city": "",
                                "state": "",
                                "distance_nm": dist_val,
                                "bearing": bearing_val,
                                "fbos": [],
                                "best_price": None,
                                "primary_fuel": "None",
                                "fuels_available": [],
                                "last_updated": now_date,
                                "fetched_at": now_iso,
                                "source": "AirNav Local Fuel"
                            }
                            airports_dict[cand_row_icao] = current_apt
                        else:
                            current_apt = airports_dict[cand_row_icao]
                            if dist_val is not None:
                                current_apt["distance_nm"] = dist_val
                                current_apt["bearing"] = bearing_val
                            if apt_name and (not current_apt.get("name") or current_apt["name"].endswith("Airport")):
                                current_apt["name"] = apt_name
                    elif current_apt is None:
                        current_apt = {
                            "icao": source_ident,
                            "faa": source_ident[1:] if (source_ident.startswith("K") and len(source_ident) == 4 and not source_ident[1:].isdigit()) else source_ident,
                            "name": f"{source_ident} Airport",
                            "city": "",
                            "state": "",
                            "distance_nm": None,
                            "bearing": None,
                            "fbos": [],
                            "best_price": None,
                            "primary_fuel": "None",
                            "fuels_available": [],
                            "last_updated": now_date,
                            "fetched_at": now_iso,
                            "source": "AirNav Local Fuel"
                        }
                        airports_dict[source_ident] = current_apt

                    first_cell_raw = "".join(row[0]) if row and len(row) > 0 else ""
                    first_cell_text = cells_text[0] if cells_text else ""
                    fbo_name = "Airport Fuel Facility"
                    fbo_brand = ""

                    FUEL_BRANDS = ('Titan', 'World Fuel Services', 'World Fuel', 'AVFUEL', 'Avfuel', 'Phillips 66', 'Shell', 'Epic', 'Chevron', 'ExxonMobil', 'Conoco', 'Total', 'AirBP', 'BP', 'independent')
                    FBO_CHAINS = ('Atlantic Aviation', 'Atlantic', 'Signature Aviation', 'Signature', 'Million Air', 'Tac Air', 'Jet Aviation', 'Ross Aviation', 'Cutter Aviation', 'Modern Aviation', 'Sheltair')

                    if len(row) > 1:
                        brand_cell_raw = "".join(row[1])
                        brand_cell_text = clean_text(brand_cell_raw)
                        for brand_name in FUEL_BRANDS:
                            if brand_name.lower() in brand_cell_text.lower():
                                fbo_brand = brand_name
                                break
                        if not fbo_brand and brand_cell_text:
                            if len(brand_cell_text) <= 30 and not any(dash in brand_cell_text for dash in ('---', '--', 'n/a')):
                                fbo_brand = brand_cell_text

                    if not fbo_brand:
                        for brand_name in FUEL_BRANDS:
                            if brand_name.lower() in full_row_str.lower():
                                fbo_brand = brand_name
                                break

                    # Priority 1: If there is an anchor tag in the first cell linking to /airport/{ICAO}/{SLUG} or /airport/...
                    m_fbo_link = re.search(r'<a\s+[^>]*href=["\'](?:https?://[^/]+)?/airport/[^/]+/([A-Za-z0-9_\-]+)["\'][^>]*>([\s\S]*?)</a>', first_cell_raw, re.IGNORECASE)
                    if m_fbo_link and m_fbo_link.group(1).lower() not in NON_FBO_SLUGS:
                        cand = clean_text(re.sub(r'<[^>]+>', '', m_fbo_link.group(2)))
                        if cand and "more info" not in cand.lower() and len(cand) > 2:
                            fbo_name = cand

                    # Priority 2: Text cleaning
                    if fbo_name == "Airport Fuel Facility" or fbo_name.lower() in ('independent', 'titan', 'avfuel', 'world fuel'):
                        cand_fbo_name = first_cell_text
                        if cand_fbo_name:
                            cand_fbo_name = re.sub(r'\b' + re.escape(current_apt["icao"]) + r'\b', '', cand_fbo_name)
                            if current_apt.get("distance_nm") and current_apt.get("bearing"):
                                cand_fbo_name = re.sub(r'\b\d+\s+' + re.escape(current_apt["bearing"]) + r'\b', '', cand_fbo_name)
                            # Strip auxiliary fuel supplier words
                            for b in ('independent', 'Titan', 'World Fuel Services', 'World Fuel', 'AVFUEL', 'Avfuel', 'Phillips 66', 'Shell', 'Epic', 'Chevron', 'ExxonMobil'):
                                cand_fbo_name = re.sub(r'\b' + re.escape(b) + r'\b', '', cand_fbo_name, flags=re.IGNORECASE)
                            cand_fbo_name = clean_text(cand_fbo_name)

                            if len(cand_fbo_name) > 2 and not any(k in cand_fbo_name.lower() for k in ('fuel', 'price', 'update', 'select', 'guaranteed', 'airboss')):
                                fbo_name = cand_fbo_name
                            else:
                                for chain in FBO_CHAINS:
                                    if chain.lower() in first_cell_text.lower():
                                        fbo_name = chain
                                        break
                                if fbo_name == "Airport Fuel Facility" and current_apt.get("name") and not current_apt["fbos"]:
                                    fbo_name = current_apt["name"]

                    # Deduplicate repeated name phrases (e.g. "Signature Aviation (Terminal 4) Signature Aviation (Terminal 4)")
                    words = fbo_name.split()
                    if len(words) >= 4 and len(words) % 2 == 0:
                        mid = len(words) // 2
                        if words[:mid] == words[mid:]:
                            fbo_name = " ".join(words[:mid])

                    # Extract quote timestamp or guarantee/airboss flags
                    quote_date = None
                    m_date = re.search(r'\b([0-9]{1,2}-[A-Za-z]{3}(?:-[0-9]{2,4})?|[0-9]{1,2}/[0-9]{1,2}(?:/[0-9]{2,4})?)\b', full_row_str)
                    if m_date and m_date.group(1).lower() not in ('jet-a', '100-ll'):
                        quote_date = m_date.group(1)

                    notes_parts = []
                    if fbo_brand:
                        notes_parts.append(fbo_brand)
                    if 'guaranteed' in full_row_str.lower():
                        notes_parts.append("Guaranteed Price")
                    if 'airboss' in full_row_str.lower():
                        notes_parts.append("Airboss")
                    if quote_date:
                        notes_parts.append(f"Quote: {quote_date}")

                    notes = " • ".join(notes_parts) if notes_parts else "Retail FBO Fuel & Line Services"

                    fbo_entry = {
                        "name": fbo_name,
                        "brand": fbo_brand,
                        "phone": "N/A",
                        "notes": notes,
                        "quote_date": quote_date,
                        "fuels": row_fuels
                    }
                    current_apt["fbos"].append(fbo_entry)

        # 3. Regex Fallback Parser for raw HTML blocks if table parsing found 0 airports
        if not airports_dict:
            airports_dict = self._extract_local_airports_regex(html_content, source_airport=source_ident)

        # 4. Finalize all airport objects: best_price, primary_fuel, fuels_available
        airports_list = []
        target_airport_obj = None

        for icao_key, apt in airports_dict.items():
            piston_prices = []
            fuels_set = set()

            for fbo in apt.get("fbos", []):
                for f_key, f_data in fbo.get("fuels", {}).items():
                    if isinstance(f_data, dict):
                        ftype = f_data.get("type")
                        pval = f_data.get("price")
                        if ftype and pval:
                            fuels_set.add(ftype)
                            if ftype not in ("Jet-A", "SAF"):
                                piston_prices.append(pval)

            apt["best_price"] = min(piston_prices) if piston_prices else None
            apt["fuels_available"] = sorted(list(fuels_set))
            if "100LL" in fuels_set:
                apt["primary_fuel"] = "100LL"
            elif piston_prices:
                piston_only = [f for f in apt["fuels_available"] if f not in ("Jet-A", "SAF")]
                apt["primary_fuel"] = piston_only[0] if piston_only else "None"
            else:
                apt["primary_fuel"] = "None"

            airports_list.append(apt)

            if source_ident:
                if icao_key == source_ident or apt.get("faa") == source_ident:
                    target_airport_obj = apt
                elif source_ident.startswith("K") and icao_key == source_ident[1:]:
                    target_airport_obj = apt
                elif not source_ident.startswith("K") and icao_key == ("K" + source_ident):
                    target_airport_obj = apt

        if not target_airport_obj and airports_list:
            target_airport_obj = airports_list[0]

        # Derive radius_miles if not parsed from title/header
        if radius_miles is None:
            all_distances = [apt["distance_nm"] for apt in airports_list if apt.get("distance_nm") is not None]
            if all_distances:
                import math
                radius_miles = int(math.ceil(max(all_distances)))
            else:
                radius_miles = 45

        return {
            "success": len(airports_list) > 0,
            "source_airport": source_ident,
            "radius_miles": radius_miles,
            "count": len(airports_list),
            "fetched_at": now_iso,
            "airports": airports_list,
            "target": target_airport_obj
        }

    def _extract_local_airports_regex(self, html_content, source_airport=None):
        """Fallback regex extractor for unstructured or non-table local fuel HTML."""
        airports_dict = {}
        now_date = time.strftime("%Y-%m-%d")
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        # Match airport anchor tags /airport/([A-Z0-9]{3,5})
        matches = list(re.finditer(r'<a\s+[^>]*href=["\'](?:https?://[^/]+)?/airport/([A-Za-z0-9]{3,5})["\'][^>]*>([\s\S]*?)</a>', html_content, re.IGNORECASE))
        if not matches:
            return airports_dict

        seen_icaos = []
        for m in matches:
            ident = m.group(1).upper().strip()
            if ident not in NON_FBO_SLUGS and ident not in ('LOCAL', 'FUEL', 'AIRNAV', 'UPDATE') and ident not in seen_icaos:
                seen_icaos.append(ident)

        for i, icao in enumerate(seen_icaos):
            # Extract text chunk for this airport
            start_pos = html_content.find(f"/airport/{icao}")
            end_pos = html_content.find(f"/airport/{seen_icaos[i+1]}") if i + 1 < len(seen_icaos) else len(html_content)
            chunk = html_content[start_pos:end_pos]

            m_dist = re.search(r'([0-9]+(?:\.[0-9]+)?)\s*(N|NNE|NE|ENE|E|ESE|SE|SSE|S|SSW|SW|WSW|W|WNW|NW|NNW)\b', chunk)
            dist_val = float(m_dist.group(1)) if m_dist else None
            bearing_val = m_dist.group(2) if m_dist else None

            m_name = re.search(r'<b>([^<]+)</b>', chunk)
            apt_name = clean_text(m_name.group(1)) if m_name else f"{icao} Airport"

            m_loc = re.search(r'([A-Za-z\s.]+),\s*([A-Z]{2})\b', chunk)
            apt_city = clean_text(m_loc.group(1)) if m_loc else ""
            apt_state = m_loc.group(2).upper() if m_loc else ""

            fuels = self._extract_fuels_from_text_or_table(chunk)
            fbo_name = "Airport Fuel Facility"
            for brand in ('Titan', 'World Fuel', 'AVFUEL', 'Phillips 66', 'Shell', 'Epic', 'Chevron', 'ExxonMobil', 'independent'):
                if brand.lower() in chunk.lower():
                    fbo_name = f"{brand} Fuel Island"
                    break

            fbos = []
            if fuels:
                fbos.append({
                    "name": fbo_name,
                    "phone": "N/A",
                    "notes": "AirNav Local Fuel Feed",
                    "fuels": fuels
                })

            clean_faa = icao[1:] if (icao.startswith("K") and len(icao) == 4 and not icao[1:].isdigit()) else icao
            airports_dict[icao] = {
                "icao": icao,
                "faa": clean_faa,
                "name": apt_name,
                "city": apt_city,
                "state": apt_state,
                "distance_nm": dist_val,
                "bearing": bearing_val,
                "fbos": fbos,
                "best_price": None,
                "primary_fuel": "None",
                "fuels_available": [],
                "last_updated": now_date,
                "fetched_at": now_iso,
                "source": "AirNav Local Fuel"
            }

        return airports_dict

    def fetch_local_fuel_prices(self, airport_code, force_refresh=False, use_cache=True):
        """
        Fetch fuel pricing for the given airport and all airports within its local search radius
        using the AirNav local fuel page (https://www.airnav.com/fuel/local.html?s={airport_code}&submit=true).
        Saves each discovered airport directly into individual <ICAO>.json cache records.
        Falls back to single-airport fetch if local fetch fails or yields 0 results.
        """
        clean_ident = airport_code.strip().upper()

        # 1. Fetch raw local fuel HTML
        try:
            html_content = self.fetch_local_fuel_html(clean_ident)
            parsed = self.parse_local_fuel_html(html_content, source_airport=clean_ident)
            if parsed and parsed.get("airports"):
                parsed["from_cache"] = False
                if use_cache:
                    for apt in parsed["airports"]:
                        apt_ident = (apt.get("icao") or apt.get("faa") or "").upper().strip()
                        if apt_ident:
                            self.save_to_cache(apt_ident, apt)
                return parsed
        except Exception as e:
            if use_cache and not force_refresh:
                cached_target = self.get_from_cache(clean_ident, allow_expired=True)
                if cached_target:
                    cached_target["from_cache"] = True
                    return {
                        "success": True,
                        "status": "ok",
                        "source_airport": clean_ident,
                        "radius_miles": 0,
                        "count": 1,
                        "fetched_at": cached_target.get("fetched_at"),
                        "data": cached_target,
                        "airports": [cached_target],
                        "target": cached_target,
                        "fallback": True,
                        "from_cache": True
                    }

            # Fallback to single airport get_airport_fuel
            try:
                single = self.get_airport_fuel(clean_ident, force_refresh=force_refresh)
                if single:
                    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    return {
                        "success": True,
                        "status": "ok",
                        "source_airport": clean_ident,
                        "radius_miles": 0,
                        "count": 1,
                        "fetched_at": single.get("fetched_at") or now_iso,
                        "data": single,
                        "airports": [single],
                        "target": single,
                        "fallback": True,
                        "from_cache": single.get("from_cache", False)
                    }
            except Exception:
                pass
            raise

        try:
            single = self.get_airport_fuel(clean_ident, force_refresh=force_refresh)
            if single:
                now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                return {
                    "success": True,
                    "status": "ok",
                    "source_airport": clean_ident,
                    "radius_miles": 0,
                    "count": 1,
                    "fetched_at": single.get("fetched_at") or now_iso,
                    "data": single,
                    "airports": [single],
                    "target": single,
                    "fallback": True,
                    "from_cache": single.get("from_cache", False)
                }
        except Exception:
            pass

        return None

    def batch_get_fuel(self, icaos, delay=None, force_refresh=False):
        """
        Fetch fuel data for multiple ICAOs in sequential batches with polite throttling.
        """
        if delay is not None:
            old_delay = self.request_delay
            self.request_delay = delay

        results = {}
        for icao in icaos:
            try:
                data = self.get_airport_fuel(icao, force_refresh=force_refresh)
                if data:
                    results[icao.upper()] = data
            except Exception as e:
                results[icao.upper()] = {
                    "icao": icao.upper(),
                    "error": str(e),
                    "fbos": [],
                    "best_price": None,
                    "fuels_available": [],
                    "primary_fuel": "None"
                }

        if delay is not None:
            self.request_delay = old_delay

        return results


# CLI Interface for testing / manual querying
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="AirNav Aviation Fuel Scraper Client")
    parser.add_argument("icaos", nargs="+", help="One or more airport ICAO codes (e.g. KSQL KPAO KHAF)")
    parser.add_argument("--local", action="store_true", help="Fetch all fuel prices within 45-mile radius (fuel/local.html)")
    parser.add_argument("--no-cache", dest="force_refresh", action="store_true", help="Bypass local cache")
    args = parser.parse_args()

    client = AirNavClient()
    print(f"📡 Querying fuel data for {len(args.icaos)} airport(s)...")
    for ident in args.icaos:
        try:
            if args.local:
                res = client.fetch_local_fuel_prices(ident, force_refresh=args.force_refresh)
            else:
                res = client.get_airport_fuel(ident, force_refresh=args.force_refresh)
            print(json.dumps(res, indent=2))
        except Exception as err:
            print(f"❌ Error fetching {ident}: {err}", file=sys.stderr)

