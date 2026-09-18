import os
import re
import json
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse

try:
    import tomllib  # Python 3.11+ standard library
except ImportError:
    try:
        import tomli as tomllib  # Fallback for Python < 3.11
    except ImportError:
        tomllib = None  # Fallback regex parser will be used

REPO_ROOT = Path(__file__).resolve().parent.parent
PUBLIC_DIR = REPO_ROOT / "public"
CONTENT_DIR = REPO_ROOT / "content"
STATIC_DIR = REPO_ROOT / "static"
ASSETS_DIR = REPO_ROOT / "assets"
LAYOUTS_DIR = REPO_ROOT / "layouts"
DATA_DIR = REPO_ROOT / "data"


class SiteConfig:
    """Encapsulates dynamically discovered Hugo configuration and DevSecOps overrides."""
    def __init__(self):
        self.base_url: str = "https://example.com/"
        self.domain: str = "example.com"
        self.title: str = "DevSecOps Hugo Starter"
        self.language_code: str = "en"
        self.build_drafts: bool = False
        self.build_future: bool = False
        self.params: Dict[str, Any] = {}
        self.cdn_domains: List[str] = [
            "cdnjs.cloudflare.com",
            "cdn.jsdelivr.net",
            "unpkg.com",
            "stackpath.bootstrapcdn.com",
            "maxcdn.bootstrapcdn.com",
        ]
        self.banned_js_frameworks: List[str] = [
            "react",
            "react-dom",
            "vue",
            "angular",
            "jquery",
            "svelte/internal",
            "backbone",
            "ember",
        ]
        self.require_security_txt: bool = False
        self.require_edge_headers: bool = False
        self.allowed_external_links: List[str] = []
        self._load_config()

    def _load_config(self):
        # 1. Inspect Hugo config files in priority order
        hugo_config_candidates = [
            REPO_ROOT / "hugo.toml",
            REPO_ROOT / "config.toml",
            REPO_ROOT / "hugo.yaml",
            REPO_ROOT / "config.yaml",
            REPO_ROOT / "hugo.json",
            REPO_ROOT / "config.json",
        ]

        for cand in hugo_config_candidates:
            if cand.exists():
                self._parse_hugo_file(cand)
                break

        # 2. Inspect optional .devsecops.json / devsecops.json / data/devsecops.json
        devsecops_json_candidates = [
            REPO_ROOT / ".devsecops.json",
            REPO_ROOT / "devsecops.json",
            DATA_DIR / "devsecops.json",
        ]

        for cand in devsecops_json_candidates:
            if cand.exists():
                try:
                    with open(cand, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if "canonical_domain" in data:
                        self.domain = data["canonical_domain"]
                    if "cdn_domains" in data:
                        self.cdn_domains = data["cdn_domains"]
                    if "banned_js_frameworks" in data:
                        self.banned_js_frameworks = data["banned_js_frameworks"]
                    if "require_security_txt" in data:
                        self.require_security_txt = bool(data["require_security_txt"])
                    if "require_edge_headers" in data:
                        self.require_edge_headers = bool(data["require_edge_headers"])
                except Exception:
                    pass
                break

        # Auto-detect security.txt presence
        if (PUBLIC_DIR / ".well-known" / "security.txt").exists() or (STATIC_DIR / ".well-known" / "security.txt").exists():
            self.require_security_txt = True

        # Auto-detect _headers presence
        if (PUBLIC_DIR / "_headers").exists() or (STATIC_DIR / "_headers").exists():
            self.require_edge_headers = True

        # Compute domain from baseURL
        if self.base_url:
            parsed = urlparse(self.base_url)
            if parsed.netloc:
                self.domain = parsed.netloc

    def _parse_hugo_file(self, path: Path):
        text = path.read_text(encoding="utf-8", errors="replace")
        if path.suffix in [".toml", ".TOML"]:
            if tomllib is not None:
                try:
                    data = tomllib.loads(text)
                    self.base_url = data.get("baseURL", self.base_url)
                    self.title = data.get("title", self.title)
                    self.language_code = data.get("locale") or data.get("languageCode", self.language_code)
                    self.build_drafts = data.get("buildDrafts", self.build_drafts)
                    self.build_future = data.get("buildFuture", self.build_future)
                    self.params = data.get("params", {})
                    return
                except Exception:
                    pass
            # Fallback regex for TOML
            m_base = re.search(r'baseURL\s*=\s*["\']([^"\']+)["\']', text)
            if m_base:
                self.base_url = m_base.group(1)
            m_title = re.search(r'title\s*=\s*["\']([^"\']+)["\']', text)
            if m_title:
                self.title = m_title.group(1)

        elif path.suffix in [".json", ".JSON"]:
            try:
                data = json.loads(text)
                self.base_url = data.get("baseURL", self.base_url)
                self.title = data.get("title", self.title)
                self.params = data.get("params", {})
            except Exception:
                pass


_SITE_CONFIG: Optional[SiteConfig] = None


def get_site_config() -> SiteConfig:
    global _SITE_CONFIG
    if _SITE_CONFIG is None:
        _SITE_CONFIG = SiteConfig()
    return _SITE_CONFIG


class ParsedHTML:
    """Structured representation of a parsed HTML document."""
    def __init__(self, filepath: Path, relpath: str, raw_content: str):
        self.filepath = filepath
        self.relpath = relpath
        self.raw_content = raw_content
        self.has_doctype = False
        self.html_attrs: Dict[str, str] = {}
        self.has_head = False
        self.has_body = False
        self.title: Optional[str] = None
        self._title_chars: List[str] = []
        self._in_title = False
        
        # Headings & text
        self.h1_tags: List[str] = []
        self.h2_tags: List[str] = []
        self.h3_tags: List[str] = []
        self._current_h1_chars: List[str] = []
        self._in_h1 = False
        self._current_h2_chars: List[str] = []
        self._in_h2 = False
        self._current_h3_chars: List[str] = []
        self._in_h3 = False

        # Tag collections
        self.meta_tags: List[Dict[str, str]] = []
        self.link_tags: List[Dict[str, str]] = []
        self.script_tags: List[Dict[str, str]] = []
        self.anchor_tags: List[Dict[str, str]] = []
        self.img_tags: List[Dict[str, str]] = []
        self.all_tags: List[Tuple[str, Dict[str, str]]] = []
        self.dom_ids: Set[str] = set()

        # Landmark semantics
        self.landmarks: Dict[str, int] = {
            "main": 0,
            "nav": 0,
            "header": 0,
            "footer": 0,
            "article": 0,
            "section": 0,
        }

    @property
    def is_alias_redirect(self) -> bool:
        """Returns True if this HTML file is a Hugo auto-generated alias redirect page."""
        return any(m.get("http-equiv", "").lower() == "refresh" for m in self.meta_tags)


class HugoHTMLParser(HTMLParser):
    """HTMLParser that populates a ParsedHTML instance."""
    def __init__(self, parsed: ParsedHTML):
        super().__init__(convert_charrefs=True)
        self.parsed = parsed

    def handle_decl(self, decl: str):
        if "html" in decl.lower():
            self.parsed.has_doctype = True

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]):
        attr_dict = {k.lower(): (v if v is not None else "") for k, v in attrs}
        tag_lower = tag.lower()
        self.parsed.all_tags.append((tag_lower, attr_dict))

        if "id" in attr_dict:
            self.parsed.dom_ids.add(attr_dict["id"])

        if tag_lower in self.parsed.landmarks:
            self.parsed.landmarks[tag_lower] += 1

        if tag_lower == "html":
            self.parsed.html_attrs = attr_dict
        elif tag_lower == "head":
            self.parsed.has_head = True
        elif tag_lower == "body":
            self.parsed.has_body = True
        elif tag_lower == "title":
            self.parsed._in_title = True
        elif tag_lower == "h1":
            self.parsed._in_h1 = True
            self.parsed._current_h1_chars = []
        elif tag_lower == "h2":
            self.parsed._in_h2 = True
            self.parsed._current_h2_chars = []
        elif tag_lower == "h3":
            self.parsed._in_h3 = True
            self.parsed._current_h3_chars = []
        elif tag_lower == "meta":
            self.parsed.meta_tags.append(attr_dict)
        elif tag_lower == "link":
            self.parsed.link_tags.append(attr_dict)
        elif tag_lower == "script":
            self.parsed.script_tags.append(attr_dict)
        elif tag_lower == "a":
            self.parsed.anchor_tags.append(attr_dict)
        elif tag_lower == "img":
            self.parsed.img_tags.append(attr_dict)

    def handle_endtag(self, tag: str):
        tag_lower = tag.lower()
        if tag_lower == "title":
            self.parsed._in_title = False
            self.parsed.title = "".join(self.parsed._title_chars).strip()
        elif tag_lower == "h1":
            self.parsed._in_h1 = False
            h1_text = "".join(self.parsed._current_h1_chars).strip()
            if h1_text:
                self.parsed.h1_tags.append(h1_text)
            else:
                self.parsed.h1_tags.append("")
        elif tag_lower == "h2":
            self.parsed._in_h2 = False
            h2_text = "".join(self.parsed._current_h2_chars).strip()
            if h2_text:
                self.parsed.h2_tags.append(h2_text)
        elif tag_lower == "h3":
            self.parsed._in_h3 = False
            h3_text = "".join(self.parsed._current_h3_chars).strip()
            if h3_text:
                self.parsed.h3_tags.append(h3_text)

    def handle_data(self, data: str):
        if self.parsed._in_title:
            self.parsed._title_chars.append(data)
        if self.parsed._in_h1:
            self.parsed._current_h1_chars.append(data)
        if self.parsed._in_h2:
            self.parsed._current_h2_chars.append(data)
        if self.parsed._in_h3:
            self.parsed._current_h3_chars.append(data)


