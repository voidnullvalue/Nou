"""Diagnostic construction and rendering for No U.

All errors raised by the lexer, parser, and runtime carry a Diagnostic with
an exact physical line number, a 1-based character column range, the source
excerpt, and a visible-whitespace rendering (tabs as `→`, spaces as `·`).
"""

from __future__ import annotations

from dataclasses import dataclass


def render_whitespace(text: str) -> str:
    """Render tabs and spaces visibly. One output character per input character."""
    return text.replace("\t", "→").replace(" ", "·")


def escape_name(name: str) -> str:
    """Escape a whitespace-based binding name: '  ' -> '<SP><SP>'."""
    out: list[str] = []
    for ch in name:
        if ch == " ":
            out.append("<SP>")
        elif ch == "\t":
            out.append("<TAB>")
        else:
            out.append(ch)
    return "".join(out)


def escape_token_text(text: str) -> str:
    """Escape a token spelling for display: 'no  u' -> 'no<SP><SP>u'."""
    return escape_name(text)


@dataclass
class Diagnostic:
    category: str  # e.g. "SyntaxError", "IndentationError", "RuntimeError"
    message: str
    filename: str
    line: int  # 1-based physical line number; 0 if unknown
    col: int  # 1-based character column; 0 if unknown
    end_col: int | None = None  # exclusive; None means single-column caret
    source_line: str | None = None  # raw source line without newline
    suggestion: str | None = None

    def render(self) -> str:
        parts: list[str] = [f"{self.category}: {self.message}"]
        if self.line > 0:
            parts.append(f"  --> {self.filename}:{self.line}:{self.col}")
        else:
            parts.append(f"  --> {self.filename}")
        if self.source_line is not None and self.line > 0:
            gutter = f" {self.line} "
            pad = " " * len(gutter)
            rendered = render_whitespace(self.source_line)
            parts.append(f"{pad}|")
            parts.append(f"{gutter}| {rendered}")
            if self.col > 0:
                width = 1
                if self.end_col is not None and self.end_col > self.col:
                    width = self.end_col - self.col
                caret = " " * (self.col - 1) + "^" + "~" * (width - 1)
                note = f" {self.suggestion}" if self.suggestion else ""
                parts.append(f"{pad}| {caret}{note}")
            elif self.suggestion:
                parts.append(f"{pad}| {self.suggestion}")
        elif self.suggestion:
            parts.append(f"  note: {self.suggestion}")
        return "\n".join(parts)


class NoUError(Exception):
    """Base class for all diagnosable No U errors."""

    def __init__(self, diagnostic: Diagnostic) -> None:
        super().__init__(diagnostic.message)
        self.diagnostic = diagnostic

    def render(self) -> str:
        return self.diagnostic.render()


class NoUSyntaxError(NoUError):
    pass


class NoURuntimeError(NoUError):
    pass
