"""Maintainer-friendly GitHub Actions, JSON, and HTML reporting."""
import html
import json
import os
from pathlib import Path


def render_markdown_summary(findings, suggestions):
    likely = [x for x in findings if x.get("status") == "likely_drift"]
    review = [x for x in findings if x.get("status") == "needs_review"]
    lines = [
        "# DocuGuard documentation report", "",
        f"**{len(likely)} likely drift** · **{len(review)} need review** · **{len(suggestions)} actions**", ""
    ]
    if not findings:
        return "\n".join(lines + ["✅ No documentation drift detected.", ""])
    lines.extend(["| Status | Documentation | Code change | Confidence |", "|---|---|---|---:|"])
    for finding in findings:
        doc = finding["documentation"]
        code = finding["code_change"]
        code_line = code.get("new_line") or code.get("old_line") or "?"
        confidence = finding.get("confidence")
        confidence_text = f"{confidence:.0%}" if isinstance(confidence, (int, float)) else "—"
        lines.append(
            f"| {finding.get('status', 'unknown')} | {doc['file']}:{doc['line']} | "
            f"{code['file']}:{code_line} | {confidence_text} |"
        )
    lines.extend(["", "## Findings"])
    for index, finding in enumerate(findings, start=1):
        doc = finding["documentation"]
        code = finding["code_change"]
        code_line = code.get("new_line") or code.get("old_line") or "?"
        lines.extend([
            "", f"### {index}. {finding.get('symbol', 'Documentation drift')}",
            "", f"**Documentation:** {doc['file']}:{doc['line']}",
            f"**Code:** {code['file']}:{code_line}",
            f"**Evidence:** {doc['sentence']}", "",
            finding.get("reason", "Potential documentation inconsistency.")
        ])
        if finding.get("drift_type") == "configuration_option_added":
            lines.append(
                f"Missing option: {finding['option']} "
                f"(new code default: {finding.get('option_default')})"
            )
        for suggestion in suggestions:
            evidence = suggestion.get("evidence", {})
            if (
                evidence.get("documentation_file") == doc["file"]
                and evidence.get("documentation_line") == doc["line"]
            ):
                if suggestion.get("suggested_sentence"):
                    lines.append(f"Suggested correction: {suggestion['suggested_sentence']}")
                elif suggestion.get("reason"):
                    lines.append(f"Next action: {suggestion['reason']}")
    lines.extend(["", "---", "DocuGuard reports evidence and proposals. Maintainers should review before merging."])
    return "\n".join(lines)


def _display_code_value(value):
    """Format code values for the human-readable old/new comparison."""
    if value is None:
        return "Not available"
    if value == "<removed>":
        return "Removed"
    return str(value)


