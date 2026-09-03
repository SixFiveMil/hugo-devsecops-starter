import os
import re
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Set
from tests.test_utils import (
    PUBLIC_DIR,
    CONTENT_DIR,
    ParsedHTML,
    get_all_html_pages,
    get_all_content_files,
    get_search_index,
    get_sitemap_urls,
    get_edge_security_headers,
)


class TestHugoSecurity(unittest.TestCase):
    pages: List[ParsedHTML] = []

    @classmethod
    def setUpClass(cls):
        cls.pages = get_all_html_pages()
        if not cls.pages:
            raise unittest.SkipTest("No HTML files found in public/. Run 'hugo' first.")

    def test_no_draft_leakage(self):
        """Ensure that markdown files marked draft: true are never compiled into public/."""
        content_files = get_all_content_files()
        draft_slugs = []
        for path, fm in content_files:
            if fm.get("draft", "").lower() == "true":
                slug = fm.get("slug", path.stem)
                draft_slugs.append((path, slug, fm.get("title", "")))

        if not draft_slugs:
            return

        search_index = get_search_index()
        search_titles = {item.get("title", "") for item in search_index}
        sitemap_urls = set(get_sitemap_urls())

        for path, slug, title in draft_slugs:
            with self.subTest(draft=path.name):
                matches = list(PUBLIC_DIR.glob(f"**/{slug}*"))
                self.assertEqual(
                    len(matches), 0,
                    f"Draft post '{path.name}' found in public artifacts: {matches}"
                )
                if title:
                    self.assertNotIn(
                        title, search_titles,
                        f"Draft title '{title}' leaked into search index (index.json)"
                    )

    def test_no_future_dated_posts_leakage(self):
        """Ensure scheduled/future posts are not published when buildFuture = false."""
        content_files = get_all_content_files()
        now = datetime.now(timezone.utc)
        future_posts = []

        for path, fm in content_files:
            if fm.get("draft", "").lower() == "true":
                continue
            date_str = fm.get("publishdate") or fm.get("date")
            if not date_str:
                continue
            try:
                clean_date = date_str.split()[0] if " " in date_str else date_str
                post_dt = datetime.fromisoformat(clean_date)
                if post_dt.tzinfo is None:
                    post_dt = post_dt.replace(tzinfo=timezone.utc)
                if post_dt > now:
                    slug = fm.get("slug", path.stem)
                    future_posts.append((path, slug, fm.get("title", "")))
            except Exception:
                continue

        if not future_posts:
            return

        search_index = get_search_index()
        search_titles = {item.get("title", "") for item in search_index}

        for path, slug, title in future_posts:
            with self.subTest(future_post=path.name):
                matches = list(PUBLIC_DIR.glob(f"**/{slug}*"))
                self.assertEqual(
                    len(matches), 0,
                    f"Future dated post '{path.name}' leaked into public/ artifacts: {matches}"
                )
                if title:
                    self.assertNotIn(
                        title, search_titles,
                        f"Future post title '{title}' leaked into search index (index.json)"
                    )

    def test_no_local_path_leakage(self):
        """Verify no local workstation filesystem paths or CI runner paths leak into public/."""
        forbidden_patterns = [
            re.compile(r"[A-Za-z]:\\[Uu]sers\\[A-Za-z0-9_.-]+", re.IGNORECASE),
            re.compile(r"/home/runner/work/", re.IGNORECASE),
            re.compile(r"/Users/[A-Za-z0-9_.-]+/(?:Documents|Desktop|Projects)", re.IGNORECASE),
        ]

        for page in self.pages:
            for pattern in forbidden_patterns:
                match = pattern.search(page.raw_content)
                self.assertIsNone(
                    match,
                    f"Local filesystem path leaked in {page.relpath}: '{match.group(0) if match else ''}'"
                )

    def test_no_sensitive_files_in_public(self):
        """Verify that .env, .git, lock files, or private keys are never copied to public/."""
        forbidden_extensions = {".env", ".key", ".pem", ".pfx", ".lock"}
        forbidden_names = {".git", ".gitignore", ".gitmodules", ".gitleaks.toml"}

        for p in PUBLIC_DIR.rglob("*"):
            if p.is_file():
                self.assertNotIn(
                    p.suffix.lower(), forbidden_extensions,
                    f"Sensitive file extension found in public: {p.relative_to(PUBLIC_DIR)}"
                )
                self.assertNotIn(
                    p.name.lower(), forbidden_names,
                    f"Sensitive filename found in public: {p.relative_to(PUBLIC_DIR)}"
                )

    def test_no_mixed_content_http_resources(self):
        """Ensure no assets or resources load via insecure unencrypted http://."""
        for page in self.pages:
            with self.subTest(page=page.relpath):
                for tag, attrs in page.all_tags:
                    for attr_name in ("src", "href", "action", "data"):
                        if attr_name in attrs:
                            val = attrs[attr_name].strip().lower()
                            if val.startswith("http://"):
                                if not any(local in val for local in ("localhost", "127.0.0.1", "schema.org", "w3.org", "purl.org")):
                                    self.fail(
                                        f"Insecure mixed-content HTTP link in {page.relpath} on <{tag} {attr_name}='{attrs[attr_name]}'>"
                                    )

    def test_subresource_integrity_on_cdn_assets(self):
        """Enforce Subresource Integrity (SRI) on all third-party CDN scripts and stylesheets."""
        cdn_domains = [
            "cdnjs.cloudflare.com",
            "cdn.jsdelivr.net",
            "unpkg.com",
            "stackpath.bootstrapcdn.com",
        ]

        for page in self.pages:
            for tag, attrs in page.all_tags:
                url_val = attrs.get("src", "") or attrs.get("href", "")
                if any(cdn in url_val for cdn in cdn_domains):
                    with self.subTest(page=page.relpath, resource=url_val):
                        self.assertIn(
                            "integrity", attrs,
                            f"Missing Subresource Integrity (SRI) attribute on CDN asset in {page.relpath}: {url_val}"
                        )
                        self.assertTrue(
                            attrs["integrity"].startswith("sha256-") or
                            attrs["integrity"].startswith("sha384-") or
                            attrs["integrity"].startswith("sha512-"),
                            f"Invalid SRI hash algorithm on {url_val} in {page.relpath}: {attrs['integrity']}"
                        )

    def test_external_links_tabnabbing_protection(self):
        """Verify that all external links with target='_blank' include rel='noopener' or rel='noreferrer'."""
        for page in self.pages:
            for a in page.anchor_tags:
                target = a.get("target", "").strip().lower()
                href = a.get("href", "").strip().lower()
                if target == "_blank" and (href.startswith("http://") or href.startswith("https://")):
                    rel = a.get("rel", "").strip().lower()
                    has_safe_rel = "noopener" in rel or "noreferrer" in rel
                    self.assertTrue(
                        has_safe_rel,
                        f"External link missing rel='noopener noreferrer' in {page.relpath}: href='{href}', target='{target}', rel='{rel}'"
                    )

    def test_no_dangerous_inline_event_handlers(self):
        """Scan HTML tags for dangerous inline execution handlers in content."""
        dangerous_handlers = {
            "onload", "onerror", "onclick", "onmouseover", "onfocus",
            "onblur", "onkeydown", "onkeyup", "onkeypress", "onsubmit",
        }

        for page in self.pages:
            with self.subTest(page=page.relpath):
                for tag, attrs in page.all_tags:
                    for handler in dangerous_handlers:
                        self.assertNotIn(
                            handler, attrs,
                            f"Dangerous inline event handler '{handler}' detected on <{tag}> in {page.relpath}"
                        )

                    href = attrs.get("href", "").strip().lower()
                    self.assertFalse(
                        href.startswith("javascript:"),
                        f"Dangerous javascript: URI detected on <{tag}> in {page.relpath}"
                    )

    def test_edge_security_headers(self):
        """Ensure public/_headers exists and configures defense-in-depth HTTP security headers."""
        headers_config = get_edge_security_headers()
        if not headers_config:
            self.skipTest("No public/_headers found; skipping edge header assertions.")

        self.assertIn("/*", headers_config, "public/_headers missing default '/*' route headers")
        root_headers = headers_config["/*"]
        expected_headers = [
            "x-content-type-options",
            "x-frame-options",
            "content-security-policy",
            "referrer-policy",
            "permissions-policy",
            "strict-transport-security",
        ]

        for h in expected_headers:
            self.assertIn(
                h, root_headers,
                f"Missing required security header '{h}' in public/_headers"
            )

        self.assertEqual(
            root_headers["x-content-type-options"].lower(), "nosniff",
            "X-Content-Type-Options must be 'nosniff'"
        )
        self.assertIn(
            root_headers["x-frame-options"].lower(), ["sameorigin", "deny"],
            "X-Frame-Options must be 'SAMEORIGIN' or 'DENY'"
        )


if __name__ == "__main__":
    unittest.main()