_CACHED_PAGES: Optional[List[ParsedHTML]] = None


def get_all_html_pages() -> List[ParsedHTML]:
    """Parses and caches all HTML pages found in public/."""
    global _CACHED_PAGES
    if _CACHED_PAGES is not None:
        return _CACHED_PAGES

    if not PUBLIC_DIR.exists():
        raise FileNotFoundError(f"Hugo public directory not found at: {PUBLIC_DIR}. Run 'hugo' first.")

    pages = []
    for root, _, files in os.walk(PUBLIC_DIR):
        for f in sorted(files):
            if f.endswith(".html"):
                full_path = Path(root) / f
                rel_path = full_path.relative_to(PUBLIC_DIR).as_posix()
                try:
                    raw_text = full_path.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    raw_text = full_path.read_bytes().decode("utf-8", errors="replace")

                parsed = ParsedHTML(full_path, rel_path, raw_text)
                parser = HugoHTMLParser(parsed)
                parser.feed(raw_text)
                pages.append(parsed)

    _CACHED_PAGES = pages
    return _CACHED_PAGES


def reset_cache():
    """Resets the cached HTML pages and site configuration."""
    global _CACHED_PAGES, _SITE_CONFIG
    _CACHED_PAGES = None
    _SITE_CONFIG = None


