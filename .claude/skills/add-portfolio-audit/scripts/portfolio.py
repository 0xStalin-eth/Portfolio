#!/usr/bin/env python3
"""Keep the portfolio README in sync with the Cyfrin audit report repos.

Commands:
  lookup <report>                 Find the Cyfrin Tech tags for a report (URL or PDF filename).
  add --name N --date YYYY-MM --report R [--tags "A, B"] [--table "### ..."]
                                  Insert the audit row (or fill in a WIP row with the same name),
                                  then recount everything.
  recount                         Rebuild the category table, the audit totals and the
                                  expertise counts from the current tables.

Options: --readme PATH (default: README.md at the repo root), --dry-run (print, don't write).
"""
import argparse
import collections
import json
import os
import re
import sys

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = json.load(open(os.path.join(SKILL_DIR, "config.json"), encoding="utf-8"))
REPO_ROOT = os.path.abspath(os.path.join(SKILL_DIR, "..", "..", ".."))
GITHUB = "https://github.com/Cyfrin/{repo}/blob/main/reports/{pdf}"
REPORT_RE = re.compile(r"github\.com/Cyfrin/(cyfrin-audit-reports(?:-private)?)/blob/main/reports/([^)\s]+)")


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Cyfrin repo lookups
# ---------------------------------------------------------------------------

def resolve_report(report):
    """Return (repo, pdf, url) from a GitHub URL or a bare PDF filename."""
    m = REPORT_RE.search(report)
    pdf = m.group(2) if m else os.path.basename(report)
    if not pdf.endswith(".pdf"):
        fail(f"report links must point to a .pdf, got {pdf}")
    if m:
        repo = m.group(1)
    else:
        repo = None
        for name, key in (("cyfrin-audit-reports", "public_repo"), ("cyfrin-audit-reports-private", "private_repo")):
            if os.path.isfile(os.path.join(CONFIG[key], "reports", pdf)):
                repo = name
                break
        if not repo:
            fail(f"{pdf} is in neither the public nor the private Cyfrin repo (did you git pull?)")
    local = os.path.join(CONFIG["public_repo" if repo == "cyfrin-audit-reports" else "private_repo"], "reports", pdf)
    if not os.path.isfile(local):
        fail(f"{pdf} is not in {repo}/reports (did you git pull?)")
    return repo, pdf, GITHUB.format(repo=repo, pdf=pdf)


def load_process_report():
    sys.path.insert(0, CONFIG["process_report_scripts"])
    try:
        import process_report  # noqa: E402
    except ImportError:
        fail(f"cannot import process_report.py from {CONFIG['process_report_scripts']} (update config.json)")
    return process_report


def tech_from_row(row):
    return [p.strip() for p in row.split("|")][4]


def lookup(report):
    repo, pdf, url = resolve_report(report)
    pub_readme = os.path.join(CONFIG["public_repo"], "README.md")
    pr = load_process_report()
    lines = open(pub_readme, encoding="utf-8").read().splitlines()
    start, end = pr.find_first_table_bounds(lines)
    info = {"repo": repo, "pdf": pdf, "url": url, "private": repo.endswith("-private")}
    if not info["private"]:
        hits = [r for r in lines[start:end] if f"reports/{pdf})" in r]
        info["matched_by"] = "PDF filename in the public README"
    else:
        audit_start = None
        for line in open(os.path.join(CONFIG["private_repo"], "README.md"), encoding="utf-8"):
            m = re.match(r"\|\s*(\d{4}-\d{2}-\d{2})\s*\|(.*)\|", line)
            if m and f"reports/{pdf})" in m.group(2):
                audit_start = m.group(1)
                break
        if not audit_start:
            fail(f"{pdf} has no row in the private README")
        client, project = pr.extract_client_and_project(pdf)
        hit = pr.find_redacted_row(pub_readme, audit_start, client, project)
        label = pr.make_redacted_label(client, project)
        if not hit:
            fail(f"no '{label}' row starting {audit_start} in the public README - the private report "
                 "was processed without its REDACTED placeholder; add one (process-reports skill) first")
        hits = [hit["line"]]
        info.update(audit_start=audit_start, label=label, matched_by="private README date + REDACTED label")
    if len(hits) != 1:
        fail(f"expected exactly 1 public README row for {pdf}, found {len(hits)}")
    info["public_row"] = hits[0]
    info["cyfrin_tech"] = tech_from_row(hits[0])
    info["tags"] = ", ".join(t.strip() for t in info["cyfrin_tech"].split(",") if t.strip() not in CONFIG["drop_tags"])
    info["note"] = ("Cyfrin tags never say Integration/Fork - check whether this audit integrates or forks "
                    "another protocol and adjust --tags (e.g. 'LayerZero' -> 'LayerZero Integration', add 'Angle Fork').")
    return info


