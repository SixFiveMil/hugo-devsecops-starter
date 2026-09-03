---
title: "Sample Confidential Draft: Never Published"
date: 2026-09-02T00:00:00-00:00
slug: sample-confidential-draft
description: "This is a private draft used by automated security tests to ensure draft containment works."
draft: true
tags: ["Internal"]
categories: ["Drafts"]
---

This post is marked with `draft: true`. 

When the automated test suite runs (`python -m unittest discover -s tests`), the security gate `test_no_draft_leakage` will verify that:
1. No HTML artifact for this slug exists in `public/`.
2. This title does not appear in `public/index.json`.
3. This URL does not appear in `public/sitemap.xml`.
