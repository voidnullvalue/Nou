"""Abstract syntax tree for No U."""

from __future__ import annotations

from dataclasses import dataclass, field

from .diagnostics import escape_name, escape_token_text
from .tokens import Token, Trailing


# -- expressions --------------------------------------------------------------


@dataclass
class Expr:
    token: Token

    def describe(self) -> str:
        return escape_token_text(self.token.text)


@dataclass
class OpExpr(Expr):
    """A single operator expression; behavior is determined by token.kind."""


@dataclass
class LiteralExpr(Expr):
    value: object = None


@dataclass
class EqualityExpr(Expr):
    """Two consecutive `!` expressions fused into structural equality."""

    second: Token = None  # type: ignore[assignment]

    def describe(self) -> str:
        return "!,! (equality)"


# -- statements ---------------------------------------------------------------


@dataclass
class Statement:
    line: int  # 1-based physical line number
    phase: int  # space depth = execution phase
    trailing: Trailing
    raw: str  # raw source line (for tracing/diagnostics)


@dataclass
class ExprStatement(Statement):
    exprs: list[Expr] = field(default_factory=list)
    nested: "Block | None" = None  # anonymous tab-indented block, if any


@dataclass
class FuncDefStatement(Statement):
    params: int = 5
    local_slots: int = 6
    body: "Block | None" = None


@dataclass
class CondStatement(Statement):
    body: "Block | None" = None


@dataclass
class LoopStatement(Statement):
    body: "Block | None" = None


@dataclass
class DelayedAssignStatement(Statement):
    """`No` on one line, `  U` on the next: schedule a mutable assignment of
    the current value to the canonical two-space binding at end of phase."""

    u_line: int = 0


@dataclass
class Block:
    statements: list[Statement] = field(default_factory=list)

    def phases(self) -> list[int]:
        return sorted({s.phase for s in self.statements})


@dataclass
class Module:
    filename: str
    block: Block


# -- AST pretty printer --------------------------------------------------------


def dump(module: Module) -> str:
    lines: list[str] = [f"Module {module.filename}"]
    _dump_block(module.block, lines, 1)
    return "\n".join(lines)


def _dump_block(block: Block, lines: list[str], depth: int) -> None:
    pad = "  " * depth
    lines.append(f"{pad}Block phases={block.phases()}")
    for stmt in block.statements:
        _dump_statement(stmt, lines, depth + 1)


def _dump_statement(stmt: Statement, lines: list[str], depth: int) -> None:
    pad = "  " * depth
    suffix = f" [line {stmt.line}, phase {stmt.phase}"
    if stmt.trailing is not Trailing.NONE:
        suffix += f", trailing={stmt.trailing.value}"
    suffix += "]"
    if isinstance(stmt, ExprStatement):
        parts = ", ".join(_describe_expr(e) for e in stmt.exprs)
        lines.append(f"{pad}ExprStatement {parts}{suffix}")
        if stmt.nested is not None:
            _dump_block(stmt.nested, lines, depth + 1)
    elif isinstance(stmt, FuncDefStatement):
        lines.append(
            f"{pad}FuncDef params={stmt.params} local_slots={stmt.local_slots}{suffix}"
        )
        if stmt.body is not None:
            _dump_block(stmt.body, lines, depth + 1)
    elif isinstance(stmt, CondStatement):
        lines.append(f"{pad}Conditional{suffix}")
        if stmt.body is not None:
            _dump_block(stmt.body, lines, depth + 1)
    elif isinstance(stmt, LoopStatement):
        lines.append(f"{pad}Loop{suffix}")
        if stmt.body is not None:
            _dump_block(stmt.body, lines, depth + 1)
    elif isinstance(stmt, DelayedAssignStatement):
        lines.append(
            f"{pad}DelayedAssign target={escape_name('  ')} (u-line {stmt.u_line}){suffix}"
        )
    else:  # pragma: no cover - defensive
        lines.append(f"{pad}{type(stmt).__name__}{suffix}")


def _describe_expr(expr: Expr) -> str:
    if isinstance(expr, EqualityExpr):
        return expr.describe()
    if isinstance(expr, LiteralExpr):
        return f"literal({expr.token.text})"
    token = expr.token
    name = f" name={escape_name(token.name)}" if token.name is not None else ""
    return f"{token.kind.value}({escape_token_text(token.text)}{name})"