def render_html_report(findings, suggestions, repository_name="Repository"):
    """Create a self-contained, searchable HTML report with escaped user content."""
    likely = [x for x in findings if x.get("status") == "likely_drift"]
    review = [x for x in findings if x.get("status") == "needs_review"]
    by_location = {}
    for suggestion in suggestions:
        evidence = suggestion.get("evidence", {})
        by_location[(evidence.get("documentation_file"), evidence.get("documentation_line"))] = suggestion

    cards = []
    for index, finding in enumerate(findings, start=1):
        doc = finding["documentation"]
        code = finding["code_change"]
        code_line = code.get("new_line") or code.get("old_line") or "?"
        suggestion = by_location.get((doc["file"], doc["line"]), {})
        correction = suggestion.get("suggested_sentence", "")
        suggestion_reason = suggestion.get("reason", "")
        reason = finding.get("reason", "Potential documentation inconsistency.")
        status = str(finding.get("status", "unknown"))
        status_class = status if status in {"likely_drift", "needs_review"} else "unknown"
        status_label = status.replace("_", " ")
        confidence = finding.get("confidence")
        if isinstance(confidence, (int, float)):
            confidence_label = f"{confidence:.0%}" if 0 <= confidence <= 1 else str(confidence)
        else:
            confidence_label = "Not scored"

        change_html = ""
        drift_type = finding.get("drift_type")
        if drift_type == "configuration_option_added":
            before_value = "Not present"
            after_value = (
                f"{finding.get('option')} (default: "
                f"{_display_code_value(finding.get('option_default'))})"
            )
            change_label = "Configuration option added"
        elif drift_type == "configuration_option_removed":
            before_value = str(finding.get("option", "Option"))
            after_value = "Removed"
            change_label = "Configuration option removed"
        elif "old_value" in finding or "new_value" in finding:
            before_value = _display_code_value(finding.get("old_value"))
            after_value = _display_code_value(finding.get("new_value"))
            change_label = "Code value changed"
        else:
            before_value = after_value = None
            change_label = ""

        if before_value is not None:
            change_html = (
                '<section class="change-panel" aria-label="Code change evidence">'
                f'<div class="section-label">{html.escape(change_label)}</div>'
                '<div class="change-flow">'
                '<div class="value-box before"><span>Before</span>'
                f'<code>{html.escape(before_value)}</code></div>'
                '<div class="change-arrow" aria-hidden="true">→</div>'
                '<div class="value-box after"><span>After</span>'
                f'<code>{html.escape(after_value)}</code></div>'
                '</div></section>'
            )

        option_html = ""
        if drift_type == "configuration_option_added":
            option_html = (
                f'<p class="meta">New option: <code>{html.escape(str(finding.get("option")))}</code>'
                f' · Default: <code>{html.escape(str(finding.get("option_default")))}</code></p>'
            )

        if correction:
            action_html = (
                '<div class="action-box"><div class="section-label">Suggested correction</div>'
                f'<p>{html.escape(str(correction))}</p></div>'
            )
        elif suggestion_reason:
            action_html = (
                '<div class="action-box review-action"><div class="section-label">Maintainer action</div>'
                f'<p>{html.escape(str(suggestion_reason))}</p></div>'
            )
        elif status == "needs_review":
            action_html = (
                '<div class="action-box review-action"><div class="section-label">Maintainer action</div>'
                '<p>Review the passage in context before deciding whether it needs an update.</p></div>'
            )
        else:
            action_html = ""

        search_text = " ".join(str(value) for value in (
            finding.get("symbol", ""), doc.get("file", ""), doc.get("sentence", ""),
            code.get("file", ""), reason, correction, suggestion_reason,
            finding.get("old_value", ""), finding.get("new_value", "")
        )).lower()

        cards.append(
            f'<article class="finding {status_class}" data-finding data-status="{status_class}" '
            f'data-search="{html.escape(search_text, quote=True)}">'
            '<div class="finding-top">'
            f'<span class="pill {status_class}">{html.escape(status_label)}</span>'
            f'<span class="confidence">{html.escape(confidence_label)} confidence</span></div>'
            f'<div class="finding-heading"><span class="finding-number">#{index:02d}</span>'
            f'<h2>{html.escape(str(finding.get("symbol", "Documentation drift")))}</h2></div>'
            '<div class="source-row">'
            f'<span><small>DOCUMENTATION</small><code>{html.escape(str(doc["file"]))}:{doc["line"]}</code></span>'
            f'<span><small>CODE</small><code>{html.escape(str(code["file"]))}:{code_line}</code></span>'
            '</div>'
            f'{change_html}{option_html}'
            '<div class="evidence-box"><div class="section-label">Documentation passage</div>'
            f'<blockquote>{html.escape(str(doc["sentence"]))}</blockquote></div>'
            f'{action_html}'
            f'<details class="why"><summary>Why DocuGuard flagged this</summary><p>{html.escape(str(reason))}</p></details>'
            '</article>'
        )

    if findings:
        body = (
            '<section class="toolbar" aria-label="Findings controls">'
            '<label class="search-label" for="report-search">Search findings</label>'
            '<input id="report-search" type="search" placeholder="Search symbol, file, passage or value..." '
            'autocomplete="off">'
            '<div class="filters" role="group" aria-label="Filter findings">'
            f'<button type="button" class="filter active" data-filter="all" aria-pressed="true">All <b>{len(findings)}</b></button>'
            f'<button type="button" class="filter" data-filter="likely_drift" aria-pressed="false">Likely drift <b>{len(likely)}</b></button>'
            f'<button type="button" class="filter" data-filter="needs_review" aria-pressed="false">Needs review <b>{len(review)}</b></button>'
            '</div>'
            f'<p class="result-count" id="result-count" aria-live="polite">Showing {len(findings)} findings</p>'
            '</section>'
            '<section class="finding-list" aria-label="Documentation findings">'
            + "".join(cards)
            + '</section><section class="no-results" id="no-results" hidden>'
            '<strong>No matching findings</strong><p>Try another search term or choose a different filter.</p></section>'
        )
    else:
        body = (
            '<section class="empty"><div class="check">✓</div>'
            '<span class="empty-kicker">ALL CLEAR</span>'
            '<h2>No documentation drift detected</h2>'
            '<p>The changed code produced no findings in the scanned documentation.</p>'
            '<span class="empty-foot">No maintainer action is needed for this analysis.</span></section>'
        )

    if likely:
        banner = (
            '<div class="status-banner warning"><span class="status-icon">!</span>'
            f'<div><strong>{len(likely)} likely drift issue'
            f'{"s" if len(likely) != 1 else ""} need attention</strong>'
            '<span>Review the evidence and suggested corrections before merging.</span></div></div>'
        )
    elif review:
        banner = (
            '<div class="status-banner review"><span class="status-icon">?</span>'
            f'<div><strong>{len(review)} item'
            f'{"s" if len(review) != 1 else ""} need human review</strong>'
            '<span>No high-confidence drift was identified, but these passages need context.</span></div></div>'
        )
    else:
        banner = (
            '<div class="status-banner success"><span class="status-icon">✓</span>'
            '<div><strong>No likely documentation drift</strong>'
            '<span>The scanned documentation appears consistent with the changed code.</span></div></div>'
        )

    css = """
:root{color-scheme:light;--bg:#f3f6fb;--panel:#fff;--ink:#14223b;--muted:#65738a;--line:#e1e8f2;--blue:#3858c8;--blue-soft:#edf2ff;--red:#b42318;--red-soft:#fff0ef;--amber:#91600c;--amber-soft:#fff7e7;--green:#167449;--green-soft:#eaf7ef}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
main{max-width:1060px;margin:auto;padding:34px 24px 64px}.hero{display:flex;align-items:center;justify-content:space-between;gap:18px;padding:23px 26px;border-radius:20px;background:linear-gradient(125deg,#142747,#233d70);color:#fff;box-shadow:0 12px 30px #1b31501c}
.brand{display:flex;align-items:center;gap:14px}.mark{width:48px;height:48px;display:grid;place-items:center;border-radius:15px;background:#eaf0ff;color:#294dbb;font-size:22px;font-weight:850;letter-spacing:-1px}
h1{margin:0;font-size:25px;letter-spacing:-.5px}.subtitle{color:#d4def0;font-size:13px}.repo-name{margin-top:3px;color:#b6c6df;font-size:12px}.hero-meta{color:#d4def0;font-size:12px;text-align:right}
.status-banner{display:flex;gap:13px;align-items:center;margin:20px 0 17px;padding:15px 18px;border:1px solid var(--line);border-radius:14px;background:var(--panel)}
.status-icon{width:31px;height:31px;flex:0 0 31px;display:grid;place-items:center;border-radius:50%;font-weight:850}.status-banner strong,.status-banner span{display:block}.status-banner strong{font-size:14px}.status-banner div span{margin-top:1px;color:var(--muted);font-size:12px}
.status-banner.warning{border-color:#f2d1ce;background:#fffafa}.status-banner.warning .status-icon{background:var(--red-soft);color:var(--red)}
.status-banner.review{border-color:#f0dfbd;background:#fffcf5}.status-banner.review .status-icon{background:var(--amber-soft);color:var(--amber)}
.status-banner.success{border-color:#cfe8d8;background:#f8fdf9}.status-banner.success .status-icon{background:var(--green-soft);color:var(--green)}
.stats{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:13px;margin:0 0 20px}.stat{padding:17px 19px;background:var(--panel);border:1px solid var(--line);border-radius:15px}
.stat b{display:block;font-size:29px;line-height:1.15;letter-spacing:-1px}.stat span{display:block;margin-top:6px;color:var(--muted);font-size:12px}
.toolbar{padding:18px 19px;background:var(--panel);border:1px solid var(--line);border-radius:15px;margin:20px 0 15px}
.search-label,.section-label{display:block;color:#66758d;font-size:10px;font-weight:800;letter-spacing:.09em;text-transform:uppercase}
input[type=search]{width:100%;margin-top:7px;padding:11px 13px;border:1px solid #d7e0ed;border-radius:10px;background:#fbfcff;color:var(--ink);font:inherit;outline:none}
input[type=search]:focus{border-color:#8199eb;box-shadow:0 0 0 3px #3858c81a}.filters{display:flex;flex-wrap:wrap;gap:8px;margin-top:13px}
.filter{padding:7px 11px;border:1px solid var(--line);border-radius:9px;background:#fff;color:#4e5c72;font:600 12px inherit;cursor:pointer}
.filter b{margin-left:5px;color:inherit}.filter:hover{border-color:#b9c8e7}.filter.active{border-color:#cbd7ff;background:var(--blue-soft);color:var(--blue)}
.result-count{margin:12px 0 0;color:var(--muted);font-size:11px}
.finding{margin:13px 0;padding:21px 23px;background:var(--panel);border:1px solid var(--line);border-left:4px solid #d1a24a;border-radius:15px;box-shadow:0 3px 12px #243a5910}
.finding.likely_drift{border-left-color:#db6258}.finding.needs_review{border-left-color:#d1a24a}
.finding-top{display:flex;align-items:center;justify-content:space-between;gap:12px}.pill{display:inline-flex;padding:4px 9px;border-radius:999px;background:#eef1f6;color:#58667c;font-size:10px;font-weight:800;letter-spacing:.035em;text-transform:uppercase}
.pill.likely_drift{background:var(--red-soft);color:var(--red)}.pill.needs_review{background:var(--amber-soft);color:var(--amber)}
.confidence{color:var(--muted);font-size:11px;font-weight:650}.finding-heading{display:flex;align-items:center;gap:10px;margin-top:10px}.finding-heading h2{margin:0;font-size:19px;letter-spacing:-.35px}
.finding-number{color:#9aa6b8;font-size:11px;font-weight:800;font-variant-numeric:tabular-nums}
.source-row{display:flex;flex-wrap:wrap;gap:10px 22px;margin:13px 0 15px}.source-row span{display:flex;align-items:center;gap:8px}
.source-row small{color:#8995a8;font-size:9px;font-weight:800;letter-spacing:.08em}.source-row code{color:#3e516f;font-size:11px}
code{padding:3px 6px;border:1px solid #e8edf4;border-radius:6px;background:#f6f8fc;font:600 12px ui-monospace,SFMono-Regular,Consolas,monospace;overflow-wrap:anywhere}
.change-panel,.evidence-box{margin-top:13px;padding:13px 15px;border:1px solid var(--line);border-radius:11px;background:#fbfcfe}
.change-flow{display:grid;grid-template-columns:minmax(0,1fr) 28px minmax(0,1fr);align-items:center;gap:10px;margin-top:9px}
.value-box{min-width:0;padding:10px 11px;border-radius:9px}.value-box span{display:block;margin-bottom:5px;color:var(--muted);font-size:10px;font-weight:800;text-transform:uppercase;letter-spacing:.07em}
.value-box code{display:inline-block;max-width:100%;overflow-wrap:anywhere}.value-box.before{background:#fff1f0;border:1px solid #f5dedb}.value-box.after{background:#eef8f2;border:1px solid #d8eee1}
.value-box.before code{color:#a12822}.value-box.after code{color:#17623f}.change-arrow{text-align:center;color:#8795aa;font-size:19px;font-weight:800}
.evidence-box blockquote{margin:8px 0 0;padding:11px 13px;border-left:3px solid #90a8ed;border-radius:0 8px 8px 0;background:#f3f6ff;color:#263650}
.action-box{margin-top:13px;padding:13px 15px;border:1px solid #cfe8d8;border-radius:11px;background:var(--green-soft);color:#185d3c}.action-box .section-label{color:#397858}.action-box p{margin:6px 0 0;overflow-wrap:anywhere}
.action-box.review-action{border-color:#f0dfbd;background:#fffbf1;color:#6d4e19}.action-box.review-action .section-label{color:#91600c}
.why{margin-top:13px;color:var(--muted);font-size:12px}.why summary{cursor:pointer;font-weight:650}.why p{margin:7px 0 0}
.empty,.no-results{padding:45px 20px;text-align:center;background:var(--panel);border:1px solid var(--line);border-radius:16px}.empty .check{font-size:37px;color:var(--green)}
.empty-kicker{display:block;margin-top:8px;color:var(--green);font-size:10px;font-weight:850;letter-spacing:.12em}.empty h2{margin:8px 0 5px;font-size:20px}.empty p,.no-results p{margin:0;color:var(--muted);font-size:13px}.empty-foot{display:inline-block;margin-top:16px;color:var(--muted);font-size:11px}
.no-results[hidden],.finding[hidden]{display:none}.no-results strong{font-size:15px}
footer{display:flex;justify-content:space-between;gap:12px;margin-top:25px;padding-top:15px;border-top:1px solid var(--line);color:var(--muted);font-size:11px}
@media(max-width:650px){main{padding:18px 12px 40px}.hero{padding:17px;border-radius:15px}.hero-meta{display:none}h1{font-size:22px}.stats{gap:7px}.stat{padding:13px}.stat b{font-size:24px}.stat span{font-size:10px}.finding{padding:16px}.change-flow{grid-template-columns:minmax(0,1fr) 18px minmax(0,1fr);gap:5px}.value-box{padding:8px}.source-row{gap:9px 13px}}
@media(prefers-reduced-motion:no-preference){.finding{transition:box-shadow .16s ease,transform .16s ease}.finding:hover{box-shadow:0 8px 22px #243a5914;transform:translateY(-1px)}}
"""
    script = """
<script>
(() => {
  const cards = Array.from(document.querySelectorAll('[data-finding]'));
  if (!cards.length) return;
  const search = document.getElementById('report-search');
  const buttons = Array.from(document.querySelectorAll('[data-filter]'));
  const count = document.getElementById('result-count');
  const empty = document.getElementById('no-results');
  let activeFilter = 'all';

  function applyFilters() {
    const query = search.value.trim().toLowerCase();
    let visible = 0;
    cards.forEach((card) => {
      const matchesFilter = activeFilter === 'all' || card.dataset.status === activeFilter;
      const matchesQuery = !query || card.dataset.search.includes(query);
      const show = matchesFilter && matchesQuery;
      card.hidden = !show;
      if (show) visible += 1;
    });
    count.textContent = 'Showing ' + visible + ' of ' + cards.length + ' findings';
    empty.hidden = visible !== 0;
  }

  buttons.forEach((button) => {
    button.addEventListener('click', () => {
      activeFilter = button.dataset.filter;
      buttons.forEach((item) => {
        const active = item === button;
        item.classList.toggle('active', active);
        item.setAttribute('aria-pressed', String(active));
      });
      applyFilters();
    });
  });
  search.addEventListener('input', applyFilters);
})();
</script>
"""

    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<meta name='color-scheme' content='light'>"
        "<title>DocuGuard · Documentation report</title><style>" + css + "</style></head><body><main>"
        "<header class='hero'><div class='brand'><div class='mark'>DG</div><div>"
        "<h1>DocuGuard</h1><div class='subtitle'>Documentation drift report</div>"
        f"<div class='repo-name'>{html.escape(str(repository_name))}</div></div></div>"
        "<div class='hero-meta'>CODE ↔ DOCUMENTATION<br>MAINTAINER REPORT</div></header>"
        + banner
        + "<section class='stats' aria-label='Finding summary'>"
        f"<div class='stat'><b>{len(findings)}</b><span>Total findings</span></div>"
        f"<div class='stat'><b>{len(likely)}</b><span>Likely drift</span></div>"
        f"<div class='stat'><b>{len(review)}</b><span>Needs review</span></div></section>"
        + body
        + "<footer><span>DocuGuard · Evidence-first documentation analysis</span>"
        "<span>Suggestions are proposals; maintainers make the final decision.</span></footer>"
        + script
        + "</main></body></html>"
    )


