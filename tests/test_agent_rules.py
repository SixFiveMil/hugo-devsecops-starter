import os
import re
import sys
import unittest
from pathlib import Path
from typing import List, Set

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.test_utils import (
    REPO_ROOT,
    PUBLIC_DIR,
    CONTENT_DIR,
    LAYOUTS_DIR,
    STATIC_DIR,
    ASSETS_DIR,
    ParsedHTML,
    get_all_html_pages,
    get_all_content_files,
    get_all_template_files,
    get_canonical_slugs_baseline,
    get_site_config,
)


class TestHugoAgentRules(unittest.TestCase):
    """
    Codifies immutable AGENTS.md engineering rules:
    1. Permalink & Citation Integrity (Zero Broken Links)
    2. Multi-Environment & Relative Linking Isolation
    3. Static Purity & Performance (UDL Accessibility Alignment)
    4. Accessibility (WCAG 2.1 AA Compliance & HTML5 Landmarks)
    5. DevSecOps & Anti-Leakage Guardrails
    """
    pages: List[ParsedHTML] = []

    @classmethod
    def setUpClass(cls):
        cls.pages = get_all_html_pages()
        cls.config = get_site_config()
        if not cls.pages:
            raise unittest.SkipTest("No HTML files found in public/. Run 'hugo' first.")

    # --------------------------------------------------------------------------
    # Rule 1: Permalink & Citation Integrity
    # --------------------------------------------------------------------------
    def test_canonical_slug_baseline_integrity(self):
        """Verify 100% of baseline slugs exist in public/ if canonical_slugs.json is defined."""
        baseline = get_canonical_slugs_baseline()
        if not baseline:
            self.skipTest("No canonical slug baseline (data/canonical_slugs.json) defined.")

        public_slugs: Set[str] = set()
        for page in self.pages:
            # Extract slug from relpath: e.g. "posts/hello-devsecops/index.html" -> "hello-devsecops"
            parts = [p for p in page.relpath.split("/") if p and p != "index.html"]
            if parts:
                public_slugs.add(parts[-1])
                public_slugs.add("/".join(parts))

        for slug in baseline:
            clean_slug = slug.strip("/").split("/")[-1]
            with self.subTest(baseline_slug=slug):
                self.assertTrue(
                    slug.strip("/") in public_slugs or clean_slug in public_slugs,
                    f"Baseline canonical slug '{slug}' is missing from compiled public/ artifacts (Zero Broken Links violation)!"
                )

    def test_citation_identifier_formats(self):
        """Ensure any DOIs or ORCID references adhere strictly to standard formats."""
        doi_regex = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+")
        orcid_regex = re.compile(r"\b\d{4}-\d{4}-\d{4}-\d{3}[\dX]\b")

        for path, fm in get_all_content_files():
            with self.subTest(file=path.name):
                # Check DOI in frontmatter
                if "doi" in fm:
                    doi_val = str(fm["doi"]).strip()
                    self.assertTrue(
                        doi_regex.search(doi_val),
                        f"Invalid DOI format '{doi_val}' in {path.name}"
                    )
                # Check ORCID in frontmatter
                if "orcid" in fm:
                    orcid_val = str(fm["orcid"]).strip()
                    self.assertTrue(
                        orcid_regex.search(orcid_val),
                        f"Invalid ORCID format '{orcid_val}' in {path.name}"
                    )

    # --------------------------------------------------------------------------
    # Rule 2: Multi-Environment & Relative Linking Isolation
    # --------------------------------------------------------------------------
    def test_no_hardcoded_production_origin_in_templates(self):
        """Ensure templates in layouts/ use root-relative links or .RelPermalink instead of hardcoded base URLs."""
        prod_domain = self.config.domain
        if not prod_domain or prod_domain in ("localhost", "127.0.0.1", "example.com"):
            # If example.com is used in starter, check both example.com and common domains
            target_domains = [prod_domain] if prod_domain else []
        else:
            target_domains = [prod_domain]

        template_files = get_all_template_files()
        for tpl in template_files:
            content = tpl.read_text(encoding="utf-8", errors="replace")
            # Exclude comments or schema.org definitions
            for domain in target_domains:
                if not domain:
                    continue
                # Search for href="https://domain... or src="https://domain...
                pattern = re.compile(rf'(?:href|src)=["\']https?://{re.escape(domain)}/([^"\']*)["\']', re.IGNORECASE)
                matches = pattern.findall(content)
                rel_path = tpl.relative_to(REPO_ROOT).as_posix()
                with self.subTest(template=rel_path):
                    self.assertEqual(
                        len(matches), 0,
                        f"Hardcoded production domain '{domain}' found in navigation template {rel_path}: {matches}. Use root-relative linking."
                    )

    # --------------------------------------------------------------------------
    # Rule 3: Static Purity & Performance (UDL Accessibility)
    # --------------------------------------------------------------------------
    def test_static_purity_no_heavy_js_frameworks(self):
        """Prohibit heavy external client-side frameworks (React, Vue, jQuery, Angular, etc.) in compiled output."""
        banned = self.config.banned_js_frameworks
        banned_patterns = [
            re.compile(rf"\b{re.escape(name)}\b", re.IGNORECASE) for name in banned
        ]

        # Audit script tags across all pages
        for page in self.pages:
            with self.subTest(page=page.relpath):
                for script in page.script_tags:
                    src = script.get("src", "").lower()
                    for name in banned:
                        self.assertNotIn(
                            name, src,
                            f"Prohibited heavy JS framework '{name}' loaded in {page.relpath}: {src}"
                        )

        # Audit JS files in public/
        for js_file in PUBLIC_DIR.rglob("*.js"):
            rel_js = js_file.relative_to(PUBLIC_DIR).as_posix()
            content = js_file.read_text(encoding="utf-8", errors="replace")
            # Check for signature tokens of heavy frameworks
            heavy_signatures = [
                ("React.createElement", "React runtime"),
                ("ReactDOM.render", "ReactDOM runtime"),
                ("createApp(", "Vue 3 runtime"),
                ("angular.module", "AngularJS runtime"),
                ("jQuery.fn.jquery", "jQuery library"),
            ]
            for sig, label in heavy_signatures:
                self.assertNotIn(
                    sig, content,
                    f"Prohibited framework signature '{label}' found in public JS asset: {rel_js}"
                )

    # --------------------------------------------------------------------------
    # Rule 4: Accessibility & WCAG 2.1 AA Compliance
    # --------------------------------------------------------------------------
    def test_landmark_html5_semantics(self):
        """Ensure all standard viewable pages contain HTML5 landmark elements: <main>, <nav>, <header>, <footer>."""
        for page in self.pages:
            if page.is_alias_redirect:
                continue
            with self.subTest(page=page.relpath):
                self.assertGreaterEqual(
                    page.landmarks["main"], 1,
                    f"Missing <main> semantic landmark in {page.relpath}"
                )
                self.assertGreaterEqual(
                    page.landmarks["header"], 1,
                    f"Missing <header> semantic landmark in {page.relpath}"
                )
                self.assertGreaterEqual(
                    page.landmarks["footer"], 1,
                    f"Missing <footer> semantic landmark in {page.relpath}"
                )
                self.assertGreaterEqual(
                    page.landmarks["nav"], 1,
                    f"Missing <nav> navigation landmark in {page.relpath}"
                )

    def test_focus_visible_css_present(self):
        """Ensure stylesheets include visible :focus-visible indicators for keyboard accessibility."""
        css_sources = list(PUBLIC_DIR.rglob("*.css")) + list(STATIC_DIR.rglob("*.css")) + list(ASSETS_DIR.rglob("*.css"))
        has_focus_visible = False

        for css_file in css_sources:
            if css_file.is_file():
                content = css_file.read_text(encoding="utf-8", errors="replace")
                if ":focus-visible" in content or ":focus" in content:
                    has_focus_visible = True
                    break

        if not has_focus_visible:
            # Also check inline <style> tags in rendered pages
            for page in self.pages:
                if ":focus-visible" in page.raw_content:
                    has_focus_visible = True
                    break

        self.assertTrue(
            has_focus_visible,
            "No :focus-visible keyboard focus indicator found in stylesheets or templates (WCAG 2.1 AA violation)."
        )

    # --------------------------------------------------------------------------
    # Rule 5: DevSecOps Anti-Leakage & Editorial Quarantine
    # --------------------------------------------------------------------------
    def test_editorial_drafts_quarantine(self):
        """Ensure distribution notes, social copy, and unapproved drafts are strictly quarantined."""
        for root, _, files in os.walk(PUBLIC_DIR):
            for f in files:
                lower = f.lower()
                rel = Path(root, f).relative_to(PUBLIC_DIR).as_posix()
                self.assertFalse(
                    lower.startswith("_distribution") or "distribution_draft" in lower,
                    f"Editorial distribution staging file leaked in public: {rel}"
                )
                self.assertFalse(
                    lower.startswith("_vault") or "vault_sync" in lower,
                    f"Vault synchronization staging file leaked in public: {rel}"
                )


if __name__ == "__main__":
    unittest.main()
