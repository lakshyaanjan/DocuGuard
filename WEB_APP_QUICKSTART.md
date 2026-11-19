# DocuGuard Web Interface

## Run locally (Windows PowerShell)

From the DocuGuard folder:

```powershell
git pull
python -m pip install -r requirements.txt
python -m streamlit run web_app.py
```

Streamlit opens the app in your browser, normally at http://localhost:8501.

## Test a repository

1. Select **GitHub repository URL** and paste a public repository URL, or select **Local Git repository** and enter a folder created with git clone.
2. Leave **Compare against Git reference** as `HEAD~1` to inspect the latest committed change.
3. Choose **Inside the code repository** if its documentation is in the same repository.
4. Optionally select a separate documentation GitHub repository, local folder, ZIP, or public static documentation website.
5. Click **Analyse repository** and inspect the evidence, suggested corrections, and downloadable HTML/JSON reports.

For a local repository with uncommitted changes, use `HEAD` as the comparison reference. The local folder must contain Git metadata. A regular ZIP download of a code repository does not contain Git history and cannot be used as the code source.

## Current scope

The web interface currently runs deterministic checks only (no API key or source-code upload to an AI provider). Detection is strongest for the Python scalar/configuration changes and literal argparse flag changes handled by the existing DocuGuard engine. Public GitHub code repositories are cloned with the latest commit and its parent so `HEAD~1` can be analysed. Large repositories may take longer to clone.

DocuGuard presents findings as evidence-backed proposals. Review them before editing documentation.
