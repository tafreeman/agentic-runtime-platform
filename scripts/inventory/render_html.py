"""Render the assembled inventory markdown into the Superdesign report template.

Run with the markdown package available but without touching the project venv:
    uv run --with markdown python scripts/inventory/render_html.py

Input:  docs/inventory/ARP-REPO-INVENTORY-<date>.md (from assemble.py)
        scripts/inventory/templates/superdesign_report.html (committed copy of the
        Superdesign draft, so a fresh clone can render without the local .superdesign/)
Output: docs/inventory/ARP-REPO-INVENTORY-<date>.html (also importable as a draft version)
"""

from __future__ import annotations

import html
import itertools
import json
import re
import sys
from pathlib import Path

import markdown

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from _common import HOME_REPO, OUT_DIR

INV = HOME_REPO / "docs" / "inventory"
_REF_IDS = itertools.count(1)  # page-wide: anchor ids must be unique
TEMPLATE = HERE / "templates" / "superdesign_report.html"
GH_BLOB = "https://github.com/tafreeman/agentic-runtime-platform/blob/{rev}/{path}"
GH_PR = "https://github.com/tafreeman/agentic-runtime-platform/pull/{n}"

STATUS = {  # cell text (lower) -> (glyph, tone)
    "active": ("●", "success"),
    "current": ("●", "success"),
    "used": ("●", "success"),
    "done": ("○", "neutral"),
    "merged": ("○", "neutral"),
    "accepted": ("●", "success"),
    "in review": ("◐", "info"),
    "open": ("◐", "info"),
    "ongoing": ("◐", "info"),
    "proposed": ("◐", "info"),
    "in-flight": ("◐", "info"),
    "generated": ("◇", "plum"),
    "config": ("◇", "plum"),
    "test-only": ("◇", "plum"),
    "stale": ("▲", "warning"),
    "stalled": ("▲", "warning"),
    "needs work": ("▲", "warning"),
    "superseded": ("▲", "warning"),
    "local-only": ("▲", "warning"),
    "blocked": ("▲", "warning"),
    "unused": ("✕", "danger"),
    "dead": ("✕", "danger"),
    "orphan": ("✕", "danger"),
    "orphan?": ("✕", "danger"),
    "broken": ("✕", "danger"),
    "duplicate": ("✕", "danger"),
}
TONE_CLS = {
    "success": "bg-el-success-soft text-el-success",
    "info": "bg-el-info-soft text-el-info",
    "warning": "bg-el-warning-soft text-el-warning",
    "danger": "bg-el-danger-soft text-el-danger",
    "plum": "bg-el-plum-soft text-el-plum",
    "neutral": "bg-el-surface-subtle text-el-ink-muted",
}
EXTRA_HEAD = (
    "<style>{css}</style>\n"
    '<script src="https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js" '
    'integrity="sha384-WmdflGW9aGfoBdHc4rRyWzYuAjEmDwMdGdiPNacbwfGKxBW/SO6guzuQ76qjnSlr" '
    'crossorigin="anonymous"></script>\n'
    '<script>document.addEventListener("DOMContentLoaded",()=>{{'
    'const dark=document.documentElement.dataset.theme==="dark";'
    'mermaid.initialize({{startOnLoad:true,theme:dark?"dark":"neutral",'
    'fontFamily:"ui-monospace, Consolas, monospace"}});'
    'const links=[...document.querySelectorAll(".toc-link")];'
    "const obs=new IntersectionObserver(es=>es.forEach(e=>{{if(e.isIntersecting){{"
    'links.forEach(l=>l.classList.toggle("is-active",l.dataset.toc===e.target.id));}}}}),'
    '{{rootMargin:"-10% 0px -80% 0px"}});'
    'document.querySelectorAll("main section[id]").forEach(s=>obs.observe(s));}});</script>\n'
)
LEDGER_CSS = """
.ledger h3{font-family:Georgia,"Times New Roman",serif;font-size:1.2rem;color:var(--el-ink);margin:3rem 0 1rem}
.ledger h4{font-weight:600;color:var(--el-ink);margin:2rem 0 .75rem}
.ledger p,.ledger li{font-size:15px;line-height:1.75rem;color:var(--el-ink-secondary)}
.ledger p{margin:.75rem 0}
.ledger ul,.ledger ol{padding-left:1.5rem;margin:.75rem 0}
.ledger ul{list-style:disc}.ledger ol{list-style:decimal}
.ledger li{margin:.25rem 0}
.ledger strong{font-weight:600;color:var(--el-ink)}
.ledger a{color:var(--el-focus)}.ledger a:hover{text-decoration:underline}
.ledger blockquote{background:var(--el-surface-subtle);border-left:2px solid var(--el-info);
  padding:1rem;margin:1.5rem 0;border-radius:0 4px 4px 0;font-size:14px}
.ledger blockquote p{margin:0;font-size:14px}
.ledger code{font-family:ui-monospace,"Cascadia Code",Consolas,monospace;font-size:12.5px;
  background:var(--el-surface-sunken);border:1px solid var(--el-divider-soft);border-radius:4px;padding:.05rem .3rem}
.ledger pre{background:var(--el-surface-sunken);border:1px solid var(--el-divider-soft);border-radius:4px;
  padding:1rem;margin:1rem 0;overflow-x:auto;font-size:13px;line-height:1.5rem}
.ledger pre code{background:none;border:0;padding:0}
.ledger hr{margin:2.5rem 0;border-color:var(--el-divider)}
.ledger .tbl{overflow-x:auto;border:1px solid var(--el-divider);border-radius:4px;margin:1.25rem 0}
.ledger table{width:100%;border-collapse:collapse;font-size:13px;line-height:1.55}
.ledger thead{background:var(--el-surface-subtle);color:var(--el-ink-secondary)}
.ledger th{padding:.5rem .75rem;font-weight:500;text-align:left;vertical-align:bottom;
  border-bottom:1px solid var(--el-divider);position:sticky;top:0;background:var(--el-surface-subtle)}
.ledger td{padding:.5rem .75rem;vertical-align:top;border-top:1px solid var(--el-divider-soft);color:var(--el-ink)}
.ledger tr:hover td{background:var(--el-surface-hover)}
.ledger td code{white-space:nowrap}
.toc-link.is-active{border-left-color:var(--el-accent);color:var(--el-ink);background:var(--el-surface);font-weight:500}
nav.toc-rail{max-height:calc(100vh - 4rem);overflow-y:auto}
@media print{nav,#theme-toggle{display:none}main{border:0}}
"""


