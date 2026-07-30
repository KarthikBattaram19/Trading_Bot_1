#!/usr/bin/env python3
"""Convert markdown files to styled PDF documents using markdown + xhtml2pdf."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import markdown
from xhtml2pdf import pisa


CSS = """
@page {
    size: A4;
    margin: 2cm 1.8cm 2.2cm 1.8cm;
    @frame footer {
        -pdf-frame-content: footerContent;
        bottom: 0.6cm;
        margin-left: 1.8cm;
        margin-right: 1.8cm;
        height: 1cm;
    }
}

body {
    font-family: Helvetica, Arial, sans-serif;
    font-size: 10pt;
    line-height: 1.45;
    color: #1a1a1a;
}

h1 {
    font-size: 22pt;
    color: #0f172a;
    border-bottom: 2px solid #2563eb;
    padding-bottom: 6px;
    margin-top: 0;
    margin-bottom: 14px;
    page-break-after: avoid;
}

h2 {
    font-size: 16pt;
    color: #1e3a5f;
    margin-top: 22px;
    margin-bottom: 10px;
    page-break-after: avoid;
}

h3 {
    font-size: 13pt;
    color: #334155;
    margin-top: 16px;
    margin-bottom: 8px;
    page-break-after: avoid;
}

h4, h5, h6 {
    font-size: 11pt;
    color: #475569;
    margin-top: 12px;
    margin-bottom: 6px;
    page-break-after: avoid;
}

p {
    margin: 0 0 8px 0;
    text-align: justify;
}

a {
    color: #2563eb;
    text-decoration: none;
}

ul, ol {
    margin: 0 0 10px 0;
    padding-left: 22px;
}

li {
    margin-bottom: 4px;
}

blockquote {
    margin: 10px 0;
    padding: 8px 12px;
    border-left: 4px solid #94a3b8;
    background: #f8fafc;
    color: #334155;
}

code {
    font-family: Courier, monospace;
    font-size: 9pt;
    background: #f1f5f9;
    padding: 1px 4px;
    border-radius: 3px;
}

pre {
    font-family: Courier, monospace;
    font-size: 8pt;
    background: #0f172a;
    color: #e2e8f0;
    padding: 10px 12px;
    border-radius: 4px;
    white-space: pre-wrap;
    word-wrap: break-word;
    margin: 10px 0 14px 0;
    page-break-inside: avoid;
}

pre code {
    background: transparent;
    color: inherit;
    padding: 0;
}

table {
    width: 100%;
    border-collapse: collapse;
    margin: 10px 0 14px 0;
    font-size: 9pt;
    page-break-inside: avoid;
}

th {
    background: #1e40af;
    color: #ffffff;
    font-weight: bold;
    padding: 6px 8px;
    border: 1px solid #1e3a8a;
    text-align: left;
}

td {
    padding: 5px 8px;
    border: 1px solid #cbd5e1;
    vertical-align: top;
}

tr:nth-child(even) td {
    background: #f8fafc;
}

hr {
    border: none;
    border-top: 1px solid #cbd5e1;
    margin: 18px 0;
}

.diagram-note {
    margin: 10px 0 14px 0;
    padding: 10px 12px;
    background: #eff6ff;
    border: 1px solid #93c5fd;
    border-radius: 4px;
    font-size: 9pt;
    color: #1e3a8a;
    page-break-inside: avoid;
}

#footerContent {
    font-size: 8pt;
    color: #64748b;
    text-align: center;
}
"""


def preprocess_markdown(text: str) -> str:
    """Replace mermaid blocks with readable placeholders for PDF output."""

    def replace_mermaid(match: re.Match[str]) -> str:
        diagram = match.group(1).strip()
        preview = diagram[:200] + ("..." if len(diagram) > 200 else "")
        preview = preview.replace("\n", " ")
        return (
            "\n\n> **Diagram (see source markdown for full rendering):** "
            f"`{preview}`\n\n"
        )

    text = re.sub(r"```mermaid\s*\n(.*?)```", replace_mermaid, text, flags=re.DOTALL)
    return text


def md_to_html(md_text: str, title: str) -> str:
    md_text = preprocess_markdown(md_text)
    body = markdown.markdown(
        md_text,
        extensions=[
            "tables",
            "fenced_code",
            "toc",
            "sane_lists",
            "nl2br",
        ],
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8" />
    <title>{title}</title>
    <style>{CSS}</style>
</head>
<body>
{body}
<div id="footerContent">{title}</div>
</body>
</html>"""


def convert_file(input_path: Path, output_path: Path) -> None:
    md_text = input_path.read_text(encoding="utf-8")
    title = input_path.stem.replace("_", " ").title()
    html = md_to_html(md_text, title)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as pdf_file:
        status = pisa.CreatePDF(html, dest=pdf_file, encoding="utf-8")

    if status.err:
        raise RuntimeError(f"PDF generation failed for {input_path} ({status.err} errors)")


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert markdown files to PDF.")
    parser.add_argument("inputs", nargs="+", type=Path, help="Markdown input files")
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory (default: same as input file)",
    )
    args = parser.parse_args()

    for input_path in args.inputs:
        if not input_path.exists():
            print(f"Error: file not found: {input_path}", file=sys.stderr)
            return 1
        out_dir = args.output_dir or input_path.parent
        output_path = out_dir / f"{input_path.stem}.pdf"
        print(f"Converting {input_path} -> {output_path}")
        convert_file(input_path, output_path)
        print(f"  OK ({output_path.stat().st_size:,} bytes)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
