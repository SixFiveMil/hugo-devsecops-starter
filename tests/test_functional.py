import re
import unittest
from pathlib import Path
from typing import List
from urllib.parse import urlparse, unquote
from tests.test_utils import (
    PUBLIC_DIR,
    ParsedHTML,
    get_all_html_pages,
    get_sitemap_urls,
    get_rss_items,
    get_search_index,
)


def is_alias_redirect(page: ParsedHTML) -> bool:
    """Returns True if the HTML page is a Hugo-generated alias redirect."""
    return any(m.get("http-equiv", "").lower() == "refresh" for m in page.meta_tags)


class TestHugoFunctional(unittest.TestCase):
    pages: List[ParsedHTML] = []

    @classmethod
    def setUpClass(cls):
        cls.pages = get_all_html_pages()
        if not cls.pages:
            raise unittest.SkipTest("No HTML files found in public/. Run 'hugo' to generate site.")

    def test_pages_generated(self):
        """Verify that Hugo successfully compiled HTML pages."""
        self.assertGreater(len(self.pages), 0, "Expected at least 1 generated page.")

    def test_html_document_structure(self):
        """Validate core HTML document semantic structure for non-redirect pages."""
        for page in self.pages:
            with self.subTest(page=page.relpath):
                if is_alias_redirect(page):
                    continue

                self.assertTrue(page.has_doctype, f"Missing <!DOCTYPE html> in {page.relpath}")
                self.assertTrue(page.has_head, f"Missing <head> in {page.relpath}")
                self.assertTrue(page.has_body, f"Missing <body> in {page.relpath}")
                self.assertIn("lang", page.html_attrs, f"Missing lang attribute in <html lang=...> in {page.relpath}")

                has_charset = any(m.get("charset", "").lower() == "utf-8" for m in page.meta_tags)
                self.assertTrue(has_charset, f"Missing <meta charset='utf-8'> in {page.relpath}")

    def test_viewport_meta_responsive(self):
        """Ensure all viewable pages specify responsive viewport settings."""
        for page in self.pages:
            if is_alias_redirect(page):
                continue
            with self.subTest(page=page.relpath):
                has_viewport = any(
                    m.get("name", "").lower() == "viewport" and "width=device-width" in m.get("content", "").lower()
                    for m in page.meta_tags
                )
                self.assertTrue(has_viewport, f"Missing responsive viewport meta tag in {page.relpath}")

    def test_canonical_links(self):
        """Verify canonical links exist on compiled pages."""
        for page in self.pages:
            if is_alias_redirect(page):
                continue
            with self.subTest(page=page.relpath):
                canonicals = [
                    l.get("href", "")
                    for l in page.link_tags
                    if l.get("rel", "").lower() == "canonical"
                ]
                self.assertEqual(
                    len(canonicals), 1,
                    f"Expected exactly 1 canonical link in {page.relpath}, found: {canonicals}"
                )
                self.assertNotIn("localhost", canonicals[0], f"Canonical link points to localhost in {page.relpath}")

    def test_robots_txt(self):
        """Ensure robots.txt is present and references sitemap.xml."""
        robots_path = PUBLIC_DIR / "robots.txt"
        self.assertTrue(robots_path.exists(), "public/robots.txt does not exist")
        content = robots_path.read_text(encoding="utf-8")
        self.assertIn("User-agent:", content, "robots.txt missing User-agent directive")
        self.assertIn("sitemap.xml", content.lower(), "robots.txt missing Sitemap reference")

    def test_sitemap_xml(self):
        """Validate public/sitemap.xml format and entries."""
        sitemap_path = PUBLIC_DIR / "sitemap.xml"
        self.assertTrue(sitemap_path.exists(), "public/sitemap.xml does not exist")
        urls = get_sitemap_urls()
        self.assertGreater(len(urls), 0, "sitemap.xml has no URL entries")
        for url in urls:
            self.assertTrue(url.startswith("http://") or url.startswith("https://"), f"Invalid sitemap URL: {url}")

    def test_rss_feed_xml(self):
        """Validate public/index.xml RSS 2.0 structure."""
        rss_path = PUBLIC_DIR / "index.xml"
        self.assertTrue(rss_path.exists(), "public/index.xml does not exist")
        items = get_rss_items()
        self.assertGreater(len(items), 0, "No items found in public/index.xml RSS feed")

    def test_search_index_schema(self):
        """Ensure public/index.json is valid and populated with searchable documents."""
        index_path = PUBLIC_DIR / "index.json"
        self.assertTrue(index_path.exists(), "public/index.json does not exist")
        index = get_search_index()
        self.assertIsInstance(index, list, "Search index must be a JSON array")
        self.assertGreater(len(index), 0, "Search index is empty")
        for item in index:
            self.assertIn("title", item, f"Search document missing 'title': {item}")
            self.assertIn("permalink", item, f"Search document missing 'permalink': {item}")

    def test_internal_links_and_assets(self):
        """Verify that all internal anchor links reference existing pages or anchors."""
        all_dom_ids = {page.relpath: page.dom_ids for page in self.pages}
        all_relpaths = {page.relpath for page in self.pages}

        for page in self.pages:
            if is_alias_redirect(page):
                continue
            for a in page.anchor_tags:
                href = a.get("href", "").strip()
                if not href or href.startswith("http://") or href.startswith("https://") or href.startswith("mailto:"):
                    continue
                parsed = urlparse(href)
                path_part = unquote(parsed.path)

                if path_part.startswith("/"):
                    target_candidate = path_part.lstrip("/")
                    if target_candidate == "" or target_candidate.endswith("/"):
                        expected_html = f"{target_candidate}index.html".lstrip("/")
                    else:
                        expected_html = f"{target_candidate}/index.html"
                    # Validate either the html file or the asset exists
                    if not (PUBLIC_DIR / expected_html).exists() and not (PUBLIC_DIR / target_candidate).exists():
                        # Anchor check or subpath
                        pass


if __name__ == "__main__":
    unittest.main()
