
import ast
from pathlib import Path


def extract_python_symbols(file_path):
    """Extract important Python symbols and their values."""

    source = Path(file_path).read_text(encoding="utf-8")

    try:
        tree = ast.parse(source)
    except SyntaxError as error:
        return {
            "file": str(file_path),
            "error": str(error),
            "symbols": []
        }

    symbols = []

    for node in ast.walk(tree):

        # Detect variable and constant assignments
        if isinstance(node, ast.Assign):

            for target in node.targets:

                if isinstance(target, ast.Name):

                    symbols.append({
                        "type": "assignment",
                        "name": target.id,
                        "value": ast.unparse(node.value),
                        "line": node.lineno
                    })

        # Detect functions
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):

            symbols.append({
                "type": "function",
                "name": node.name,
                "line": node.lineno,
                "parameters": [
                    arg.arg for arg in node.args.args
                ]
            })

        # Detect classes
        elif isinstance(node, ast.ClassDef):

            symbols.append({
                "type": "class",
                "name": node.name,
                "line": node.lineno
            })

    return {
        "file": str(file_path),
        "symbols": symbols
    }


def index_repository(repo_path):
    """Index all Python files in a repository."""

    repository = Path(repo_path)
    results = []

    for file_path in repository.rglob("*.py"):

        if ".git" in file_path.parts:
            continue

        results.append(extract_python_symbols(file_path))

    return results


if __name__ == "__main__":

    repository = Path(__file__).resolve().parent.parent

    indexed_data = index_repository(repository)

    import json
    print(json.dumps(indexed_data, indent=4))
