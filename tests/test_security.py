import os
import re
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Set

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.test_utils import (
    REPO_ROOT,
    PUBLIC_DIR,
    CONTENT_DIR,
    ParsedHTML,
    get_all_html_pages,
    get_all_content_files,
    get_search_index,
    get_sitemap_urls,
    get_edge_security_headers,
    get_cloudflare_headers,
    get_site_config,
)


class TestHugoSecurity(unittest.TestCase):
    pages: List[ParsedHTML] = []

    @classmethod
    def setUpClass(cls):
        cls.pages = get_all_html_pages()
        cls.config = get_site_config()
        if not cls.pages:
            raise unittest.SkipTest("No HTML files found in public/. Run 'hugo' first.")

    def test_no_draft_leakage(self):
        """Ensure that markdown files marked draft: true are never compiled into public/."""
        content_files = get_all_content_files()
        draft_slugs = []
        for path, fm in content_files:
            if str(fm.get("draft", "")).lower() == "true":
                slug = fm.get("slug", path.stem)
                draft_slugs.append((path, slug, fm.get("title", "")))

        if not draft_slugs:
            return  # No drafts in content/

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
                for s_url in sitemap_urls:
                    self.assertNotIn(
                        slug, s_url,
                        f"Draft slug '{slug}' leaked into sitemap.xml: {s_url}"
                    )

    def test_no_future_dated_posts_leakage(self):
        """Ensure scheduled/future posts (publishDate > now) are not published when buildFuture = false."""
        if self.config.build_future:
            self.skipTest("buildFuture is enabled in Hugo configuration; skipping future post quarantine check.")

        content_files = get_all_content_files()
        now = datetime.now(timezone.utc)
        future_posts = []

        for path, fm in content_files:
            if str(fm.get("draft", "")).lower() == "true":
                continue
            date_str = fm.get("publishDate") or fm.get("publishdate") or fm.get("date")
            if not date_str:
                continue
            try:
                clean_date = str(date_str).split()[0] if " " in str(date_str) else str(date_str)
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
                matches = [p for p in self.pages if slug in p.relpath]
                self.assertEqual(
                    len(matches), 0,
                    f"Future-dated post '{path.name}' leaked into public artifacts: {[m.relpath for m in matches]}"
                )
                if title:
                    self.assertNotIn(
                        title, search_titles,
                        f"Future post title '{title}' leaked into search index (index.json)"
                    )

    def test_no_distribution_draft_leakage(self):
        """Ensure no private _distribution.md files, staging notes, or vault sync buffers leak into public/."""
        distribution_matches = (
            list(PUBLIC_DIR.glob("**/*_distribution*")) +
            list(PUBLIC_DIR.glob("**/distribution_drafts*")) +
            list(PUBLIC_DIR.glob("**/_vault_staging*")) +
            list(PUBLIC_DIR.glob("**/staging_notes*"))
        )
        self.assertEqual(
            len(distribution_matches), 0,
            f"Private editorial/distribution drafts leaked into public artifacts: {distribution_matches}"
        )

        search_index = get_search_index()
        for item in search_index:
            url = item.get("permalink", "")
            title = item.get("title", "")
            self.assertNotIn(
                "_distribution", url.lower(),
                f"Distribution draft URL leaked into search index: {url}"
            )
            self.assertFalse(
                title.lower().startswith("distribution:"),
                f"Distribution draft title leaked into search index: {title}"
            )

    def test_no_local_path_leakage(self):
        """Verify no local workstation filesystem paths or CI runner paths leak into public/."""
        forbidden_patterns = [
            (re.compile(r"[a-zA-Z]:\\[Uu]sers\\[a-zA-Z0-9_.-]+", re.IGNORECASE), "Windows Workstation Path"),
            (re.compile(r"/home/runner/work/", re.IGNORECASE), "GitHub Runner Workspace"),
            (re.compile(r"/Users/[a-zA-Z0-9_.-]+/(?:Documents|Desktop|Projects|repos)", re.IGNORECASE), "macOS Workstation Path"),
        ]

        text_extensions = {".html", ".js", ".json", ".xml", ".css", ".txt"}
        for root, _, files in os.walk(PUBLIC_DIR):
            for f in files:
                ext = Path(f).suffix.lower()
                if ext in text_extensions:
                    file_path = Path(root) / f
                    rel_path = file_path.relative_to(PUBLIC_DIR).as_posix()
                    content = file_path.read_text(encoding="utf-8", errors="replace")
                    for pattern, desc in forbidden_patterns:
                        match = pattern.search(content)
                        self.assertIsNone(
                            match,
                            f"Workstation path disclosure ({desc}: '{match.group(0) if match else ''}') leaked in {rel_path}"
                        )

    def test_no_sensitive_files_in_public(self):
        """Verify that .env, .git, lock files, or private keys are never copied to public/."""
        forbidden_extensions = {".env", ".key", ".pem", ".pfx", ".lock"}
        forbidden_names = {
            ".git", ".gitignore", ".gitmodules", ".gitleaks.toml",
            ".hugo_build.lock", ".ds_store", "thumbs.db"
        }
        private_key_pattern = re.compile(r"-----BEGIN (?:RSA|OPENSSH|EC|DSA|PGP|PRIVATE) KEY-----")

        for root, _, files in os.walk(PUBLIC_DIR):
            for f in files:
                lower_name = f.lower()
                file_path = Path(root) / f
                rel_path = file_path.relative_to(PUBLIC_DIR).as_posix()

                self.assertNotIn(
                    file_path.suffix.lower(), forbidden_extensions,
                    f"Sensitive file extension found in public: {rel_path}"
                )
                self.assertNotIn(
                    lower_name, forbidden_names,
                    f"Sensitive filename found in public: {rel_path}"
                )

                if f.endswith((".html", ".json", ".txt", ".xml", ".js", ".css")):
                    content = file_path.read_text(encoding="utf-8", errors="replace")
                    match = private_key_pattern.search(content)
                    self.assertIsNone(
                        match,
                        f"Private key header found in public artifact: {rel_path}"
                    )

    def test_subresource_integrity_on_cdn_assets(self):
        """Enforce Subresource Integrity (SRI) on all third-party CDN scripts and stylesheets."""
        cdn_domains = tuple(self.config.cdn_domains)

        for page in self.pages:
            with self.subTest(page=page.relpath):
                # Audit external scripts
                for script in page.script_tags:
                    src = script.get("src", "")
                    if any(domain in src for domain in cdn_domains):
                        integrity = script.get("integrity", "")
                        crossorigin = script.get("crossorigin", "")
                        self.assertTrue(
                            integrity.startswith(("sha256-", "sha384-", "sha512-")),
                            f"CDN script missing valid SRI integrity hash in {page.relpath}: {src}"
                        )
                        self.assertEqual(
                            crossorigin.lower(), "anonymous",
                            f"CDN script missing crossorigin='anonymous' in {page.relpath}: {src}"
                        )

                # Audit external stylesheets
                for link in page.link_tags:
                    href = link.get("href", "")
                    rel = link.get("rel", "")
                    if "stylesheet" in rel and any(domain in href for domain in cdn_domains):
                        integrity = link.get("integrity", "")
                        crossorigin = link.get("crossorigin", "")
                        self.assertTrue(
                            integrity.startswith(("sha256-", "sha384-", "sha512-")),
                            f"CDN stylesheet missing valid SRI integrity hash in {page.relpath}: {href}"
                        )
                        self.assertEqual(
                            crossorigin.lower(), "anonymous",
                            f"CDN stylesheet missing crossorigin='anonymous' in {page.relpath}: {href}"
                        )

    def test_external_links_tabnabbing_protection(self):
        """Verify that all external links with target='_blank' include rel='noopener' or rel='noreferrer'."""
        for page in self.pages:
            with self.subTest(page=page.relpath):
                for a in page.anchor_tags:
                    target = a.get("target", "").strip().lower()
                    href = a.get("href", "").strip().lower()
                    if target == "_blank" and (href.startswith("http://") or href.startswith("https://")):
                        rel = a.get("rel", "").strip().lower().split()
                        has_safe_rel = "noopener" in rel or "noreferrer" in rel
                        self.assertTrue(
                            has_safe_rel,
                            f"Reverse tabnabbing vulnerability: <a target='_blank'> missing rel='noopener noreferrer' for href='{href}' in {page.relpath}"
                        )

    def test_no_mixed_content_http_resources(self):
        """Ensure no assets or resources load via insecure unencrypted http://."""
        resource_tags = [
            ("img", "src"),
            ("script", "src"),
            ("link", "href"),
            ("iframe", "src"),
            ("audio", "src"),
            ("video", "src"),
            ("source", "src"),
            ("form", "action"),
        ]

        allowed_schemes = ("localhost", "127.0.0.1", "schema.org", "w3.org", "purl.org", "xmlns")

        for page in self.pages:
            with self.subTest(page=page.relpath):
                for tag, attrs in page.all_tags:
                    for r_tag, r_attr in resource_tags:
                        if tag == r_tag and r_attr in attrs:
                            val = attrs[r_attr].strip().lower()
                            if val.startswith("http://"):
                                if not any(allowed in val for allowed in allowed_schemes):
                                    self.fail(
                                        f"Insecure mixed-content HTTP link in {page.relpath} on <{tag} {r_attr}='{attrs[r_attr]}'>"
                                    )

    def test_no_dangerous_inline_event_handlers(self):
        """Scan HTML tags for dangerous inline execution handlers in content."""
        dangerous_handlers = {
            "onload", "onerror", "onclick", "onmouseover", "onfocus",
            "onfocusin", "onfocusout", "onblur", "onkeydown", "onkeyup",
            "onkeypress", "onsubmit", "onunload", "onbeforeunload",
            "onmouseenter", "onmouseleave"
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
            if self.config.require_edge_headers:
                self.fail("Missing public/_headers or static/_headers security header configuration")
            else:
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

    def test_mermaid_security_strict(self):
        """Verify Mermaid configuration strictly uses securityLevel: 'strict'."""
        for page in self.pages:
            if "mermaid" in page.raw_content.lower():
                with self.subTest(page=page.relpath):
                    self.assertNotIn(
                        "securityLevel: 'loose'", page.raw_content,
                        f"Insecure mermaid securityLevel: 'loose' found in {page.relpath}"
                    )
                    self.assertNotIn(
                        'securityLevel: "loose"', page.raw_content,
                        f"Insecure mermaid securityLevel: 'loose' found in {page.relpath}"
                    )

    def test_security_txt_rfc9116(self):
        """Verify RFC 9116 security.txt exists in public/.well-known/ and complies with standard."""
        security_txt = PUBLIC_DIR / ".well-known" / "security.txt"
        if not security_txt.exists():
            if self.config.require_security_txt:
                self.fail("Missing RFC 9116 public/.well-known/security.txt file")
            else:
                self.skipTest("No security.txt found and not marked as required.")

        content = security_txt.read_text(encoding="utf-8")
        directives = {}
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" in line:
                k, v = line.split(":", 1)
                directives[k.strip().lower()] = v.strip()

        self.assertIn("contact", directives, "Missing mandatory 'Contact:' directive in security.txt")
        self.assertIn("expires", directives, "Missing mandatory 'Expires:' directive in security.txt")

        contact_val = directives["contact"]
        self.assertTrue(
            contact_val.startswith("https://") or contact_val.startswith("mailto:"),
            f"Contact URI must be an https:// or mailto: scheme, got '{contact_val}'"
        )

        expires_str = directives["expires"]
        try:
            expires_dt = datetime.fromisoformat(expires_str.replace("Z", "+00:00"))
            self.assertGreater(
                expires_dt, datetime.now(timezone.utc),
                f"security.txt Expires timestamp '{expires_str}' is in the past"
            )
        except ValueError as err:
            self.fail(f"Invalid ISO 8601 Expires timestamp in security.txt: {err}")

        if "canonical" in directives:
            self.assertTrue(directives["canonical"].startswith("https://"))
        if "policy" in directives:
            self.assertTrue(directives["policy"].startswith("https://"))


if __name__ == "__main__":
    unittest.main()
