"""Render the Markdown setup guides (clippilot/assets/guides) into static HTML
pages under website/guides/, so the app and the website share one source.

    pip install markdown && python scripts/build_website.py
"""

from __future__ import annotations

import html
import re
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parent.parent
GUIDES = ROOT / "clippilot" / "assets" / "guides"
OUT = ROOT / "website" / "guides"

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} · ClipPilot</title>
<meta name="description" content="{description}">
<link rel="icon" href="../assets/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="../style.css">
</head>
<body class="guide-page">
<header class="nav">
  <a class="logo" href="../index.html"><img src="../assets/favicon.svg" alt="" width="28" height="28"> ClipPilot</a>
  <nav><a href="../index.html#features">Features</a><a href="index.html">Setup guides</a><a href="../index.html#download">Download</a>
  <a href="https://github.com/ritviksajeev/clipped" rel="noopener">GitHub</a></nav>
</header>
<main class="guide-layout">
  <aside class="guide-nav">
    <h3>Setup guides</h3>
    {nav}
  </aside>
  <article class="prose">
    {body}
  </article>
</main>
<footer class="footer"><p>ClipPilot is free and open source (MIT). It runs on your computer: no accounts, no servers, no tracking.</p></footer>
</body>
</html>
"""

INDEX_BODY = """<h1>Setup guides</h1>
<p>Everything you need to get ClipPilot running with your own free API keys. The same guides are built into the app under <strong>Guides</strong>.</p>
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
    return "ClipPilot setup guide"


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
            f'<a href="{s}.html"{active_attr if s == active else ""}>{html.escape(t)}</a>' for s, t, _ in entries)
        return f"<nav>{links}</nav>"

    for slug, title, path in entries:
        text = path.read_text("utf-8")
        body = markdown.markdown(rewrite_links(text), extensions=["tables", "fenced_code", "sane_lists"])
        body = re.sub(r'<a href="(https?://[^"]+)"', r'<a href="\1" target="_blank" rel="noopener"', body)
        page = PAGE.format(title=html.escape(title), description=html.escape(first_paragraph(text)),
                           nav=nav(slug), body=body)
        target = OUT / f"{slug}.html"
        target.write_text(page, "utf-8")
        written.append(target)

    items = "".join(f'<li><a href="{s}.html">{html.escape(t)}</a></li>' for s, t, _ in entries)
    index = PAGE.format(title="Setup guides", description="Step-by-step setup guides for ClipPilot",
                        nav=nav(""), body=INDEX_BODY.format(items=items))
    (OUT / "index.html").write_text(index, "utf-8")
    written.append(OUT / "index.html")
    return written


if __name__ == "__main__":
    for path in build():
        print("wrote", path.relative_to(ROOT))
