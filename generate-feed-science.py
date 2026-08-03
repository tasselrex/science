#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

OUT = Path("feed.json")
MAX_ITEMS = 200

QUERIES = [
    ("Superconductivity", "all:superconductor OR all:superconductivity OR cat:cond-mat.supr-con"),
    ("Quantum", 'cat:quant-ph OR all:"quantum computing" OR all:"quantum information"'),
    ("Tribology", "all:tribology OR all:friction OR all:wear OR all:lubrication"),
    ("Materials science", "cat:cond-mat.mtrl-sci OR all:polymer OR all:nanomaterial OR all:materials"),
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ScienceFeed/1.0; +https://github.com/tasselrex/science)"
}

def clean(s: str | None) -> str:
    if not s:
        return ""
    return re.sub(r"\s+", " ", s).strip()

def strip_html(s: str | None) -> str:
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", " ", s)
    s = clean(s)
    return (
        s.replace("&amp;", "&")
         .replace("&lt;", "<")
         .replace("&gt;", ">")
         .replace("&quot;", '"')
         .replace("&apos;", "'")
    )

def truncate(s: str, n: int = 180) -> str:
    s = clean(s)
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"

def fetch(url: str, timeout: int = 25) -> str:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")

def parse_atom(xml_text: str, source_label: str):
    ns = {"a": "http://www.w3.org/2005/Atom"}
    root = ET.fromstring(xml_text)
    items = []

    for entry in root.findall("a:entry", ns):
        title = clean(entry.findtext("a:title", default="", namespaces=ns))
        summary = truncate(strip_html(entry.findtext("a:summary", default="", namespaces=ns)), 180)
        published = clean(entry.findtext("a:published", default="", namespaces=ns))[:10]
        updated = clean(entry.findtext("a:updated", default="", namespaces=ns))[:10]

        link = ""
        for link_el in entry.findall("a:link", ns):
            if link_el.attrib.get("rel", "alternate") == "alternate" and link_el.attrib.get("href"):
                link = link_el.attrib["href"]
                break
        if not link:
            link = clean(entry.findtext("a:id", default="", namespaces=ns))

        authors = [
            clean(author.findtext("a:name", default="", namespaces=ns))
            for author in entry.findall("a:author", ns)
        ]
        authors = ", ".join([a for a in authors if a][:3])

        items.append({
            "title": title,
            "summary": summary,
            "source": source_label,
            "date": published or updated or datetime.now(timezone.utc).date().isoformat(),
            "link": link,
            "authors": authors,
        })

    return items

def arxiv_url(query: str) -> str:
    base = "https://export.arxiv.org/api/query"
    params = {
        "search_query": query,
        "start": "0",
        "max_results": "50",
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    return base + "?" + urllib.parse.urlencode(params)

def main():
    print("Starting feed generation", flush=True)

    buckets = {label: [] for label, _ in QUERIES}
    errors = []
    source_counts = {}

    per_source_limit = max(1, MAX_ITEMS // max(1, len(QUERIES)))

    for label, query in QUERIES:
        try:
            print("Fetching:", label, flush=True)
            xml_text = fetch(arxiv_url(query))
            print("Fetched:", label, flush=True)

            items = parse_atom(xml_text, label)
            print(label, len(items), items[0]["title"] if items else "NO HITS", flush=True)

            seen_titles = set()
            unique_items = []
            for item in items:
                key = item["title"].lower()
                if key in seen_titles:
                    continue
                seen_titles.add(key)
                unique_items.append(item)

            buckets[label] = unique_items[:per_source_limit]
            source_counts[label] = len(buckets[label])

        except Exception as e:
            print("FAILED:", label, e, flush=True)
            errors.append(f"{label}: {e}")
            source_counts[label] = 0

    final_items = []
    global_seen = set()

    while len(final_items) < MAX_ITEMS:
        made_progress = False

        for label, _ in QUERIES:
            bucket = buckets[label]
            while bucket:
                item = bucket.pop(0)
                key = item["title"].lower()
                if key in global_seen:
                    continue
                global_seen.add(key)
                final_items.append(item)
                made_progress = True
                break

            if len(final_items) >= MAX_ITEMS:
                break

        if not made_progress:
            break

    payload = {
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "items": final_items,
        "errors": errors,
        "sourceCounts": source_counts,
        "sourceTotal": len(QUERIES),
        "itemTotal": len(final_items),
    }

    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUT} with {len(payload['items'])} items", flush=True)
    print("Source counts:", source_counts, flush=True)

if __name__ == "__main__":
    main()
