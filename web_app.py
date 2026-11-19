from __future__ import annotations

import json
import os
import tempfile
from contextlib import ExitStack
from pathlib import Path

import streamlit as st

from docuguard.drift_detector import detect_documentation_drift
from docuguard.ingestion.sources import SourceError, resolve_source
from docuguard.llm_client import LLMError
from docuguard.reporting import render_html_report
from docuguard.suggestion_engine import generate_suggestion

st.set_page_config(page_title="DocuGuard | Documentation Integrity", page_icon="🛡️", layout="wide")

st.markdown("""
<style>
.stApp{background:#f5f7fb}
.hero{padding:1.6rem 1.8rem;border-radius:18px;background:linear-gradient(120deg,#101b35,#263e70);color:white;margin-bottom:1.2rem}
.hero h1{color:white;font-size:2.35rem;margin:0}.hero p{color:#d7e1f5;margin:.35rem 0 0;font-size:1.02rem}
div[data-testid="stMetric"]{background:white;padding:1rem;border:1px solid #e2e8f0;border-radius:12px}
</style>
<div class="hero"><h1>🛡️ DocuGuard</h1><p>Catch documentation that a code change made wrong.</p></div>
""", unsafe_allow_html=True)

with st.sidebar:
    st.markdown("### How it works")
    st.write("1. Connect a Git repository.")
    st.write("2. Choose the code change to inspect.")
    st.write("3. Optionally provide a separate documentation source.")
    st.write("4. Review evidence-backed findings and export a report.")
    st.divider()
    st.caption("Analysis runs locally on the machine hosting this app.")
    st.caption("This interface uses deterministic checks and does not send source code to an AI provider.")

st.markdown("## Analyse a repository")
st.write("Choose a Git repository with commit history. DocuGuard compares the selected commit with its parent or checks uncommitted working-tree changes.")

left, right = st.columns(2)
with left:
    repo_kind = st.selectbox("Code repository source", ["GitHub repository URL", "Local Git repository"])
    if repo_kind == "GitHub repository URL":
        repo_url = st.text_input("GitHub URL", placeholder="https://github.com/owner/repository")
        repo_branch = st.text_input("Branch (optional)", placeholder="Default branch")
        repo_local = ""
    else:
        repo_local = st.text_input("Local repository folder", placeholder="C:\\Projects\\my-repository")
        repo_url = ""
        repo_branch = ""
with right:
    compare_ref = st.text_input("Compare against Git reference", value="HEAD~1", help="HEAD~1 checks the latest committed change. Use HEAD to check uncommitted changes against the current commit.")
    docs_kind = st.selectbox("Documentation source", ["Inside the code repository", "Separate GitHub repository", "Separate local folder", "ZIP archive", "Public documentation website"])
    docs_url = docs_branch = docs_local = docs_website = ""
    docs_zip = None
    if docs_kind == "Separate GitHub repository":
        docs_url = st.text_input("Documentation GitHub URL", placeholder="https://github.com/owner/documentation")
        docs_branch = st.text_input("Documentation branch (optional)", placeholder="Default branch")
    elif docs_kind == "Separate local folder":
        docs_local = st.text_input("Documentation folder", placeholder="C:\\Projects\\my-documentation")
    elif docs_kind == "ZIP archive":
        docs_zip = st.file_uploader("Upload documentation ZIP", type=["zip"])
    elif docs_kind == "Public documentation website":
        docs_website = st.text_input("Documentation website URL", placeholder="https://docs.example.com/")
submitted = st.button("🔍 Analyse repository", type="primary", use_container_width=True)

