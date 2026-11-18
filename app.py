
import json
from pathlib import Path

from docuguard.suggestion_engine import generate_all_suggestions


def main():

    repository = Path(__file__).resolve().parent

    print("=" * 55)
    print("                  DOCUGUARD")
    print("       Documentation Drift Detection System")
    print("=" * 55)

    print("\nAnalyzing repository...\n")

    suggestions = generate_all_suggestions(repository)

    if not suggestions:
        print("No documentation drift detected.")
        return

    print(f"Found {len(suggestions)} potential documentation issue(s).\n")

    for index, suggestion in enumerate(suggestions, start=1):

        evidence = suggestion["evidence"]

        print(f"ISSUE #{index}")
        print("-" * 55)

        print("Status:", suggestion["status"])

        print("\nOutdated documentation:")
        print(suggestion["original_sentence"])

        print("\nSuggested correction:")
        print(suggestion["suggested_sentence"])

        print("\nEvidence:")
        print(
            f"Code: {evidence['code_file']}:"
            f"{evidence['code_line']}"
        )
        print(
            f"Documentation: "
            f"{evidence['documentation_file']}:"
            f"{evidence['documentation_line']}"
        )

        print("\nExplanation:")
        print(suggestion["explanation"])

        print("-" * 55)


if __name__ == "__main__":
    main()
