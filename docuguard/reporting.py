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


def render_html_report(findings, suggestions, repository_name="Repository"):
    """Create a self-contained, responsive HTML report with escaped user content."""
    likely = [x for x in findings if x.get("status") == "likely_drift"]
    review = [x for x in findings if x.get("status") == "needs_review"]
    by_location = {}
    for suggestion in suggestions:
        evidence = suggestion.get("evidence", {})
        by_location[(evidence.get("documentation_file"), evidence.get("documentation_line"))] = suggestion

    cards = []
    for finding in findings:
        doc = finding["documentation"]
        code = finding["code_change"]
        code_line = code.get("new_line") or code.get("old_line") or "?"
        suggestion = by_location.get((doc["file"], doc["line"]), {})
        correction = suggestion.get("suggested_sentence", "")
        reason = suggestion.get("reason") or finding.get("reason", "")
        option_html = ""
        if finding.get("drift_type") == "configuration_option_added":
            option_html = (
                f'<p class="meta">Missing option: <code>{html.escape(str(finding["option"]))}</code>'
                f' · New default: <code>{html.escape(str(finding.get("option_default")))}</code></p>'
            )
        correction_html = (
            '<div class="correction"><strong>Suggested correction</strong>'
            f'<p>{html.escape(correction)}</p></div>'
            if correction else ""
        )
        cards.append(
            '<article class="finding">'
            f'<div class="top"><span class="pill {html.escape(finding.get("status", "unknown"))}">'
            f'{html.escape(finding.get("status", "unknown").replace("_", " "))}</span>'
            f'<span>{html.escape(str(finding.get("confidence", 0)))} confidence</span></div>'
            f'<h2>{html.escape(str(finding.get("symbol", "Documentation drift")))}</h2>'
            f'<p class="meta">Docs <code>{html.escape(doc["file"])}:{doc["line"]}</code>'
            f' · Code <code>{html.escape(code["file"])}:{code_line}</code></p>'
            f'{option_html}'
            f'<blockquote>{html.escape(doc["sentence"])}</blockquote>'
            f'{correction_html}<p class="reason">{html.escape(reason)}</p></article>'
        )
    body = "".join(cards) if findings else (
        '<section class="empty"><div class="check">✓</div>'
        '<h2>No documentation drift detected</h2>'
        '<p>The changed code produced no findings in the scanned documentation.</p></section>'
    )
    css = """
:root{--bg:#f4f6fa;--panel:#fff;--ink:#172033;--muted:#68748a;--line:#e4e9f1;--blue:#3659c9;--red:#b42318;--amber:#8a5a00;--green:#137547}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 Inter,system-ui,sans-serif}
main{max-width:1000px;margin:auto;padding:40px 22px 70px}header{display:flex;justify-content:space-between;gap:18px;align-items:center}
.brand{display:flex;gap:12px;align-items:center}.mark{width:42px;height:42px;border-radius:13px;background:#e9efff;color:var(--blue);display:grid;place-items:center;font-weight:800;font-size:21px}
h1{margin:0;font-size:26px}.subtitle,.meta,.reason{color:var(--muted)}.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin:25px 0}
.stat,.finding,.empty{background:var(--panel);border:1px solid var(--line);border-radius:15px}.stat{padding:18px}.stat b{display:block;font-size:28px}.stat span{color:var(--muted);font-size:13px}
.finding{padding:22px;margin:12px 0}.top{display:flex;justify-content:space-between;color:var(--muted);font-size:12px}
.pill{padding:4px 10px;border-radius:999px;background:#fff2d3;color:var(--amber);font-weight:700;text-transform:capitalize}
.pill.likely_drift{background:#feeceb;color:var(--red)}h2{font-size:18px;margin:14px 0 4px}
.meta{font-size:13px}code{background:#f1f4f9;padding:2px 5px;border-radius:5px}
blockquote{margin:14px 0;padding:12px 15px;border-left:3px solid #9aafea;background:#f7f9ff;border-radius:0 9px 9px 0}
.correction{margin-top:14px;padding:13px 15px;background:#eef8f2;border:1px solid #d8eee1;border-radius:10px;color:#175b3b}
.empty{text-align:center;padding:50px 20px}.check{font-size:32px;color:var(--green)}
footer{margin-top:28px;padding-top:15px;border-top:1px solid var(--line);font-size:12px;color:var(--muted)}
@media(max-width:640px){main{padding:25px 14px}.stats{gap:7px}.stat{padding:12px}.stat b{font-size:22px}.finding{padding:16px}}
"""
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>DocuGuard report</title><style>" + css + "</style></head><body><main>"
        "<header><div class='brand'><div class='mark'>D</div><div>"
        "<h1>DocuGuard</h1><div class='subtitle'>Documentation drift report</div>"
        f"<div class='meta'>{html.escape(repository_name)}</div></div></div>"
        "<div class='meta'>Generated by DocuGuard</div></header>"
        "<section class='stats'>"
        f"<div class='stat'><b>{len(findings)}</b><span>Total findings</span></div>"
        f"<div class='stat'><b>{len(likely)}</b><span>Likely drift</span></div>"
        f"<div class='stat'><b>{len(review)}</b><span>Needs review</span></div></section>"
        + body
        + "<footer>Evidence points to the documentation passage and code change. Suggestions are proposals for maintainer review.</footer>"
        "</main></body></html>"
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