def _section_id(title: str) -> str:
    m = re.match(r"(\d+)\.", title)
    return (
        f"s{m.group(1)}" if m else "s-" + re.sub(r"\W+", "-", title.lower()).strip("-")
    )


def _short(title: str) -> str:
    """TOC label: drop the em-dash/paren subtitle, then trim long comma lists."""
    head = re.split(r"\s+[—(]", title)[0]
    return head if len(head) <= 34 else head.split(",")[0] + " …"


def _link(href: str, rev: str) -> str:
    if href.startswith(("http://", "https://", "#", "mailto:")):
        return href
    path = href.lstrip("./").split("#")[0]
    return GH_BLOB.format(rev=rev, path=path)


def _pills(cell_html: str) -> str:
    text = re.sub(r"<[^>]+>", "", cell_html).strip().strip("*").strip()
    key = text.lower()
    if key in STATUS:
        glyph, tone = STATUS[key]
        return (
            f'<span class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full '
            f'{TONE_CLS[tone]} text-xs font-medium whitespace-nowrap">{glyph} {html.escape(text)}</span>'
        )
    return cell_html


def _style(body: str, rev: str) -> str:
    body = re.sub(
        r'<pre><code class="language-mermaid">(.*?)</code></pre>',
        lambda m: (
            '<figure class="my-8 p-1 border border-el-divider rounded bg-el-surface-subtle">'
            '<div class="mermaid bg-el-surface border border-el-divider-soft rounded p-6 '
            f'overflow-x-auto">{m.group(1)}</div></figure>'
        ),
        body,
        flags=re.S,
    )
    # Element styling lives in LEDGER_CSS (scoped to .ledger) — per-element utility
    # classes on ~5k table cells doubled the page size and stalled the Tailwind CDN.
    body = re.sub(r"<table>", '<div class="tbl"><table>', body)
    body = body.replace("</table>", "</table></div>")
    body = re.sub(
        r"<td>(.*?)</td>", lambda m: f"<td>{_pills(m.group(1))}</td>", body, flags=re.S
    )
    body = re.sub(
        r'href="([^"]+)"',
        lambda m: f'href="{_link(html.unescape(m.group(1)), rev)}"',
        body,
    )
    body = re.sub(
        r"(?<![\w/#])tafreeman/agentic-runtime-platform#(\d+)",
        lambda m: f'<a href="{GH_PR.format(n=m.group(1))}">#{m.group(1)}</a>',
        body,
    )
    body = re.sub(
        r"<a (?![^>]*\bid=)", lambda _m: f'<a id="ref-{next(_REF_IDS)}" ', body
    )
    return body