def parse_frontmatter(file_content: str) -> Dict[str, Any]:
    """Extracts frontmatter key-values from markdown files."""
    match = re.search(r"^---\s*\n(.*?)\n---", file_content, re.DOTALL)
    if not match:
        return {}
    fm_text = match.group(1)
    data: Dict[str, Any] = {}
    for line in fm_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            key, val = line.split(":", 1)
            key = key.strip()
            val = val.strip().strip("\"'")
            data[key] = val
    return data


def get_all_content_files() -> List[Tuple[Path, Dict[str, Any]]]:
    """Returns list of (filepath, frontmatter_dict) for all markdown files under content/."""
    results = []
    if not CONTENT_DIR.exists():
        return results

    for root, _, files in os.walk(CONTENT_DIR):
        for f in files:
            if f.endswith(".md"):
                full_path = Path(root) / f
                content = full_path.read_text(encoding="utf-8", errors="replace")
                fm = parse_frontmatter(content)
                results.append((full_path, fm))
    return results


def get_all_template_files() -> List[Path]:
    """Returns list of all template files under layouts/."""
    if not LAYOUTS_DIR.exists():
        return []
    return [p for p in LAYOUTS_DIR.rglob("*") if p.is_file() and p.suffix in [".html", ".xml", ".json", ".txt"]]


def get_sitemap_urls() -> List[str]:
    """Extracts all <loc> entries from public/sitemap.xml."""
    sitemap_path = PUBLIC_DIR / "sitemap.xml"
    if not sitemap_path.exists():
        return []
    tree = ET.parse(sitemap_path)
    root = tree.getroot()
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    urls = []
    for loc in root.findall(".//sm:loc", ns) or root.findall(".//loc"):
        if loc.text:
            urls.append(loc.text.strip())
    return urls


def get_rss_items() -> List[Dict[str, str]]:
    """Extracts items from public/index.xml (RSS 2.0)."""
    rss_path = PUBLIC_DIR / "index.xml"
    if not rss_path.exists():
        return []
    tree = ET.parse(rss_path)
    root = tree.getroot()
    items = []
    for item in root.findall(".//channel/item"):
        title_el = item.find("title")
        link_el = item.find("link")
        items.append({
            "title": title_el.text if title_el is not None and title_el.text else "",
            "link": link_el.text if link_el is not None and link_el.text else "",
        })
    return items


def get_search_index() -> List[Dict[str, Any]]:
    """Loads and parses public/index.json if present."""
    index_path = PUBLIC_DIR / "index.json"
    if not index_path.exists():
        return []
    try:
        with open(index_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
            return []
    except Exception:
        return []


def get_edge_security_headers() -> Dict[str, Dict[str, str]]:
    """
    Parses standard edge _headers format (Cloudflare Pages, Netlify) into a mapping of:
    { path_pattern: { header_name: header_value } }
    """
    headers_file = PUBLIC_DIR / "_headers"
    if not headers_file.exists():
        headers_file = STATIC_DIR / "_headers"
    if not headers_file.exists():
        return {}

    sections: Dict[str, Dict[str, str]] = {}
    current_pattern = "/*"
    sections[current_pattern] = {}

    for line in headers_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("/") or line.startswith("/*"):
            current_pattern = line
            if current_pattern not in sections:
                sections[current_pattern] = {}
        elif ":" in line:
            h_name, h_val = line.split(":", 1)
            sections[current_pattern][h_name.strip().lower()] = h_val.strip()

    return sections


get_cloudflare_headers = get_edge_security_headers


def get_canonical_slugs_baseline() -> Optional[List[str]]:
    """Returns baseline list of canonical slugs from data/canonical_slugs.json if present."""
    candidates = [
        DATA_DIR / "canonical_slugs.json",
        REPO_ROOT / ".canonical_slugs.json",
    ]
    for cand in candidates:
        if cand.exists():
            try:
                with open(cand, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        return data
                    if isinstance(data, dict) and "slugs" in data:
                        return data["slugs"]
            except Exception:
                pass
    return None
