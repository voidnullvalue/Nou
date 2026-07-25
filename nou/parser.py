"""The No U parser.

Turns the lexer's logical lines into a Module of nested Blocks:

- Leading tab depth defines lexical block nesting. A +1 increase opens a
  block attached to the immediately preceding statement (function body,
  conditional body, loop body, or anonymous nested block). A jump of more
  than +1 is an indentation error.
- Leading space depth is recorded on each statement as its execution phase.
- The exact lines `NO U !` / `NO u !` are conditional / loop headers and
  require a body block.
- A line whose sole content is `No`, immediately followed (next physical
  line, nothing in between) by a `U` line at the same tab depth and space
  depth + 2, is a delayed assignment.
- Two consecutive bare `!` expressions in one statement fuse into equality.
"""

from __future__ import annotations

from .ast import (
    Block,
    CondStatement,
    DelayedAssignStatement,
    EqualityExpr,
    Expr,
    ExprStatement,
    FuncDefStatement,
    LiteralExpr,
    LoopStatement,
    Module,
    OpExpr,
    Statement,
)
from .diagnostics import Diagnostic, NoUSyntaxError
from .lexer import Lexer, decode_source
from .tokens import LineKind, LogicalLine, Token, TokenKind, Trailing

_SKIPPED = (LineKind.BLANK, LineKind.WS_ONLY, LineKind.COMMENT_ONLY)


