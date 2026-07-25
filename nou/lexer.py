"""The No U lexer.

Responsibilities:
- UTF-8 decoding with rejection of invalid byte sequences.
- Line-ending normalization (CRLF -> LF) before any tokenization.
- Indentation analysis: leading tabs (lexical block depth) followed by
  leading spaces (execution phase depth). A tab after a leading space is
  an error.
- Trailing-whitespace modifiers (return / suppress / negate).
- Exact, non-normalizing recognition of every legal operator spelling.
- Comments: `no! ... !no`, same-line or whole-line spanning.
- Homoglyph rejection with useful diagnostics.

The lexer never modifies source text and never normalizes case or
operator-internal whitespace.
"""

from __future__ import annotations

import re
import unicodedata

from .diagnostics import Diagnostic, NoUSyntaxError, escape_token_text
from .tokens import LineKind, LogicalLine, Token, TokenKind, Trailing

# Exact-spelling operators (no internal whitespace variability).
_EXACT_OPERATORS: dict[str, TokenKind] = {
    "no": TokenKind.PUSH_TRUE,
    "NO": TokenKind.PUSH_FALSE,
    "No": TokenKind.PUSH_NULL,
    "u": TokenKind.LOAD_CURRENT,
    "nou": TokenKind.CALL0,
    "!": TokenKind.BANG,
    "nooo u": TokenKind.ADD,
    "nooooo uuuuuu": TokenKind.FUNC_DEF,
    "NOOOOOO UUUUUUUU": TokenKind.BIG_CALL,
    "U": TokenKind.U_MARKER,
}

_LOAD_VAR_RE = re.compile(r"no([ \t]+)u")
_STORE_IMMUT_RE = re.compile(r"NO([ \t]+)U")
_STORE_MUT_RE = re.compile(r"NO([ \t]+)u")
_INT_RE = re.compile(r"-?[0-9]+")

# Characters that visually resemble the ASCII characters operators are made of.
_HOMOGLYPHS: dict[str, str] = {
    "н": "n",  # CYRILLIC SMALL LETTER EN (visual lookalike in some fonts)
    "о": "o",  # CYRILLIC SMALL LETTER O
    "у": "u",  # CYRILLIC SMALL LETTER U
    "Н": "N",  # CYRILLIC CAPITAL LETTER EN
    "О": "O",  # CYRILLIC CAPITAL LETTER O
    "У": "U",  # CYRILLIC CAPITAL LETTER U
    "ο": "o",  # GREEK SMALL LETTER OMICRON
    "υ": "u",  # GREEK SMALL LETTER UPSILON
    "Ο": "O",  # GREEK CAPITAL LETTER OMICRON
    "Υ": "U",  # GREEK CAPITAL LETTER UPSILON
    "！": "!",  # FULLWIDTH EXCLAMATION MARK
    "ｎ": "n",  # FULLWIDTH LATIN SMALL LETTER N
    "ｏ": "o",  # FULLWIDTH LATIN SMALL LETTER O
    "ｕ": "u",  # FULLWIDTH LATIN SMALL LETTER U
    "Ｎ": "N",  # FULLWIDTH LATIN CAPITAL LETTER N
    "Ｏ": "O",  # FULLWIDTH LATIN CAPITAL LETTER O
    "Ｕ": "U",  # FULLWIDTH LATIN CAPITAL LETTER U
    " ": " ",  # NO-BREAK SPACE
    " ": " ",  # FIGURE SPACE
    " ": " ",  # NARROW NO-BREAK SPACE
    "　": " ",  # IDEOGRAPHIC SPACE
}