# ---------------------------------------------------------------------------
# README parsing
# ---------------------------------------------------------------------------

def iter_rows(lines, start_heading, stop_heading):
    """Yield (index, cells, category_col) for every data row of every table between two headings."""
    try:
        a = lines.index(start_heading)
    except ValueError:
        fail(f"heading '{start_heading}' not found in README")
    col = None
    for i in range(a, len(lines)):
        line = lines[i]
        if line.startswith(stop_heading) and i > a:
            break
        if not line.startswith("|"):
            col = None
            continue
        cells = [c.strip() for c in line.split("|")]
        if col is None:
            col = cells.index("Category") if "Category" in cells else -1
            continue
        if col < 0 or cells[col].startswith((":", "-")):
            continue
        yield i, cells, col


def collect(lines):
    private, public = [], []
    for i, cells, col in iter_rows(lines, "## Private Engagements", "## Public Engagements"):
        if "WIP" not in lines[i]:
            private.append({t.strip() for t in cells[col].split(",")})
    for _, cells, col in iter_rows(lines, "## Public Engagements - (2023 - 2024)", "# "):
        public.append({t.strip() for t in cells[col].split(",")})
    return private, public


# ---------------------------------------------------------------------------
# Recount
# ---------------------------------------------------------------------------

def recount(lines):
    private, public = collect(lines)
    rows = private + public
    alias = CONFIG["count_aliases"]
    counts = collections.Counter()
    for tags in rows:
        counts.update({alias.get(t, t) for t in tags})
    integ = sum(any(t.endswith(" Integration") for t in tags) for tags in rows)
    fork = sum(any(t.endswith(" Fork") for t in tags) for tags in rows)

    # Total contests is the hand-maintained "~N public contests" figure.
    note = next((l for l in lines if l.startswith("> In total I've done")), None)
    if not note:
        fail("note line '> In total I've done ...' not found")
    m = re.search(r"~(\d+) public contests", note)
    if not m:
        fail("could not read '~N public contests' from the total note")
    contests = int(m.group(1))

    w = max(len(k) for k in counts)
    block = ["## Audits by Category", "",
             f"> In total I've done ~{len(private) + contests} audits: {len(private)} private engagements and ~{contests} public contests.",
             ">",
             f"> The breakdown counts the {len(rows)} audits listed below: the {len(private)} private engagements and the {len(public)} public contests where I placed in the top 10. An audit with several categories is counted in each of them.",
             f"> {integ} audits were integrations with other protocols (`... Integration` tags) and {fork} were forks (`... Fork` tags).", "",
             "<details>", "<summary>Show the category breakdown</summary>", "",
             f"| {'Category'.ljust(w)} | Audits |", f"| :{'-' * (w - 1)} | -----: |"]
    block += [f"| {k.ljust(w)} | {str(v).rjust(6)} |" for k, v in sorted(counts.items(), key=lambda x: (-x[1], x[0].lower()))]
    block += ["", "</details>", ""]
    a, b = lines.index("## Audits by Category"), lines.index("## Private Engagements")
    lines[a:b] = block

    for i, line in enumerate(lines):
        if line.startswith("> Only the ") and "contests where I placed in the top 10" in line:
            lines[i] = re.sub(r"Only the \d+ contests", f"Only the {len(public)} contests", line)

    # Expertise bullets: "- Label (N)"
    groups = CONFIG["expertise_groups"]
    unknown = []
    for i, line in enumerate(lines):
        m = re.match(r"^- (.+) \((\d+)\)$", line)
        if not m:
            continue
        label = m.group(1)
        if label not in groups:
            unknown.append(label)
            continue
        members = set(groups[label])
        lines[i] = f"- {label} ({sum(bool(members & tags) for tags in rows)})"
    if unknown:
        print(f"WARNING: expertise bullets without a group in config.json (left unchanged): {unknown}", file=sys.stderr)

    known = {t for g in groups.values() for t in g}
    ungrouped = sorted(k for k in {t for tags in rows for t in tags} if k not in known)
    return {"listed": len(rows), "private": len(private), "contests_listed": len(public),
            "total": len(private) + contests, "integrations": integ, "forks": fork,
            "tags_in_no_expertise_group": ungrouped}