class Parser:
    def __init__(self, lines: list[LogicalLine], filename: str = "<source>") -> None:
        self.lines = lines
        self.filename = filename
        self.pos = 0

    # -- helpers ---------------------------------------------------------------

    def _error(
        self,
        message: str,
        line: LogicalLine,
        col: int = 1,
        end_col: int | None = None,
        category: str = "SyntaxError",
        suggestion: str | None = None,
    ) -> NoUSyntaxError:
        return NoUSyntaxError(
            Diagnostic(
                category=category,
                message=message,
                filename=self.filename,
                line=line.line_no,
                col=col,
                end_col=end_col,
                source_line=line.raw,
                suggestion=suggestion,
            )
        )

    def _peek_code_line(self) -> LogicalLine | None:
        """Next line that is not blank/ws-only/comment-only, without consuming."""
        i = self.pos
        while i < len(self.lines):
            if self.lines[i].kind not in _SKIPPED:
                return self.lines[i]
            i += 1
        return None

    # -- entry -------------------------------------------------------------------

    def parse_module(self) -> Module:
        block = self._parse_block(0)
        line = self._peek_code_line()
        if line is not None:  # pragma: no cover - defensive; depth 0 consumes all
            raise self._error("unexpected content after top-level block", line)
        return Module(filename=self.filename, block=block)

    # -- blocks --------------------------------------------------------------------

    def _parse_block(self, depth: int) -> Block:
        statements: list[Statement] = []
        while True:
            line = self._peek_code_line()
            if line is None or line.tab_depth < depth:
                break
            if line.tab_depth > depth:
                if line.tab_depth != depth + 1:
                    raise self._error(
                        f"indentation jumps from tab depth {depth} to {line.tab_depth}; "
                        "blocks may only nest one tab at a time",
                        line,
                        col=1,
                        end_col=line.tab_depth + 1,
                        category="IndentationError",
                    )
                if not statements:
                    raise self._error(
                        "unexpected indent: a nested block must follow a statement",
                        line,
                        col=1,
                        end_col=line.tab_depth + 1,
                        category="IndentationError",
                    )
                body = self._parse_block(depth + 1)
                self._attach_body(statements[-1], body, line)
                continue
            # Skip over non-code lines before this one.
            while self.lines[self.pos] is not line:
                self.pos += 1
            self.pos += 1
            statements.append(self._parse_line(line))
        for stmt in statements:
            self._check_body_present(stmt)
        return Block(statements=statements)

    def _attach_body(self, stmt: Statement, body: Block, at: LogicalLine) -> None:
        if isinstance(stmt, FuncDefStatement):
            stmt.body = body
        elif isinstance(stmt, CondStatement):
            stmt.body = body
        elif isinstance(stmt, LoopStatement):
            stmt.body = body
        elif isinstance(stmt, ExprStatement):
            stmt.nested = body
        else:
            raise self._error(
                "a nested block may not follow a delayed assignment",
                at,
                category="IndentationError",
            )

    def _check_body_present(self, stmt: Statement) -> None:
        missing: str | None = None
        if isinstance(stmt, FuncDefStatement) and stmt.body is None:
            missing = "function definition"
        elif isinstance(stmt, CondStatement) and stmt.body is None:
            missing = "conditional"
        elif isinstance(stmt, LoopStatement) and stmt.body is None:
            missing = "loop"
        if missing is not None:
            fake = LogicalLine(
                line_no=stmt.line,
                kind=LineKind.STATEMENT,
                tab_depth=0,
                space_depth=stmt.phase,
                raw=stmt.raw,
            )
            raise self._error(
                f"{missing} requires a tab-indented body block on the following lines",
                fake,
                suggestion="indent the body one tab deeper than this line",
            )

    # -- statements -------------------------------------------------------------------

    def _parse_line(self, line: LogicalLine) -> Statement:
        if line.kind is LineKind.COND_HEADER:
            return CondStatement(
                line=line.line_no,
                phase=line.space_depth,
                trailing=line.trailing,
                raw=line.raw,
            )
        if line.kind is LineKind.LOOP_HEADER:
            return LoopStatement(
                line=line.line_no,
                phase=line.space_depth,
                trailing=line.trailing,
                raw=line.raw,
            )

        tokens = line.tokens

        if len(tokens) == 1 and tokens[0].kind is TokenKind.U_MARKER:
            raise self._error(
                "stray 'U' line: 'U' is only valid on the line immediately after a lone 'No'",
                line,
                col=tokens[0].col,
                end_col=tokens[0].end_col,
                suggestion="the delayed-assignment form is 'No' then a line of exactly two spaces and 'U'",
            )

        # Delayed assignment: a lone `No` immediately followed by a U line.
        if len(tokens) == 1 and tokens[0].kind is TokenKind.PUSH_NULL:
            u_line = self._try_consume_u_line(line)
            if u_line is not None:
                return DelayedAssignStatement(
                    line=line.line_no,
                    phase=line.space_depth,
                    trailing=Trailing.NONE,
                    raw=line.raw,
                    u_line=u_line.line_no,
                )

        # Function definition must stand alone on its line.
        if any(t.kind is TokenKind.FUNC_DEF for t in tokens):
            if len(tokens) != 1:
                bad = next(t for t in tokens if t.kind is TokenKind.FUNC_DEF)
                raise self._error(
                    "'nooooo uuuuuu' must be the only expression on its line",
                    line,
                    col=bad.col,
                    end_col=bad.end_col,
                )
            tok = tokens[0]
            return FuncDefStatement(
                line=line.line_no,
                phase=line.space_depth,
                trailing=line.trailing,
                raw=line.raw,
                params=5,
                local_slots=6,
            )

        exprs = self._build_exprs(tokens, line)
        return ExprStatement(
            line=line.line_no,
            phase=line.space_depth,
            trailing=line.trailing,
            raw=line.raw,
            exprs=exprs,
        )

    def _try_consume_u_line(self, no_line: LogicalLine) -> LogicalLine | None:
        """If the very next physical line is a matching `U` line, consume it."""
        if self.pos >= len(self.lines):
            return None
        nxt = self.lines[self.pos]
        if nxt.line_no != no_line.line_no + 1:
            return None
        if nxt.kind is not LineKind.STATEMENT:
            return None
        if len(nxt.tokens) != 1 or nxt.tokens[0].kind is not TokenKind.U_MARKER:
            return None
        if nxt.tab_depth != no_line.tab_depth or nxt.space_depth != no_line.space_depth + 2:
            raise self._error(
                "misindented 'U' line in delayed assignment: expected the same tab "
                f"depth ({no_line.tab_depth}) and exactly two more leading spaces "
                f"({no_line.space_depth + 2}), found tab depth {nxt.tab_depth} and "
                f"space depth {nxt.space_depth}",
                nxt,
                col=1,
                end_col=nxt.tab_depth + nxt.space_depth + 1,
                category="IndentationError",
            )
        if no_line.trailing is not Trailing.NONE:
            raise self._error(
                "trailing whitespace is not allowed on the 'No' line of a delayed assignment",
                no_line,
            )
        if nxt.trailing is not Trailing.NONE:
            raise self._error(
                "trailing whitespace is not allowed on the 'U' line of a delayed assignment",
                nxt,
            )
        self.pos += 1
        return nxt

    def _build_exprs(self, tokens: list[Token], line: LogicalLine) -> list[Expr]:
        exprs: list[Expr] = []
        i = 0
        while i < len(tokens):
            tok = tokens[i]
            if tok.kind is TokenKind.U_MARKER:
                raise self._error(
                    "'U' is not an operator; it may only form the second line of a delayed assignment",
                    line,
                    col=tok.col,
                    end_col=tok.end_col,
                )
            if (
                tok.kind is TokenKind.BANG
                and i + 1 < len(tokens)
                and tokens[i + 1].kind is TokenKind.BANG
            ):
                exprs.append(EqualityExpr(token=tok, second=tokens[i + 1]))
                i += 2
                continue
            if tok.kind is TokenKind.LITERAL:
                exprs.append(LiteralExpr(token=tok, value=tok.value))
            else:
                exprs.append(OpExpr(token=tok))
            i += 1
        return exprs


# -- convenience entry points ---------------------------------------------------


def parse_source(source: str, filename: str = "<source>") -> Module:
    lines = Lexer(source, filename).lex()
    return Parser(lines, filename).parse_module()


def parse_bytes(data: bytes, filename: str = "<source>") -> Module:
    return parse_source(decode_source(data, filename), filename)
