---
name: add-portfolio-audit
description: Add a new Cyfrin audit to the portfolio README with its categories pulled automatically from the Cyfrin audit-report repos, then refresh every counter (audits by category, total audit count, integrations/forks, areas of expertise). Use when the user says "add an audit", "add this report to my portfolio", "new audit", gives a project name + date + Cyfrin report link, or asks to "recount" / "refresh the counters".
---

# Add an audit to the portfolio

The user gives three things: **project name**, **date** (`YYYY-MM`, the audit month) and the **report link**.
Everything else is filled in from the Cyfrin repos by `scripts/portfolio.py`. Paths, dropped tags, count aliases and the expertise groups live in `config.json` next to this file.

## Rules

- **Report links point to a `.pdf`**, in `Cyfrin/cyfrin-audit-reports` (shown as `**[Report](...)**`) or `Cyfrin/cyfrin-audit-reports-private` (shown as `**[PRIVATE](...)**`). The script refuses anything else. Interesting-finding links may point to `.md`; this skill doesn't touch them.
- **Categories come from the Cyfrin public README's Tech column**, never invented:
  - Public report: matched by PDF filename in the public README main table.
  - Private report: the private README date (audit start) + the REDACTED label built from the filename (client first+last letter, project first letter per word) picks the REDACTED row. This is the same match the `process-reports` skill uses, and the script imports its `process_report.py` for it.
- **`Formal Verification` is dropped** (not a DeFi category). Other drops go in `config.json` → `drop_tags`.
- **Integration and Fork tags are a judgment call** the Cyfrin tags don't carry. If the audit integrates or forks another protocol, rename that protocol's tag (`LayerZero` → `LayerZero Integration`) or add one (`Angle Fork`). Ask the user when the report doesn't make it obvious.
- Do not commit or push unless the user asks.

## Workflow

1. **Pull the Cyfrin repos** so a just-published report is found:
   ```bash
   git -C <public_repo from config.json> pull -q && git -C <private_repo from config.json> pull -q
   ```
2. **Look up the tags:**
   ```bash
   python3 -I .claude/skills/add-portfolio-audit/scripts/portfolio.py lookup "<report link or PDF filename>"
   ```
   It prints the matched public README row, `cyfrin_tech` (raw) and `tags` (after drops). If it errors:
   - *not in either repo*: wrong link, or the repos aren't pulled.
   - *no 'REDACTED …' row*: the private report was processed without its public placeholder. Tell the user; it has to be added with the `process-reports` skill first.
3. **Decide the final tags**: start from `tags`, apply Integration/Fork naming (see Rules), and keep the Cyfrin wording otherwise. Show the user the row you're about to add if you changed anything.
4. **Add the row and recount:**
   ```bash
   python3 -I .claude/skills/add-portfolio-audit/scripts/portfolio.py add \
       --name "<Project Name>" --date YYYY-MM --report "<link>" [--tags "A, B, C"]
   ```
   - Goes into the `### Cyfrin - Lead Security Researcher` table by default, newest first. Use `--table "### <heading prefix>"` for another table.
   - A **WIP row with the same name is filled in** instead of adding a duplicate.
   - Without `--tags` it uses the looked-up tags as is.
   - `--dry-run` prints the result without writing.
5. **Check the output**: the `counts` block shows the new totals. If `tags_in_no_expertise_group` lists a tag that belongs to an expertise area, add it to that group in `config.json` and run `recount`. Expertise bullets are matched by label (`- <Label> (N)`); a bullet without a group is reported and left alone.
6. Show the user the `git diff` of `README.md`.

## Recount only

After editing tables by hand (or changing `config.json`):
```bash
python3 -I .claude/skills/add-portfolio-audit/scripts/portfolio.py recount
```
It rebuilds, from the tables:
- the **Audits by Category** table, with aliases from `config.json` → `count_aliases` (e.g. `RWA` = `Real-World Assets`, Perpetuals and Leverage grouped)
- the **total audit count** = private engagement rows (WIP rows excluded) + the `~N public contests` figure in the note
- the **listed-contests** count in the note and in the Public Engagements note
- the **integrations / forks** counts (`… Integration` / `… Fork` tags)
- the numbers on the **areas of expertise** bullets (distinct audits per group in `config.json` → `expertise_groups`)

`~N public contests` is hand-maintained (only top-10 placements are listed). When the user's contest total changes, edit that number in the `> In total I've done …` line and run `recount`.