# ---------------------------------------------------------------------------
# Add
# ---------------------------------------------------------------------------

def add(lines, name, date, report, tags, table):
    if not re.fullmatch(r"\d{4}-\d{2}", date):
        fail(f"date must be YYYY-MM, got {date}")
    repo, pdf, url = resolve_report(report)
    if any(f"/reports/{pdf})" in l for l in lines):
        fail(f"{pdf} is already in the portfolio")
    if tags is None:
        tags = lookup(report)["tags"]
    label = "PRIVATE" if repo.endswith("-private") else "Report"
    row = f"| {name.ljust(29)} | {date} | {tags.ljust(39)} | **[{label}]({url})**  |"

    h = next((k for k, l in enumerate(lines) if l.startswith(table)), None)
    if h is None:
        fail(f"no table heading starting with '{table}'")
    i = h + 3  # heading, header row, separator row
    if not (lines[h + 1].startswith("|") and lines[h + 2].startswith("|")):
        fail(f"unexpected layout under '{table}'")
    # A WIP row with the same name gets filled in instead of duplicated.
    for j in range(i, len(lines)):
        if not lines[j].startswith("|"):
            break
        cells = [c.strip() for c in lines[j].split("|")]
        if cells[1] == name and "WIP" in lines[j]:
            lines[j] = row
            return {"action": "filled WIP row", "line": j + 1, "row": row}
    # Newest first: insert before the first row with an older date.
    while i < len(lines) and lines[i].startswith("|"):
        cells = [c.strip() for c in lines[i].split("|")]
        if cells[2] < date:
            break
        i += 1
    lines.insert(i, row)
    return {"action": "inserted row", "line": i + 1, "row": row}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--readme", default=os.path.join(REPO_ROOT, "README.md"))
    ap.add_argument("--dry-run", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("lookup")
    p.add_argument("report")
    p = sub.add_parser("add")
    p.add_argument("--name", required=True)
    p.add_argument("--date", required=True)
    p.add_argument("--report", required=True)
    p.add_argument("--tags")
    p.add_argument("--table", default=CONFIG["default_table"])
    sub.add_parser("recount")
    args = ap.parse_args()

    if args.cmd == "lookup":
        print(json.dumps(lookup(args.report), indent=1))
        return
    lines = open(args.readme, encoding="utf-8").read().split("\n")
    out = {}
    if args.cmd == "add":
        out["added"] = add(lines, args.name, args.date, args.report, args.tags, args.table)
    out["counts"] = recount(lines)
    if not args.dry_run:
        open(args.readme, "w", encoding="utf-8").write("\n".join(lines))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