if submitted:
    st.session_state.pop("docuguard_result", None)
    if not compare_ref.strip():
        st.error("Enter a Git comparison reference, such as HEAD~1 or HEAD.")
    elif repo_kind == "GitHub repository URL" and not repo_url.strip():
        st.error("Enter the GitHub URL of the code repository.")
    elif repo_kind == "Local Git repository" and not repo_local.strip():
        st.error("Enter the local Git repository folder.")
    elif docs_kind == "Separate GitHub repository" and not docs_url.strip():
        st.error("Enter the documentation GitHub URL.")
    elif docs_kind == "Separate local folder" and not docs_local.strip():
        st.error("Enter the documentation folder.")
    elif docs_kind == "ZIP archive" and docs_zip is None:
        st.error("Upload a documentation ZIP archive.")
    elif docs_kind == "Public documentation website" and not docs_website.strip():
        st.error("Enter the public documentation website URL.")
    else:
        try:
            with st.spinner("Preparing repository and analysing documentation drift…"):
                with ExitStack() as stack:
                    upload_root = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="docuguard-upload-")))
                    if repo_kind == "GitHub repository URL":
                        repository, _ = resolve_source(stack, github_url=repo_url.strip(), branch=repo_branch.strip() or None, label="repository")
                    else:
                        repository, _ = resolve_source(stack, local_path=repo_local.strip(), label="repository")
                    if not (repository / ".git").exists():
                        raise SourceError("The code source has no .git history. Use a GitHub URL or a local folder created with git clone. A normal GitHub ZIP download does not contain commit history.")

                    docs_path = None
                    if docs_kind == "Separate GitHub repository":
                        docs_path, _ = resolve_source(stack, github_url=docs_url.strip(), branch=docs_branch.strip() or None, label="docs")
                    elif docs_kind == "Separate local folder":
                        docs_path, _ = resolve_source(stack, local_path=docs_local.strip(), label="docs")
                    elif docs_kind == "ZIP archive":
                        docs_archive = upload_root / "documentation.zip"
                        docs_archive.write_bytes(docs_zip.getvalue())
                        docs_path, _ = resolve_source(stack, zip_path=docs_archive, label="docs")
                    elif docs_kind == "Public documentation website":
                        docs_path, _ = resolve_source(stack, website_url=docs_website.strip(), label="docs")

                    previous_base_ref = os.environ.get("DOCUGUARD_BASE_REF")
                    os.environ["DOCUGUARD_BASE_REF"] = compare_ref.strip()
                    try:
                        findings = detect_documentation_drift(repository, docs_path, llm_mode="off", use_embeddings=False)
                    finally:
                        if previous_base_ref is None:
                            os.environ.pop("DOCUGUARD_BASE_REF", None)
                        else:
                            os.environ["DOCUGUARD_BASE_REF"] = previous_base_ref

                    suggestions = []
                    for finding in findings:
                        if finding.get("status") == "likely_drift":
                            suggestion = generate_suggestion(finding)
                            if suggestion is not None:
                                suggestions.append(suggestion)
                        elif finding.get("status") == "needs_review":
                            evidence = {
                                "symbol": finding.get("symbol"),
                                "old_value": finding.get("old_value"),
                                "new_value": finding.get("new_value"),
                                "code_file": finding["code_change"]["file"],
                                "code_line": finding["code_change"].get("new_line") or finding["code_change"].get("old_line"),
                                "documentation_file": finding["documentation"]["file"],
                                "documentation_line": finding["documentation"]["line"],
                                "confidence": finding.get("confidence"),
                            }
                            suggestions.append({"status": "manual_review_required", "reason": finding.get("reason", "Manual review is recommended."), "evidence": evidence})

                    html_report = render_html_report(findings, suggestions, repository.name)
                    json_report = json.dumps({"findings": findings, "suggestions": suggestions}, indent=2, ensure_ascii=False, default=str)
                    st.session_state["docuguard_result"] = {
                        "repository_name": repository.name,
                        "findings": findings,
                        "suggestions": suggestions,
                        "html": html_report,
                        "json": json_report,
                        "comparison": compare_ref.strip(),
                    }
        except (SourceError, LLMError, OSError, ValueError, RuntimeError) as error:
            st.error(f"Analysis could not be completed: {error}")
        except Exception as error:
            st.error(f"Unexpected analysis error ({type(error).__name__}): {error}")

result = st.session_state.get("docuguard_result")
if result:
    findings = result["findings"]
    suggestions = result["suggestions"]
    likely_count = sum(item.get("status") == "likely_drift" for item in findings)
    review_count = sum(item.get("status") == "needs_review" for item in findings)
    clean_count = sum(item.get("status") == "no_drift" for item in findings)
    st.divider()
    st.markdown(f"## Results: {result['repository_name']}")
    st.caption(f"Comparison reference: {result['comparison']} · Deterministic analysis")
    metrics = st.columns(4)
    metrics[0].metric("Total findings", len(findings))
    metrics[1].metric("Likely drift", likely_count)
    metrics[2].metric("Needs review", review_count)
    metrics[3].metric("No drift", clean_count)
    html_col, json_col = st.columns(2)
    with html_col:
        st.download_button("⬇️ Download HTML report", data=result["html"].encode("utf-8"), file_name="docuguard-report.html", mime="text/html", use_container_width=True)
    with json_col:
        st.download_button("⬇️ Download JSON report", data=result["json"].encode("utf-8"), file_name="docuguard-report.json", mime="application/json", use_container_width=True)
    if not findings:
        st.success("No documentation drift was detected for the selected code change.")
    else:
        st.markdown("### Findings")
        suggestion_by_location = {(item.get("evidence", {}).get("documentation_file"), item.get("evidence", {}).get("documentation_line")): item for item in suggestions}
        for number, finding in enumerate(findings, start=1):
            doc = finding["documentation"]
            code = finding["code_change"]
            code_line = code.get("new_line") or code.get("old_line") or "?"
            status = finding.get("status", "unknown")
            suggestion = suggestion_by_location.get((doc["file"], doc["line"]), {})
            with st.expander(f"{number}. {finding.get('symbol', 'Documentation finding')} · {status.replace('_', ' ')}", expanded=(status == "likely_drift")):
                st.markdown(f"**Documentation:** {doc['file']}:{doc['line']}")
                st.markdown(f"**Code change:** {code['file']}:{code_line}")
                confidence = finding.get("confidence")
                if isinstance(confidence, (int, float)):
                    st.markdown(f"**Confidence:** {confidence:.0%}")
                st.markdown("**Documentation passage**")
                st.info(doc["sentence"])
                st.markdown("**Why this was flagged**")
                st.write(finding.get("reason", "Potential documentation inconsistency."))
                if suggestion.get("suggested_sentence"):
                    st.markdown("**Suggested correction**")
                    st.success(suggestion["suggested_sentence"])
                elif suggestion.get("reason"):
                    st.markdown("**Recommended action**")
                    st.warning(suggestion["reason"])
    st.caption("DocuGuard reports evidence and proposed corrections. Review findings before changing documentation.")
else:
    st.info("Ready when you are. Start with a GitHub repository URL and leave the comparison reference at HEAD~1 to inspect its latest committed change.")
