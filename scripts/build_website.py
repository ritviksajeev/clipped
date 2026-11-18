"""Render the Markdown setup guides (clipped/assets/guides) into static HTML
pages under website/guides/, so the app and the website share one source.

    pip install markdown && python scripts/build_website.py
"""

from __future__ import annotations

import html
import re
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parent.parent
GUIDES = ROOT / "clipped" / "assets" / "guides"
OUT = ROOT / "website" / "guides"

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<meta name="theme-color" content="#09090b"/>
<title>{title} · clipped</title>
<meta name="description" content="{description}"/>
<script>(function(d){{var h=d.documentElement;h.classList.add('js');window.clippedFailsafe=setTimeout(function(){{h.classList.add('is-ready')}},7000)}})(document);</script>
<link rel="icon" type="image/svg+xml" href="../assets/favicon.svg"/>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
<link href="https://fonts.googleapis.com/css2?family=Geist:wght@300;400;500;600;700&family=Geist+Mono:wght@400;500&family=Instrument+Serif:ital@0;1&display=swap" rel="stylesheet"/>
<link rel="stylesheet" href="../style.css?v=2"/>
</head>
<body class="guide-page">
<div class="loader" aria-hidden="true"><div class="loader-brand">clipped</div></div>
<header class="topbar">
  <a href="../index.html" class="brand" data-transition aria-label="clipped home"><span data-sticker></span>clipped</a>
  <div class="topbar-right">
    <nav class="topnav" aria-label="Primary">
      <a href="../index.html#pipeline" data-transition><span data-scramble>Features</span></a>
      <a href="index.html" data-transition class="active"><span data-scramble>Guides</span></a>
      <a href="https://github.com/ritviksajeev/clipped" target="_blank" rel="noopener"><span data-scramble>GitHub</span></a>
    </nav>
    <a class="pill-btn" href="../index.html#download" data-transition data-magnetic="0.2"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 4v11M7 10l5 5 5-5M5 20h14"/></svg><span class="lbl">Download</span></a>
  </div>
</header>
<main>
  <section class="guide-hero">
    <div class="wrap">
      <div class="ph-top"><span><span class="dot"></span><a href="../index.html" data-transition>clipped</a> / <a href="index.html" data-transition>guides</a>{crumb}</span><span>{meta}</span></div>
      <h1 class="ph-title" data-split>{title}</h1>
    </div>
  </section>
  <div class="wrap guide-layout">
    <aside class="guide-nav reveal">
      <h3>SETUP GUIDES</h3>
      {nav}
    </aside>
    <article class="prose glow reveal d1">
      {body}
    </article>
  </div>
</main>
<footer class="site-footer" style="padding-top:70px;padding-bottom:110px">
  <div class="wrap">
    <div class="footer-bottom">
      <span>© clipped · MIT · runs on your computer</span>
      <a href="../index.html#download" data-transition>Download clipped ↗</a>
      <a href="https://evzero.org" target="_blank" rel="noopener">Built by evzero ↗</a>
    </div>
  </div>
</footer>
<script src="../vendor/lenis.min.js?v=1.3.27"></script>
<script src="../main.js?v=2"></script>
</body>
</html>
"""

INDEX_BODY = """<h2>Start here</h2>
<p>Everything you need to get clipped running with your own free API keys. The same guides are built into the app under <strong>Guides</strong>.</p>
<ol class="guide-list">{items}</ol>"""


def slug_of(path: Path) -> str:
    return path.stem.split("-", 1)[-1]


def title_of(text: str, fallback: str) -> str:
    return next((l.lstrip("# ").strip() for l in text.splitlines() if l.startswith("# ")), fallback)


def first_paragraph(text: str) -> str:
    for block in text.split("\n\n"):
        block = block.strip()
        if block and not block.startswith(("#", "|", ">", "*", "1.")):
            return re.sub(r"[*_`\[\]]|\(http[^)]*\)|\(#[^)]*\)", "", block)[:160]
    return "clipped setup guide"


def rewrite_links(md_text: str) -> str:
    # In-app links (#/guides/x) become sibling pages; other in-app routes become plain text.
    md_text = re.sub(r"\]\(#/guides/([a-z0-9-]+)\)", r"](\1.html)", md_text)
    md_text = re.sub(r"\[([^\]]+)\]\(#/[^)]*\)", r"\1", md_text)
    return md_text


def build() -> list[Path]:
    OUT.mkdir(parents=True, exist_ok=True)
    guides = sorted(GUIDES.glob("*.md"))
    entries = [(slug_of(p), title_of(p.read_text("utf-8"), p.stem), p) for p in guides]
    written = []

    def nav(active: str) -> str:
        active_attr = ' class="active"'
        links = "".join(
            f'<a href="{s}.html" data-transition{active_attr if s == active else ""}>{html.escape(t)}</a>'
            for s, t, _ in entries)
        return f"<nav>{links}</nav>"

    total = len(entries)
    for n, (slug, title, path) in enumerate(entries, start=1):
        text = path.read_text("utf-8")
        body = markdown.markdown(rewrite_links(text), extensions=["tables", "fenced_code", "sane_lists"])
        body = re.sub(r'<a href="(https?://[^"]+)"', r'<a href="\1" target="_blank" rel="noopener"', body)
        page = PAGE.format(title=html.escape(title), description=html.escape(first_paragraph(text)),
                           crumb=f" / {html.escape(slug)}", meta=f"guide {n:02d} of {total:02d}",
                           nav=nav(slug), body=body)
        target = OUT / f"{slug}.html"
        target.write_text(page, "utf-8")
        written.append(target)

    items = "".join(f'<li><a href="{s}.html" data-transition>{html.escape(t)}</a></li>' for s, t, _ in entries)
    index = PAGE.format(title="Setup guides", description="Step-by-step setup guides for clipped",
                        crumb="", meta=f"{total} guides", nav=nav(""), body=INDEX_BODY.format(items=items))
    (OUT / "index.html").write_text(index, "utf-8")
    written.append(OUT / "index.html")
    return written


if __name__ == "__main__":
    for path in build():
        print("wrote", path.relative_to(ROOT))