def decode_source(data: bytes, filename: str) -> str:
    """Decode UTF-8 source bytes, rejecting invalid sequences."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        prefix = data[: exc.start]
        line = prefix.count(b"\n") + 1
        col = exc.start - (prefix.rfind(b"\n") + 1) + 1
        raise NoUSyntaxError(
            Diagnostic(
                category="EncodingError",
                message=f"source is not valid UTF-8: {exc.reason} at byte offset {exc.start}",
                filename=filename,
                line=line,
                col=col,
                suggestion="No U source files must be UTF-8 encoded",
            )
        ) from None
    if text.startswith("﻿"):
        text = text[1:]  # tolerate a UTF-8 BOM; it is not part of the program
    return text


def normalize_newlines(text: str, filename: str) -> str:
    """CRLF and LF are equivalent. A lone CR is an error."""
    text = text.replace("\r\n", "\n")
    if "\r" in text:
        idx = text.index("\r")
        prefix = text[:idx]
        line = prefix.count("\n") + 1
        col = idx - (prefix.rfind("\n") + 1) + 1
        raise NoUSyntaxError(
            Diagnostic(
                category="SyntaxError",
                message="stray carriage return (CR) without a following LF",
                filename=filename,
                line=line,
                col=col,
                suggestion="use LF or CRLF line endings",
            )
        )
    return text


class Lexer:
    def __init__(self, source: str, filename: str = "<source>") -> None:
        self.filename = filename
        self.source = normalize_newlines(source, filename)
        # splitlines would also split on unicode line separators; we must not.
        self.lines: list[str] = self.source.split("\n")
        # A final newline yields a trailing empty element; dropping it makes a
        # trailing newline semantically invisible, as required.
        if self.lines and self.lines[-1] == "":
            self.lines.pop()

    # -- diagnostics helpers -------------------------------------------------

    def _error(
        self,
        message: str,
        line_no: int,
        col: int,
        end_col: int | None = None,
        category: str = "SyntaxError",
        suggestion: str | None = None,
    ) -> NoUSyntaxError:
        raw = self.lines[line_no - 1] if 0 < line_no <= len(self.lines) else None
        return NoUSyntaxError(
            Diagnostic(
                category=category,
                message=message,
                filename=self.filename,
                line=line_no,
                col=col,
                end_col=end_col,
                source_line=raw,
                suggestion=suggestion,
            )
        )

    def _homoglyph_check(self, text: str, line_no: int, base_col: int) -> None:
        """If text contains a known homoglyph of an operator character, complain."""
        for i, ch in enumerate(text):
            if ch in _HOMOGLYPHS:
                name = unicodedata.name(ch, f"U+{ord(ch):04X}")
                looks_like = _HOMOGLYPHS[ch]
                shown = "space" if looks_like == " " else f"'{looks_like}'"
                raise self._error(
                    f"character U+{ord(ch):04X} ({name}) looks like ASCII {shown} "
                    "but is not; operators must use exact ASCII characters",
                    line_no,
                    base_col + i,
                    base_col + i + 1,
                    suggestion=f"replace it with ASCII {shown}",
                )

    # -- indentation ---------------------------------------------------------

    def _split_indent(self, raw: str, line_no: int) -> tuple[int, int, int]:
        """Return (tab_depth, space_depth, content_start_index)."""
        i = 0
        tabs = 0
        while i < len(raw) and raw[i] == "\t":
            tabs += 1
            i += 1
        spaces = 0
        while i < len(raw) and raw[i] == " ":
            spaces += 1
            i += 1
        if i < len(raw) and raw[i] == "\t":
            raise self._error(
                "tab appears after indentation space",
                line_no,
                i + 1,
                suggestion="tabs may not follow leading spaces",
            )
        if i < len(raw) and raw[i] in _HOMOGLYPHS and _HOMOGLYPHS[raw[i]] == " ":
            self._homoglyph_check(raw[i], line_no, i + 1)
        return tabs, spaces, i

    # -- trailing whitespace -------------------------------------------------

    def _split_trailing(
        self, code: str, line_no: int, base_col: int
    ) -> tuple[str, Trailing]:
        """Split off the trailing-whitespace modifier of the code portion.

        base_col is the 1-based column of code[0] in the physical line.
        """
        stripped = code.rstrip(" \t")
        trail = code[len(stripped) :]
        if not trail:
            return stripped, Trailing.NONE
        tcol = base_col + len(stripped)
        spaces = trail.count(" ")
        tabs = trail.count("\t")
        if spaces and tabs:
            raise self._error(
                "trailing whitespace mixes spaces and tabs",
                line_no,
                tcol,
                tcol + len(trail),
                suggestion="use at most two trailing spaces or one trailing tab, not both",
            )
        if tabs > 1:
            raise self._error(
                f"{tabs} trailing tabs; at most one is allowed",
                line_no,
                tcol,
                tcol + len(trail),
                suggestion="one trailing tab negates the statement's value",
            )
        if spaces > 2:
            raise self._error(
                f"{spaces} trailing spaces; at most two are allowed",
                line_no,
                tcol,
                tcol + len(trail),
                suggestion="one trailing space returns the value, two suppress it",
            )
        if tabs == 1:
            return stripped, Trailing.NEGATE
        if spaces == 1:
            return stripped, Trailing.RETURN
        return stripped, Trailing.SUPPRESS

    # -- literals ------------------------------------------------------------

    def _parse_string_payload(
        self, text: str, line_no: int, base_col: int
    ) -> str:
        """Decode the escaped contents of a string literal (without quotes)."""
        out: list[str] = []
        i = 0
        while i < len(text):
            ch = text[i]
            if ch != "\\":
                out.append(ch)
                i += 1
                continue
            if i + 1 >= len(text):
                raise self._error(
                    "dangling backslash in string literal",
                    line_no,
                    base_col + i,
                )
            esc = text[i + 1]
            if esc == "n":
                out.append("\n")
                i += 2
            elif esc == "r":
                out.append("\r")
                i += 2
            elif esc == "t":
                out.append("\t")
                i += 2
            elif esc == "\\":
                out.append("\\")
                i += 2
            elif esc == '"':
                out.append('"')
                i += 2
            elif esc == "u":
                hex_part = text[i + 2 : i + 6]
                if len(hex_part) != 4 or not all(
                    c in "0123456789abcdefABCDEF" for c in hex_part
                ):
                    raise self._error(
                        "\\u escape requires exactly four hexadecimal digits",
                        line_no,
                        base_col + i,
                        base_col + i + 2 + len(hex_part),
                    )
                out.append(chr(int(hex_part, 16)))
                i += 6
            else:
                raise self._error(
                    f"unknown string escape '\\{esc}'",
                    line_no,
                    base_col + i,
                    base_col + i + 2,
                    suggestion="supported escapes: \\n \\r \\t \\\\ \\\" \\uXXXX",
                )
        return "".join(out)

    def _parse_literal(self, seg: str, line_no: int, col: int) -> Token:
        """Parse a `!...!` literal. seg starts with '!' and has length > 1."""
        assert seg.startswith("!")
        if not seg.endswith("!") or len(seg) < 3:
            raise self._error(
                f"malformed literal {seg!r}: literals are delimited by '!' on both sides",
                line_no,
                col,
                col + len(seg),
                suggestion="write !null!, !true!, !false!, !123!, or !\"text\"!",
            )
        payload = seg[1:-1]
        value: object
        if payload.startswith('"'):
            if not payload.endswith('"') or len(payload) < 2:
                raise self._error(
                    "malformed string literal: missing closing quote before '!'",
                    line_no,
                    col,
                    col + len(seg),
                )
            value = self._parse_string_payload(payload[1:-1], line_no, col + 2)
        elif payload == "null":
            value = None
        elif payload == "true":
            value = True
        elif payload == "false":
            value = False
        elif _INT_RE.fullmatch(payload):
            value = int(payload, 10)
        else:
            self._homoglyph_check(payload, line_no, col + 1)
            raise self._error(
                f"invalid literal payload {payload!r}",
                line_no,
                col + 1,
                col + 1 + len(payload),
                suggestion='an unquoted payload must be null, true, false, or a base-10 integer',
            )
        return Token(
            kind=TokenKind.LITERAL,
            text=seg,
            line=line_no,
            col=col,
            end_col=col + len(seg),
            value=value,
        )

    # -- segments ------------------------------------------------------------

    def _match_segment(self, seg: str, line_no: int, col: int) -> Token:
        """Match one comma-delimited segment (already trimmed) to a token."""
        if seg.startswith("!") and len(seg) > 1:
            return self._parse_literal(seg, line_no, col)
        kind = _EXACT_OPERATORS.get(seg)
        if kind is not None:
            return Token(kind=kind, text=seg, line=line_no, col=col, end_col=col + len(seg))
        m = _LOAD_VAR_RE.fullmatch(seg)
        if m:
            return Token(
                kind=TokenKind.LOAD_VAR,
                text=seg,
                line=line_no,
                col=col,
                end_col=col + len(seg),
                name=m.group(1),
            )
        m = _STORE_IMMUT_RE.fullmatch(seg)
        if m:
            return Token(
                kind=TokenKind.STORE_IMMUT,
                text=seg,
                line=line_no,
                col=col,
                end_col=col + len(seg),
                name=m.group(1),
            )
        m = _STORE_MUT_RE.fullmatch(seg)
        if m:
            return Token(
                kind=TokenKind.STORE_MUT,
                text=seg,
                line=line_no,
                col=col,
                end_col=col + len(seg),
                name=m.group(1),
            )
        self._homoglyph_check(seg, line_no, col)
        escaped = escape_token_text(seg)
        suggestion = None
        low = seg.lower().replace("\t", " ")
        if re.fullmatch(r"no +u", low) and seg not in ("nooo u",):
            suggestion = (
                "case matters: no<WS>u loads, NO<WS>U stores immutably, NO<WS>u stores mutably"
            )
        raise self._error(
            f"unrecognized operator (recognized token: {escaped})",
            line_no,
            col,
            col + len(seg),
            suggestion=suggestion,
        )

    def _scan_code(
        self, code: str, line_no: int, base_col: int
    ) -> list[Token]:
        """Split the code portion of a line into tokens.

        Commas are mandatory separators. Same-line comments (`no! ... !no`)
        act as separator whitespace. String literals may contain commas and
        comment delimiters as plain text.
        """
        tokens: list[Token] = []
        segments: list[tuple[str, int]] = []  # (text, start index into code)
        seg_start = 0
        i = 0
        n = len(code)
        # (char, source index) pairs of the current segment; elided comments
        # contribute a positionless separator space so spans stay exact.
        chars: list[tuple[str, int | None]] = []

        def close_segment(end: int) -> None:
            lo = 0
            hi = len(chars)
            while lo < hi and chars[lo][0] in " \t":
                lo += 1
            while hi > lo and chars[hi - 1][0] in " \t":
                hi -= 1
            if lo == hi:
                raise self._error(
                    "empty expression between commas",
                    line_no,
                    base_col + seg_start,
                    base_col + end,
                    suggestion="remove the extra comma",
                )
            text = "".join(c for c, _ in chars[lo:hi])
            first_pos = next(p for _, p in chars[lo:hi] if p is not None)
            segments.append((text, first_pos))

        while i < n:
            ch = code[i]
            if code.startswith("no!", i):
                # A comment opener. Same-line comments must close on this line.
                close = code.find("!no", i + 3)
                if close == -1:
                    raise self._error(
                        "comment spanning multiple lines may not follow code on the same line",
                        line_no,
                        base_col + i,
                        base_col + i + 3,
                        suggestion="put multi-line comments on their own lines",
                    )
                chars.append((" ", None))  # a comment separates like whitespace
                i = close + 3
                continue
            if ch == ",":
                close_segment(i)
                chars.clear()
                seg_start = i + 1
                i += 1
                continue
            if ch == "!" and i + 1 < n and code[i + 1] == '"':
                # String literal: consume through closing `"` and `!`.
                j = i + 2
                while j < n:
                    if code[j] == "\\":
                        j += 2
                        continue
                    if code[j] == '"':
                        break
                    j += 1
                if j >= n:
                    raise self._error(
                        "unterminated string literal",
                        line_no,
                        base_col + i,
                        base_col + n,
                        suggestion='string literals look like !"text"!',
                    )
                if j + 1 >= n or code[j + 1] != "!":
                    raise self._error(
                        "string literal is missing its closing '!'",
                        line_no,
                        base_col + i,
                        base_col + j + 1,
                    )
                for k in range(i, j + 2):
                    chars.append((code[k], k))
                i = j + 2
                continue
            chars.append((ch, i))
            i += 1
        close_segment(n)

        for text, start in segments:
            tokens.append(self._match_segment(text, line_no, base_col + start))
        return tokens

    # -- main entry ----------------------------------------------------------

    def lex(self) -> list[LogicalLine]:
        result: list[LogicalLine] = []
        line_no = 0
        total = len(self.lines)
        idx = 0
        while idx < total:
            raw = self.lines[idx]
            line_no = idx + 1
            idx += 1

            if raw == "":
                result.append(
                    LogicalLine(line_no=line_no, kind=LineKind.BLANK, tab_depth=0, space_depth=0, raw=raw)
                )
                continue

            tabs, spaces, start = self._split_indent(raw, line_no)
            if start == len(raw):
                # Whitespace-only line: significant (validated, recorded).
                result.append(
                    LogicalLine(
                        line_no=line_no,
                        kind=LineKind.WS_ONLY,
                        tab_depth=tabs,
                        space_depth=spaces,
                        raw=raw,
                    )
                )
                continue

            rest = raw[start:]
            base_col = start + 1  # 1-based column of first content character

            # Whole-line comment (possibly spanning multiple lines)?
            if rest.startswith("no!"):
                close = rest.find("!no", 3)
                if close != -1 and rest[close + 3 :].strip(" \t") == "":
                    result.append(
                        LogicalLine(
                            line_no=line_no,
                            kind=LineKind.COMMENT_ONLY,
                            tab_depth=tabs,
                            space_depth=spaces,
                            raw=raw,
                        )
                    )
                    continue
                if close == -1:
                    # Multi-line comment: consume lines until one contains !no.
                    open_line = line_no
                    while True:
                        if idx >= total:
                            raise self._error(
                                "unterminated comment: no matching '!no' before end of file",
                                open_line,
                                base_col,
                                base_col + 3,
                                suggestion="close the comment with !no",
                            )
                        body = self.lines[idx]
                        idx += 1
                        close = body.find("!no")
                        if close != -1:
                            after = body[close + 3 :]
                            if after.strip(" \t") != "":
                                raise self._error(
                                    "code is not allowed after a multi-line comment terminator",
                                    idx,
                                    close + 4,
                                    suggestion="put the code on its own line",
                                )
                            result.append(
                                LogicalLine(
                                    line_no=open_line,
                                    kind=LineKind.COMMENT_ONLY,
                                    tab_depth=tabs,
                                    space_depth=spaces,
                                    raw=raw,
                                )
                            )
                            break
                    continue
                # Comment closes on this line but code follows it: fall
                # through to statement scanning (the scanner elides it).

            code, trailing = self._split_trailing(rest, line_no, base_col)
            if code == "":
                # The line was only a comment plus trailing whitespace.
                result.append(
                    LogicalLine(
                        line_no=line_no,
                        kind=LineKind.COMMENT_ONLY,
                        tab_depth=tabs,
                        space_depth=spaces,
                        raw=raw,
                    )
                )
                continue

            # Header special-cases: no commas, so these exact lines cannot
            # be anything else.
            if code == "NO U !":
                result.append(
                    LogicalLine(
                        line_no=line_no,
                        kind=LineKind.COND_HEADER,
                        tab_depth=tabs,
                        space_depth=spaces,
                        trailing=trailing,
                        raw=raw,
                    )
                )
                continue
            if code == "NO u !":
                result.append(
                    LogicalLine(
                        line_no=line_no,
                        kind=LineKind.LOOP_HEADER,
                        tab_depth=tabs,
                        space_depth=spaces,
                        trailing=trailing,
                        raw=raw,
                    )
                )
                continue

            tokens = self._scan_code(code, line_no, base_col)
            if not tokens:
                result.append(
                    LogicalLine(
                        line_no=line_no,
                        kind=LineKind.COMMENT_ONLY,
                        tab_depth=tabs,
                        space_depth=spaces,
                        raw=raw,
                    )
                )
                continue
            result.append(
                LogicalLine(
                    line_no=line_no,
                    kind=LineKind.STATEMENT,
                    tab_depth=tabs,
                    space_depth=spaces,
                    tokens=tokens,
                    trailing=trailing,
                    raw=raw,
                )
            )
        return result


def lex_source(source: str, filename: str = "<source>") -> list[LogicalLine]:
    return Lexer(source, filename).lex()


def lex_bytes(data: bytes, filename: str = "<source>") -> list[LogicalLine]:
    return Lexer(decode_source(data, filename), filename).lex()