def _escape_property(value):
    return (
        str(value).replace("%", "%25").replace("\r", "%0D")
        .replace("\n", "%0A").replace(":", "%3A").replace(",", "%2C")
    )


def _escape_data(value):
    return str(value).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def write_github_annotations(findings):
    """Emit GitHub Actions annotations on relevant documentation lines."""
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return
    for finding in findings:
        doc = finding["documentation"]
        code = finding["code_change"]
        level = "warning" if finding.get("status") == "likely_drift" else "notice"
        code_line = code.get("new_line") or code.get("old_line") or "?"
        title = f"DocuGuard: {finding.get('status', 'finding').replace('_', ' ')}"
        message = (
            f"{finding.get('reason', 'Potential documentation drift')} "
            f"Code reference: {code['file']}:{code_line}"
        )
        properties = (
            f"file={_escape_property(doc['file'])},"
            f"line={doc['line']},title={_escape_property(title)}"
        )
        print(f"::{level} {properties}::{_escape_data(message)}")


def write_step_summary(markdown):
    """Append the report to the GitHub Actions job summary if available."""
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return False
    with open(summary_path, "a", encoding="utf-8") as summary_file:
        summary_file.write(markdown + "\n")
    return True


def write_json_report(path, findings, suggestions):
    """Write machine-readable results."""
    payload = {"findings": findings, "suggestions": suggestions}
    Path(path).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8"
    )
