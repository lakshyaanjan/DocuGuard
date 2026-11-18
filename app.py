
import sys
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
        return 0

    print(f"Found {len(suggestions)} potential documentation issue(s).\n")

    for index, suggestion in enumerate(suggestions, start=1):

        evidence = suggestion["evidence"]

        print(f"ISSUE #{index}")
        print("-" * 55)

        print("Status:", suggestion["status"])

        if "original_sentence" in suggestion:
            print("\nOutdated documentation:")
            print(suggestion["original_sentence"])

        if "suggested_sentence" in suggestion:
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

        if "explanation" in suggestion:
            print("\nExplanation:")
            print(suggestion["explanation"])

        if "reason" in suggestion:
            print("\nReason:")
            print(suggestion["reason"])

        print("-" * 55)

    print("\nDocuGuard analysis completed.")
    print("Documentation issues require attention.")

    return 1


if __name__ == "__main__":
    sys.exit(main())