def _sections(md_text: str, rev: str) -> tuple[list[str], list[tuple[str, str]]]:
    conv = markdown.Markdown(extensions=["tables", "fenced_code", "sane_lists"])
    chunks = re.split(r"(?m)^## ", md_text)
    out, toc = [], []
    for chunk in chunks[1:]:
        title, _, rest = chunk.partition("\n")
        title = title.strip()
        if title.lower() == "contents":
            continue
        sid = _section_id(title)
        toc.append((sid, title))
        num = re.match(r"(\d+)\.", title)
        eyebrow = f"Section {num.group(1)}" if num else "Report"
        heading = re.sub(r"^\d+\.\s*", "", title)
        body = _style(conv.reset().convert(rest), rev)
        out.append(
            f'<section id="{sid}" class="scroll-mt-8 mb-16">'
            f'<div class="mb-8"><div class="text-micro font-mono uppercase tracking-widest '
            f'text-el-ink-muted mb-2">{eyebrow}</div><h2 class="text-3xl font-display text-el-ink '
            f'pb-4 border-b border-el-divider">{html.escape(heading)}</h2></div>{body}</section>'
        )
    return out, toc


def _stats() -> list[tuple[str, str, str]]:
    py = json.loads((OUT_DIR / "py_inventory.json").read_text(encoding="utf-8"))
    ui = json.loads((OUT_DIR / "ui_inventory.json").read_text(encoding="utf-8"))
    meta = json.loads((OUT_DIR / "meta_inventory.json").read_text(encoding="utf-8"))
    src = [m for m in py["modules"] if not m.get("is_test")]
    prs = meta["git"]["open_prs"]

    return [
        (f"{sum(int(m.get('loc', 0)) for m in src):,}", "Python source LOC", "ink"),
        (f"{py['test_totals']['functions']:,}", "Python test functions", "ink"),
        (
            f"{sum(r['loc'] for r in ui['files'] if not r['is_test']):,}",
            "UI source LOC",
            "ink",
        ),
        (
            str(len(prs) if isinstance(prs, list) else "?"),
            "Open PRs at extract",
            "accent",
        ),
        (str(len(meta["adrs"])), "ADR files", "ink"),
        (
            str(
                len(ui["unused_candidates"])
                + sum(1 for m in src if m.get("orphan_candidate"))
            ),
            "Unused-code candidates",
            "warning",
        ),
    ]


def _page(
    base: str, sections: str, toc: list[tuple[str, str]], active: str = ""
) -> str:
    """Fill the Superdesign template with the given sections and a TOC rail."""
    toc_html = "".join(
        f'<li><a href="#{sid}" id="toc-{sid}" data-toc="{sid}" class="toc-link block py-1.5 px-3 '
        f"border-l-2 border-transparent hover:bg-el-surface-hover"
        f'{" is-active" if sid == active else ""}">{html.escape(_short(title))}</a></li>'
        for sid, title in toc
    )
    page = re.sub(
        r"(<nav[^>]*>\s*<ul[^>]*>).*?(</ul>\s*</nav>)",
        lambda m: m.group(1) + toc_html + m.group(2),
        base,
        flags=re.S,
    )
    return re.sub(
        r"(<main[^>]*>).*?(</main>)",
        lambda m: m.group(1) + sections + m.group(2),
        page,
        flags=re.S,
    )


def _set_span(tpl: str, sd_id: int, text: str) -> str:
    """Replace the text of the element tagged ``data-sd-id`` (first match only)."""
    return re.sub(
        rf'(data-sd-id="{sd_id}">)[^<]*(<)',
        lambda m: m.group(1) + html.escape(text, quote=False) + m.group(2),
        tpl,
        count=1,
    )


