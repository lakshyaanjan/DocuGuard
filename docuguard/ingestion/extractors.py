"""Extract documentation and source-code chunks with line-level provenance.

This module deliberately uses only Python's standard library. It is an
ingestion layer, not a semantic index: no embeddings or model calls happen here.
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from html.parser import HTMLParser
from typing import Any

from .policy import DOCUMENTATION_EXTENSIONS, MAX_CHUNK_CHARS, MAX_TEXT_LINES


def _clip_lines(lines: list[str], start: int, end: int) -> str:
    return "\n".join(lines[max(0, start - 1):min(len(lines), end)])


def _split_large_text_with_lines(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[tuple[str, int, int]]:
    """Split text at line boundaries and retain relative start/end line offsets."""
    lines = text.splitlines()
    if not lines:
        return []
    pieces: list[tuple[str, int, int]] = []
    current: list[str] = []
    current_start = 0
    size = 0

    def flush() -> None:
        nonlocal current, size
        if current:
            pieces.append(("\n".join(current), current_start, current_start + len(current) - 1))
            current = []
            size = 0

    for line_index, line in enumerate(lines):
        if len(line) > max_chars:
            flush()
            for offset in range(0, len(line), max_chars):
                part = line[offset:offset + max_chars]
                if part.strip():
                    pieces.append((part, line_index, line_index))
            continue
        if current and size + len(line) + 1 > max_chars:
            flush()
        if not current:
            current_start = line_index
        current.append(line)
        size += len(line) + 1
    flush()
    return [piece for piece in pieces if piece[0].strip()]


def _split_large_text(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """Compatibility helper returning only the split text pieces."""
    return [piece for piece, _, _ in _split_large_text_with_lines(text, max_chars)]


def _new_raw_chunk(
    *, kind: str, content: str, start_line: int, end_line: int,
    language: str | None = None, symbol: str | None = None,
    parent_symbol: str | None = None, section: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "content": content.strip("\n"),
        "start_line": start_line,
        "end_line": max(start_line, end_line),
        "language": language,
        "symbol": symbol,
        "parent_symbol": parent_symbol,
        "section": section,
        "metadata": metadata or {},
    }


def _paragraph_chunks(
    lines: list[str], start_line: int, *, section: str | None,
    kind: str = "documentation_paragraph", language: str | None = None,
) -> list[dict[str, Any]]:
    text = "\n".join(line.rstrip() for line in lines).strip()
    if not text:
        return []
    parts = _split_large_text_with_lines(text)
    chunks = []
    for part, relative_start, relative_end in parts:
        chunks.append(_new_raw_chunk(
            kind=kind, content=part, start_line=start_line + relative_start,
            end_line=start_line + relative_end, language=language, section=section,
        ))
    return chunks


class _HTMLContentParser(HTMLParser):
    """Small HTML content extractor retaining approximate source line numbers."""

    BLOCK_TAGS = {
        "p", "li", "tr", "td", "th", "h1", "h2", "h3", "h4", "h5", "h6",
        "pre", "blockquote", "dt", "dd",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.chunks: list[dict[str, Any]] = []
        self.section: str | None = None
        self.stack: list[tuple[str, int, list[str], str | None]] = []
        self.code_depth = 0
        self.code_language: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "pre":
            self.code_depth += 1
            self.code_language = None
        if tag == "code" and self.code_depth:
            class_value = attributes.get("class") or ""
            match = re.search(r"(?:language|lang)-([\w+#.-]+)", class_value)
            if match:
                self.code_language = match.group(1)
        if tag in self.BLOCK_TAGS:
            self.stack.append((tag, self.getpos()[0], [], self.section))

    def handle_data(self, data: str) -> None:
        if not data.strip():
            return
        if self.stack:
            tag, line, pieces, old_section = self.stack[-1]
            pieces.append(data)
            self.stack[-1] = (tag, line, pieces, old_section)

    def handle_endtag(self, tag: str) -> None:
        if tag in self.BLOCK_TAGS:
            for index in range(len(self.stack) - 1, -1, -1):
                if self.stack[index][0] == tag:
                    open_tag, line, pieces, _ = self.stack.pop(index)
                    content = re.sub(r"\s+", " ", " ".join(pieces)).strip()
                    if content:
                        if open_tag in {"td", "th"} and self.stack and self.stack[-1][0] == "tr":
                            parent_tag, parent_line, parent_pieces, parent_section = self.stack[-1]
                            parent_pieces.append(content)
                            self.stack[-1] = (parent_tag, parent_line, parent_pieces, parent_section)
                        elif open_tag == "tr":
                            cells = [cell.strip() for cell in pieces if cell.strip()]
                            self.chunks.append(_new_raw_chunk(
                                kind="documentation_table_row", content="| " + " | ".join(cells) + " |",
                                start_line=line, end_line=max(line, self.getpos()[0]), section=self.section,
                            ))
                        elif open_tag == "p" and any(tag in {"td", "th"} for tag, *_ in self.stack):
                            for parent_index in range(len(self.stack) - 1, -1, -1):
                                if self.stack[parent_index][0] in {"td", "th"}:
                                    parent_tag, parent_line, parent_pieces, parent_section = self.stack[parent_index]
                                    parent_pieces.append(content)
                                    self.stack[parent_index] = (parent_tag, parent_line, parent_pieces, parent_section)
                                    break
                        elif open_tag.startswith("h") and open_tag[1:].isdigit():
                            self.section = content
                            self.chunks.append(_new_raw_chunk(
                                kind="documentation_heading", content=content,
                                start_line=line, end_line=line,
                                metadata={"heading_level": int(open_tag[1:])},
                            ))
                        elif self.code_depth:
                            self.chunks.append(_new_raw_chunk(
                                kind="code_example", content=content,
                                start_line=line, end_line=max(line, self.getpos()[0]),
                                language=self.code_language,
                                section=self.section,
                            ))
                        else:
                            kind = "documentation_list_item" if open_tag == "li" else "documentation_paragraph"
                            self.chunks.append(_new_raw_chunk(
                                kind=kind, content=content, start_line=line,
                                end_line=max(line, self.getpos()[0]), section=self.section,
                            ))
                    break
        if tag == "pre" and self.code_depth:
            self.code_depth -= 1
            if not self.code_depth:
                self.code_language = None


def _extract_html(text: str) -> list[dict[str, Any]]:
    parser = _HTMLContentParser()
    try:
        parser.feed(text)
        parser.close()
    except Exception:
        # Malformed HTML should not prevent the rest of the repository ingest.
        return _extract_plain_documentation(text)
    return parser.chunks


def _extract_markdown_or_rst(text: str, extension: str) -> list[dict[str, Any]]:
    lines = text.splitlines()
    chunks: list[dict[str, Any]] = []
    paragraph: list[str] = []
    paragraph_start = 1
    section_stack: list[tuple[int, str]] = []
    i = 0

    def current_section() -> str | None:
        return " / ".join(label for _, label in section_stack) or None

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            chunks.extend(_paragraph_chunks(
                paragraph, paragraph_start, section=current_section()
            ))
            paragraph = []

    while i < len(lines):
        raw = lines[i]
        stripped = raw.strip()
        line_number = i + 1

        if not stripped:
            flush_paragraph()
            i += 1
            continue

        # Markdown fenced code blocks.
        fence = re.match(r"^\s*(`{3,}|~{3,})\s*([\w+#.-]*)?.*$", raw)
        if fence:
            flush_paragraph()
            marker = fence.group(1)
            language = (fence.group(2) or "").strip() or None
            code_lines: list[str] = []
            code_start = i + 2
            i += 1
            while i < len(lines) and not re.match(
                r"^\s*" + re.escape(marker[0]) + "{" + str(len(marker)) + r",}\s*$", lines[i]
            ):
                code_lines.append(lines[i])
                i += 1
            if code_lines:
                for part, relative_start, relative_end in _split_large_text_with_lines("\n".join(code_lines)):
                    chunks.append(_new_raw_chunk(
                        kind="code_example", content=part,
                        start_line=code_start + relative_start,
                        end_line=code_start + relative_end,
                        language=language, section=current_section(),
                        metadata={"fenced": True},
                    ))
            i += 1
            continue

        # reStructuredText code-block/code directives and indented literal blocks.
        rst_directive = re.match(r"^\s*\.\.\s+code(?:-block|)::\s*([\w+#.-]*)", raw) if extension in {".rst", ".txt"} else None
        if rst_directive:
            flush_paragraph()
            language = rst_directive.group(1) or None
            directive_indent = len(raw) - len(raw.lstrip())
            i += 1
            while i < len(lines) and not lines[i].strip():
                i += 1
            code_start = i + 1
            code_lines = []
            while i < len(lines):
                candidate = lines[i]
                if candidate.strip() and len(candidate) - len(candidate.lstrip()) <= directive_indent:
                    break
                code_lines.append(candidate[directive_indent + 3:] if candidate.startswith(" " * (directive_indent + 3)) else candidate.lstrip())
                i += 1
            while code_lines and not code_lines[-1].strip():
                code_lines.pop()
            if code_lines:
                chunks.append(_new_raw_chunk(
                    kind="code_example", content="\n".join(code_lines),
                    start_line=code_start, end_line=code_start + len(code_lines) - 1,
                    language=language, section=current_section(),
                    metadata={"rst_directive": True},
                ))
            continue

        # Markdown headings.
        markdown_heading = re.match(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$", raw)
        if markdown_heading:
            flush_paragraph()
            level = len(markdown_heading.group(1))
            title = markdown_heading.group(2).strip()
            section_stack = [(depth, label) for depth, label in section_stack if depth < level]
            section_stack.append((level, title))
            chunks.append(_new_raw_chunk(
                kind="documentation_heading", content=title,
                start_line=line_number, end_line=line_number,
                metadata={"heading_level": level},
            ))
            i += 1
            continue

        # reStructuredText heading underline.
        if i + 1 < len(lines) and re.fullmatch(r"\s*[=\-~^\"`:#*+]{3,}\s*", lines[i + 1]):
            flush_paragraph()
            title = stripped
            underline = lines[i + 1].strip()
            level = {"=": 1, "-": 2, "~": 3, "^": 4}.get(underline[0], 5)
            section_stack = [(depth, label) for depth, label in section_stack if depth < level]
            section_stack.append((level, title))
            chunks.append(_new_raw_chunk(
                kind="documentation_heading", content=title,
                start_line=line_number, end_line=line_number + 1,
                metadata={"heading_level": level},
            ))
            i += 2
            continue

        # Markdown table rows are retained individually for exact row evidence.
        if stripped.startswith("|") and stripped.endswith("|"):
            flush_paragraph()
            if not re.fullmatch(r"\|[\s:|\-]+\|", stripped):
                chunks.append(_new_raw_chunk(
                    kind="documentation_table_row", content=stripped,
                    start_line=line_number, end_line=line_number,
                    section=current_section(),
                ))
            i += 1
            continue

        # Markdown/RST list items are kept as individual evidence chunks.
        if re.match(r"^\s*(?:[-+*]\s+|\d+[.)]\s+|\*\s+)", raw):
            flush_paragraph()
            chunks.append(_new_raw_chunk(
                kind="documentation_list_item", content=stripped,
                start_line=line_number, end_line=line_number,
                section=current_section(),
            ))
            i += 1
            continue

        if not paragraph:
            paragraph_start = line_number
        paragraph.append(raw)
        i += 1

    flush_paragraph()
    return chunks


def _extract_plain_documentation(text: str) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    lines = text.splitlines()
    current: list[str] = []
    start = 1
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            if current:
                chunks.extend(_paragraph_chunks(current, start, section=None))
                current = []
        else:
            if not current:
                start = number
            current.append(line)
    if current:
        chunks.extend(_paragraph_chunks(current, start, section=None))
    return chunks


def extract_documentation(text: str, extension: str) -> list[dict[str, Any]]:
    extension = extension.lower()
    if extension in {".html", ".htm", ".xhtml"}:
        return _extract_html(text)
    if extension in {".md", ".markdown", ".mdown", ".rst", ".adoc", ".asciidoc", ".txt"}:
        return _extract_markdown_or_rst(text, extension)
    return _extract_plain_documentation(text)


def _python_ast_chunks(text: str) -> list[dict[str, Any]]:
    lines = text.splitlines()
    try:
        tree = ast.parse(text)
    except SyntaxError as error:
        return [_new_raw_chunk(
            kind="source_file", content=text[:MAX_CHUNK_CHARS],
            start_line=1, end_line=min(len(lines), max(1, text[:MAX_CHUNK_CHARS].count("\n") + 1)),
            language="python", metadata={"parse_error": str(error)},
        )]

    chunks: list[dict[str, Any]] = []

    # Module docstring.
    module_doc = ast.get_docstring(tree, clean=False)
    if module_doc and tree.body and isinstance(tree.body[0], ast.Expr):
        node = tree.body[0]
        value = node.value
        start = getattr(value, "lineno", node.lineno)
        end = getattr(value, "end_lineno", node.end_lineno or start)
        chunks.append(_new_raw_chunk(
            kind="python_docstring", content=module_doc,
            start_line=start, end_line=end, language="python",
            symbol="<module>", metadata={"scope": "module"},
        ))

    class _Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.scope: list[str] = []

        def _visit_assignment(self, node: ast.Assign | ast.AnnAssign | ast.AugAssign) -> None:
            start = node.lineno
            end = getattr(node, "end_lineno", start)
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names = [target.id for target in targets if isinstance(target, ast.Name)]
            chunks.append(_new_raw_chunk(
                kind="python_assignment", content=_clip_lines(lines, start, end),
                start_line=start, end_line=end, language="python",
                symbol=", ".join(names) if names else None,
                parent_symbol=".".join(self.scope) or None,
            ))

        def visit_Assign(self, node: ast.Assign) -> None:
            self._visit_assignment(node)

        def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
            self._visit_assignment(node)

        def visit_AugAssign(self, node: ast.AugAssign) -> None:
            self._visit_assignment(node)

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            parent = ".".join(self.scope) or None
            symbol = ".".join([*self.scope, node.name])
            start = min([node.lineno, *[decorator.lineno for decorator in node.decorator_list]])
            end = getattr(node, "end_lineno", node.lineno)
            content = _clip_lines(lines, start, end)
            chunks.append(_new_raw_chunk(
                kind="python_class", content=content, start_line=start,
                end_line=end, language="python", symbol=symbol,
                parent_symbol=parent,
            ))
            doc = ast.get_docstring(node, clean=False)
            if doc and node.body and isinstance(node.body[0], ast.Expr):
                expr = node.body[0]
                value = expr.value
                doc_start = getattr(value, "lineno", expr.lineno)
                doc_end = getattr(value, "end_lineno", expr.end_lineno or doc_start)
                chunks.append(_new_raw_chunk(
                    kind="python_docstring", content=doc,
                    start_line=doc_start, end_line=doc_end,
                    language="python", symbol=symbol,
                    parent_symbol=parent, metadata={"scope": "class"},
                ))
            self.scope.append(node.name)
            for child in node.body:
                self.visit(child)
            self.scope.pop()

        def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
            parent = ".".join(self.scope) or None
            symbol = ".".join([*self.scope, node.name])
            start = min([node.lineno, *[decorator.lineno for decorator in node.decorator_list]])
            end = getattr(node, "end_lineno", node.lineno)
            chunks.append(_new_raw_chunk(
                kind="python_function", content=_clip_lines(lines, start, end),
                start_line=start, end_line=end, language="python",
                symbol=symbol, parent_symbol=parent,
                metadata={"async": isinstance(node, ast.AsyncFunctionDef)},
            ))
            doc = ast.get_docstring(node, clean=False)
            if doc and node.body and isinstance(node.body[0], ast.Expr):
                expr = node.body[0]
                value = expr.value
                doc_start = getattr(value, "lineno", expr.lineno)
                doc_end = getattr(value, "end_lineno", expr.end_lineno or doc_start)
                chunks.append(_new_raw_chunk(
                    kind="python_docstring", content=doc,
                    start_line=doc_start, end_line=doc_end,
                    language="python", symbol=symbol,
                    parent_symbol=parent, metadata={"scope": "function"},
                ))

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self._visit_function(node)
            # Nested functions are indexed too, with their enclosing symbol.
            self.scope.append(node.name)
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    self.visit(child)
            self.scope.pop()

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self._visit_function(node)
            self.scope.append(node.name)
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    self.visit(child)
            self.scope.pop()

    # Imports and module-level executable statements are useful retrieval context too.
    import_nodes = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
    if import_nodes:
        first_line = min(node.lineno for node in import_nodes)
        last_line = max(getattr(node, "end_lineno", node.lineno) for node in import_nodes)
        chunks.append(_new_raw_chunk(
            kind="python_imports", content=_clip_lines(lines, first_line, last_line),
            start_line=first_line, end_line=last_line, language="python",
        ))

    visitor = _Visitor()
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            visitor.visit(node)
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            start = node.lineno
            end = getattr(node, "end_lineno", start)
            names: list[str] = []
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    names.append(target.id)
            chunks.append(_new_raw_chunk(
                kind="python_assignment", content=_clip_lines(lines, start, end),
                start_line=start, end_line=end, language="python",
                symbol=", ".join(names) if names else None,
            ))
        elif not isinstance(node, (ast.Import, ast.ImportFrom)) and not (
            isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str) and node is tree.body[0]
        ):
            start = node.lineno
            end = getattr(node, "end_lineno", start)
            chunks.append(_new_raw_chunk(
                kind="python_module_block", content=_clip_lines(lines, start, end),
                start_line=start, end_line=end, language="python",
            ))

    # Comments are extracted separately using tokenize, including trailing comments.
    comments: list[tuple[int, str]] = []
    try:
        tokens = tokenize.generate_tokens(io.StringIO(text).readline)
        for token in tokens:
            if token.type == tokenize.COMMENT:
                comments.append((token.start[0], token.string))
    except (tokenize.TokenError, IndentationError):
        pass

    group: list[tuple[int, str]] = []
    for line_no, comment in comments:
        if group and line_no > group[-1][0] + 1:
            chunks.append(_new_raw_chunk(
                kind="python_comment", content="\n".join(value for _, value in group),
                start_line=group[0][0], end_line=group[-1][0], language="python",
            ))
            group = []
        group.append((line_no, comment))
    if group:
        chunks.append(_new_raw_chunk(
            kind="python_comment", content="\n".join(value for _, value in group),
            start_line=group[0][0], end_line=group[-1][0], language="python",
        ))

    if not chunks and text.strip():
        chunks.append(_new_raw_chunk(
            kind="source_file", content=text[:MAX_CHUNK_CHARS], start_line=1,
            end_line=min(len(lines), max(1, text[:MAX_CHUNK_CHARS].count("\n") + 1)),
            language="python",
        ))
    return chunks


def _extract_generic_comments(text: str, language: str | None) -> list[dict[str, Any]]:
    """Best-effort comment extraction for common languages; not a full parser."""
    lines = text.splitlines()
    comments: list[dict[str, Any]] = []
    i = 0
    line_comment_prefixes = {
        "javascript": ("//",), "jsx": ("//",), "typescript": ("//",), "tsx": ("//",),
        "java": ("//",), "c": ("//",), "cpp": ("//",), "go": ("//",), "rust": ("//",),
        "csharp": ("//",), "swift": ("//",), "kotlin": ("//",), "scala": ("//",),
        "shell": ("#",), "ruby": ("#",), "php": ("//", "#"), "sql": ("--",),
        "dockerfile": ("#",), "makefile": ("#",),
    }
    prefixes = line_comment_prefixes.get(language or "", ())
    while i < len(lines):
        stripped = lines[i].lstrip()
        prefix = next((p for p in prefixes if stripped.startswith(p)), None)
        if prefix:
            start = i + 1
            block = [lines[i]]
            i += 1
            while i < len(lines):
                candidate = lines[i].lstrip()
                if any(candidate.startswith(p) for p in prefixes):
                    block.append(lines[i])
                    i += 1
                elif not candidate and i + 1 < len(lines) and any(lines[i + 1].lstrip().startswith(p) for p in prefixes):
                    block.append(lines[i])
                    i += 1
                else:
                    break
            comments.append(_new_raw_chunk(
                kind="source_comment", content="\n".join(block),
                start_line=start, end_line=start + len(block) - 1,
                language=language,
            ))
            continue
        if "/*" in lines[i]:
            start = i + 1
            block = [lines[i]]
            while "*/" not in block[-1] and i + 1 < len(lines):
                i += 1
                block.append(lines[i])
            if any("*/" in part for part in block):
                comment_text = "\n".join(block)
                comments.append(_new_raw_chunk(
                    kind="source_comment", content=comment_text,
                    start_line=start, end_line=start + len(block) - 1,
                    language=language,
                    metadata={"block_comment": True, "documentation_comment": comment_text.lstrip().startswith("/**")},
                ))
        i += 1
    return comments


def _generic_source_chunks(text: str, language: str | None) -> list[dict[str, Any]]:
    lines = text.splitlines()
    chunks: list[dict[str, Any]] = []
    start = 0
    while start < len(lines):
        end = min(len(lines), start + MAX_TEXT_LINES)
        # Prefer a blank-line boundary in the latter half of the window.
        boundary = next((idx for idx in range(end - 1, start + MAX_TEXT_LINES // 2 - 1, -1) if not lines[idx].strip()), None)
        if boundary is not None:
            end = boundary + 1
        content = "\n".join(lines[start:end]).strip("\n")
        if content.strip():
            chunks.append(_new_raw_chunk(
                kind="source_block", content=content,
                start_line=start + 1, end_line=end,
                language=language,
            ))
        start = max(end, start + 1)
    return chunks


def extract_source(text: str, language: str | None, extension: str) -> list[dict[str, Any]]:
    if language == "python":
        return _python_ast_chunks(text)
    chunks = _generic_source_chunks(text, language)
    chunks.extend(_extract_generic_comments(text, language))
    return chunks


def extract_configuration(text: str, language: str | None) -> list[dict[str, Any]]:
    lines = text.splitlines()
    chunks: list[dict[str, Any]] = []
    for start in range(0, len(lines), MAX_TEXT_LINES):
        part = lines[start:start + MAX_TEXT_LINES]
        content = "\n".join(part).strip()
        if content:
            chunks.append(_new_raw_chunk(
                kind="configuration_block", content=content,
                start_line=start + 1, end_line=start + len(part),
                language=language,
            ))
    return chunks


def extract_file_chunks(text: str, extension: str, file_kind: str, language: str | None) -> list[dict[str, Any]]:
    if file_kind == "documentation":
        return extract_documentation(text, extension)
    if file_kind == "configuration":
        return extract_configuration(text, language)
    return extract_source(text, language, extension)
