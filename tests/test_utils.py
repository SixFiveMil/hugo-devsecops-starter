import os
import re
import json
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
PUBLIC_DIR = REPO_ROOT / "public"
CONTENT_DIR = REPO_ROOT / "content"
STATIC_DIR = REPO_ROOT / "static"


class ParsedHTML:
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
        self.meta_tags: List[Dict[str, str]] = []
        self.link_tags: List[Dict[str, str]] = []
        self.script_tags: List[Dict[str, str]] = []
        self.anchor_tags: List[Dict[str, str]] = []
        self.img_tags: List[Dict[str, str]] = []
        self.all_tags: List[Tuple[str, Dict[str, str]]] = []
        self.dom_ids: Set[str] = set()


class HugoHTMLParser(HTMLParser):
    def __init__(self, parsed: ParsedHTML):
        super().__init__(convert_charrefs=True)
        self.parsed = parsed

    def handle_decl(self, decl: str):
        if "html" in decl.lower():
            self.parsed.has_doctype = True

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]):
        attr_dict = {k.lower(): (v if v is not None else "") for k, v in attrs}
        self.parsed.all_tags.append((tag.lower(), attr_dict))

        if "id" in attr_dict:
            self.parsed.dom_ids.add(attr_dict["id"])

        if tag == "html":
            self.parsed.html_attrs = attr_dict
        elif tag == "head":
            self.parsed.has_head = True
        elif tag == "body":
            self.parsed.has_body = True
        elif tag == "title":
            self.parsed._in_title = True
        elif tag == "meta":
            self.parsed.meta_tags.append(attr_dict)
        elif tag == "link":
            self.parsed.link_tags.append(attr_dict)
        elif tag == "script":
            self.parsed.script_tags.append(attr_dict)
        elif tag == "a":
            self.parsed.anchor_tags.append(attr_dict)
        elif tag == "img":
            self.parsed.img_tags.append(attr_dict)

    def handle_endtag(self, tag: str):
        if tag == "title":
            self.parsed._in_title = False
            self.parsed.title = "".join(self.parsed._title_chars).strip()

    def handle_data(self, data: str):
        if self.parsed._in_title:
            self.parsed._title_chars.append(data)


_CACHED_PAGES: Optional[List[ParsedHTML]] = None


def get_all_html_pages() -> List[ParsedHTML]:
    """Parses and caches all HTML pages found in the public/ directory."""
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
    """Resets the cached HTML pages."""
    global _CACHED_PAGES
    _CACHED_PAGES = None


def parse_frontmatter(file_content: str) -> Dict[str, str]:
    """Extracts frontmatter key-values from markdown files."""
    match = re.search(r"^---\s*\n(.*?)\n---", file_content, re.DOTALL)
    if not match:
        return {}
    fm_text = match.group(1)
    data = {}
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


def get_all_content_files() -> List[Tuple[Path, Dict[str, str]]]:
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


def get_search_index() -> List[Dict]:
    """Loads and parses public/index.json."""
    index_path = PUBLIC_DIR / "index.json"
    if not index_path.exists():
        return []
    with open(index_path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_edge_security_headers() -> Dict[str, Dict[str, str]]:
    """
    Parses standard edge _headers format (Cloudflare Pages, Netlify) into a mapping of:
    { path_pattern: { header_name: header_value } }
    """
    headers_file = PUBLIC_DIR / "_headers"
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
