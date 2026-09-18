import re
import sys
import unittest
from pathlib import Path
from typing import List
from urllib.parse import urlparse, unquote

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.test_utils import (
    REPO_ROOT,
    CONTENT_DIR,
    PUBLIC_DIR,
    ParsedHTML,
    get_all_html_pages,
    get_sitemap_urls,
    get_rss_items,
    get_search_index,
    get_site_config,
)


class TestHugoFunctional(unittest.TestCase):
    pages: List[ParsedHTML] = []

    @classmethod
    def setUpClass(cls):
        cls.pages = get_all_html_pages()
        cls.config = get_site_config()
        if not cls.pages:
            raise unittest.SkipTest("No HTML files found in public/. Run 'hugo' to generate site.")

    def test_pages_generated(self):
        """Verify that Hugo successfully compiled HTML pages."""
        self.assertGreater(len(self.pages), 0, "Expected at least 1 generated page in public/.")

    def test_html_document_structure(self):
        """Validate core HTML document semantic structure for non-redirect pages."""
        for page in self.pages:
            with self.subTest(page=page.relpath):
                if page.is_alias_redirect:
                    self.assertTrue(page.has_doctype, f"Alias redirect page {page.relpath} missing DOCTYPE")
                    continue

                self.assertTrue(page.has_doctype, f"Missing <!DOCTYPE html> in {page.relpath}")
                self.assertTrue(page.has_head, f"Missing <head> in {page.relpath}")
                self.assertTrue(page.has_body, f"Missing <body> in {page.relpath}")
                self.assertIn("lang", page.html_attrs, f"Missing lang attribute on <html> in {page.relpath}")

                has_charset = any(m.get("charset", "").lower() == "utf-8" for m in page.meta_tags)
                self.assertTrue(has_charset, f"Missing <meta charset='utf-8'> in {page.relpath}")

    def test_viewport_meta_responsive(self):
        """Ensure all viewable pages specify responsive viewport settings."""
        for page in self.pages:
            if page.is_alias_redirect:
                continue
            with self.subTest(page=page.relpath):
                has_viewport = any(
                    m.get("name", "").lower() == "viewport" and "width=device-width" in m.get("content", "").lower()
                    for m in page.meta_tags
                )
                self.assertTrue(has_viewport, f"Missing responsive viewport meta tag in {page.relpath}")

    def test_page_titles(self):
        """Ensure every page has a meaningful, non-empty <title>."""
        for page in self.pages:
            with self.subTest(page=page.relpath):
                self.assertTrue(bool(page.title), f"Page {page.relpath} has empty or missing <title>")

    def test_seo_single_h1_per_page(self):
        """Enforce SEO & accessibility standards: every non-redirect page must have exactly one <h1> tag."""
        for page in self.pages:
            if page.is_alias_redirect:
                continue
            with self.subTest(page=page.relpath):
                self.assertEqual(
                    len(page.h1_tags), 1,
                    f"Expected exactly 1 <h1> tag in {page.relpath}, found {len(page.h1_tags)}: {page.h1_tags}"
                )

    def test_seo_image_alt_attributes(self):
        """Enforce WCAG & SEO standards: all <img> tags must possess a non-empty alt attribute."""
        for page in self.pages:
            if page.is_alias_redirect:
                continue
            with self.subTest(page=page.relpath):
                for img in page.img_tags:
                    self.assertIn(
                        "alt", img,
                        f"Missing alt attribute in {page.relpath}: img src='{img.get('src')}'"
                    )
                    alt_text = img.get("alt", "").strip()
                    self.assertTrue(
                        bool(alt_text),
                        f"Empty alt attribute in {page.relpath}: img src='{img.get('src')}'"
                    )

    def test_canonical_links(self):
        """Verify canonical links exist on compiled pages and do not point to localhost."""
        for page in self.pages:
            if page.is_alias_redirect:
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
                canon = canonicals[0]
                self.assertNotIn("localhost", canon, f"Canonical link points to localhost in {page.relpath}: {canon}")
                self.assertNotIn("127.0.0.1", canon, f"Canonical link points to 127.0.0.1 in {page.relpath}: {canon}")

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
            self.assertTrue(
                url.startswith("http://") or url.startswith("https://"),
                f"Invalid sitemap URL schema: {url}"
            )
            self.assertNotIn("localhost", url, f"Sitemap URL contains localhost: {url}")

    def test_rss_feed_xml(self):
        """Validate public/index.xml RSS 2.0 structure."""
        rss_path = PUBLIC_DIR / "index.xml"
        if not rss_path.exists():
            self.skipTest("No public/index.xml RSS feed generated.")
        items = get_rss_items()
        self.assertGreater(len(items), 0, "No items found in public/index.xml RSS feed")
        for item in items:
            self.assertTrue(item["title"], "RSS item has empty title")
            self.assertTrue(item["link"], "RSS item has empty link")

    def test_search_index_schema(self):
        """Ensure public/index.json is valid and populated with searchable documents."""
        index_path = PUBLIC_DIR / "index.json"
        if not index_path.exists():
            self.skipTest("No public/index.json search index generated.")
        index = get_search_index()
        self.assertIsInstance(index, list, "Search index must be a JSON array")
        self.assertGreater(len(index), 0, "Search index is empty")
        for item in index:
            self.assertIn("title", item, f"Search document missing 'title': {item}")
            self.assertIn("permalink", item, f"Search document missing 'permalink': {item}")

    def test_internal_links_and_assets(self):
        """Verify that every internal anchor link and local image references an existing resource."""
        for page in self.pages:
            if page.is_alias_redirect:
                continue
            with self.subTest(page=page.relpath):
                # Check internal anchor links
                for a in page.anchor_tags:
                    href = a.get("href", "").strip()
                    if not href or href.startswith(("http://", "https://", "mailto:", "tel:", "javascript:", "#")):
                        continue
                    parsed = urlparse(href)
                    path = unquote(parsed.path)
                    if path:
                        if path.startswith("/"):
                            target = PUBLIC_DIR / path.lstrip("/")
                        else:
                            target = page.filepath.parent / path

                        if target.is_dir():
                            exists = (target / "index.html").exists()
                        else:
                            exists = (
                                target.exists() or
                                (target.parent / (target.name + ".html")).exists() or
                                (PUBLIC_DIR / f"{path.strip('/')}.html").exists()
                            )
                        self.assertTrue(
                            exists,
                            f"Broken internal link '{href}' in {page.relpath} (target {target} not found)"
                        )

                # Check local images
                for img in page.img_tags:
                    src = img.get("src", "").strip()
                    if src and not src.startswith(("http://", "https://", "data:")):
                        parsed = urlparse(src)
                        path = unquote(parsed.path)
                        target = PUBLIC_DIR / path.lstrip("/") if path.startswith("/") else page.filepath.parent / path
                        self.assertTrue(
                            target.exists(),
                            f"Broken local image reference '{src}' in {page.relpath} (target {target} not found)"
                        )

    def test_no_unrendered_shortcodes(self):
        """Verify that raw Hugo shortcode markers were not leaked into the rendered HTML."""
        shortcode_regex = re.compile(r"(\{\{<|\{\{%|\{\{\s*\.|\>\}\}|%\}\})")
        for page in self.pages:
            with self.subTest(page=page.relpath):
                cleaned_content = re.sub(r"<(pre|code)[^>]*>.*?</\1>", "", page.raw_content, flags=re.DOTALL)
                match = shortcode_regex.search(cleaned_content)
                self.assertIsNone(
                    match,
                    f"Found unrendered Hugo template marker '{match.group(0) if match else ''}' in {page.relpath}"
                )

    def test_academic_citations(self):
        """Verify Google Scholar / Highwire Press citation tags if present."""
        pages_with_citations = [
            p for p in self.pages
            if any(m.get("name", "").startswith("citation_") for m in p.meta_tags)
        ]
        if not pages_with_citations:
            return  # Optional check if site does not publish academic papers

        for page in pages_with_citations:
            with self.subTest(page=page.relpath):
                meta_names = {m.get("name", ""): m.get("content", "") for m in page.meta_tags}
                self.assertIn("citation_title", meta_names, f"Missing citation_title in {page.relpath}")
                self.assertIn("citation_author", meta_names, f"Missing citation_author in {page.relpath}")
                if "citation_doi" in meta_names:
                    self.assertTrue(
                        meta_names["citation_doi"].startswith("10."),
                        f"Invalid citation_doi format in {page.relpath}: {meta_names['citation_doi']}"
                    )


if __name__ == "__main__":
    unittest.main()