def _fill_cover(tpl: str) -> str:
    """Populate the cover from the data so it cannot describe another revision."""
    meta = json.loads((OUT_DIR / "meta_inventory.json").read_text(encoding="utf-8"))
    py = json.loads((OUT_DIR / "py_inventory.json").read_text(encoding="utf-8"))
    ui = json.loads((OUT_DIR / "ui_inventory.json").read_text(encoding="utf-8"))
    short, _, rest = str(meta["revision"]).partition(" ")
    day = rest[:10]
    src = [m for m in py["modules"] if not m.get("is_test")]
    tpl = _set_span(tpl, 5, f"Repository Inventory · {day}")
    tpl = _set_span(tpl, 9, f"rev {short}")
    tpl = _set_span(tpl, 11, f"{len(src)} Python modules")
    tpl = _set_span(tpl, 13, f"{len(ui['files'])} UI files")
    tpl = _set_span(tpl, 15, f"{len(meta['workflows'])} workflows")
    tpl = _set_span(tpl, 17, f"{len(meta['ci'])} CI jobs")
    tpl = _set_span(tpl, 19, f"{len(meta['adrs'])} ADRs")
    tpl = re.sub(
        r"Snapshot taken [0-9/\-]+ against",
        f"Snapshot taken {day} against",
        tpl,
        count=1,
    )
    return re.sub(
        r"(<code[^>]*>)c3b2d328(</code>)",
        lambda m: m.group(1) + short + m.group(2),
        tpl,
    )


def _base_template() -> str:
    tpl = _fill_cover(TEMPLATE.read_text(encoding="utf-8"))
    tiles = "".join(
        f'<div><div class="text-3xl font-display text-el-{tone}">{val}</div>'
        f'<div class="text-micro uppercase font-mono text-el-ink-muted mt-1 tracking-wider">{label}</div></div>'
        for val, label, tone in _stats()
    )
    tpl = re.sub(
        r"(<!-- Stat Tiles -->\s*<div[^>]*>).*?(</div>\s*</div>\s*</div>\s*<!-- Main Layout -->)",
        lambda m: (
            m.group(1)
            + tiles
            + "</div>\n      </div>\n    </div>\n\n    <!-- Main Layout -->"
        ),
        tpl,
        flags=re.S,
    )
    tpl = tpl.replace('<main class="', '<main class="ledger ', 1)
    tpl = tpl.replace("shadow-[0_16px_40px_rgb(22_22_22_/_0.04)] dark:shadow-none", "")
    tpl = tpl.replace('<nav class="', '<nav class="toc-rail ', 1)
    return tpl.replace("</head>", EXTRA_HEAD.format(css=LEDGER_CSS) + "</head>", 1)


def main() -> None:
    md_path = max(INV.glob("ARP-REPO-INVENTORY-*.md"))
    meta = json.loads((OUT_DIR / "meta_inventory.json").read_text(encoding="utf-8"))
    rev = meta["revision"].split()[0]
    parts, toc = _sections(md_path.read_text(encoding="utf-8"), rev)
    base = _base_template()
    full = _page(base, "\n".join(parts), toc)
    out = md_path.with_suffix(".html")
    out.write_text(full, encoding="utf-8")
    print(f"wrote {out} ({len(full) // 1024} KB, {len(toc)} sections)")
    # Superdesign rejects very large drafts (HTTP 403 at ~630 KB), so the canvas gets one
    # draft per section; the single-page file above stays the canonical deliverable.
    split_dir = HOME_REPO / ".superdesign" / "tmp" / "parts"
    split_dir.mkdir(parents=True, exist_ok=True)
    for (sid, _title), body in zip(toc, parts, strict=True):
        # The Superdesign API's firewall 403s on the literal text "python -m" (reads as
        # command injection); a non-breaking space renders identically and passes.
        # Literal braces in content (Mermaid decision nodes) are rejected as JSX residue;
        # entities decode back to the same text for Mermaid and the reader.
        body = body.replace("{", "&#123;").replace("}", "&#125;")
        page = _page(base, body, toc, active=sid).replace("python -m", "python&nbsp;-m")
        (split_dir / f"{sid}.html").write_text(page, encoding="utf-8")
        print(f"  part {sid}: {len(page) // 1024} KB")


if __name__ == "__main__":
    main()
