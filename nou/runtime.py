"""The No U interpreter runtime.

Execution model:

- Each lexical block executes in a Frame with its own operand stack,
  current value, bindings, and deferred-assignment queue.
- Statements execute grouped by ascending execution phase (leading-space
  depth); within a phase, in source order.
- Delayed assignments scheduled during a phase are applied, in source
  order, when that phase ends.
- A statement with one trailing space returns its value from the block
  immediately (remaining statements, phases, and unapplied deferred
  assignments are abandoned).
- A block's result is its returned value, or Null if it never returns.
"""

from __future__ import annotations

import sys
import typing
from dataclasses import dataclass, field

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
    Statement,
)
from .diagnostics import Diagnostic, NoURuntimeError, escape_name
from .tokens import TokenKind, Trailing
from .values import (
    Builtin,
    Function,
    Value,
    to_repr,
    truthy,
    values_equal,
)

DELAYED_TARGET = "  "  # the canonical two-space binding
DEFAULT_STEP_LIMIT = 1_000_000


@dataclass
class Binding:
    value: Value
    mutable: bool


class Frame:
    """One lexical block's execution state."""

    __slots__ = ("parent", "stack", "current", "bindings", "deferred")

    def __init__(self, parent: "Frame | None") -> None:
        self.parent = parent
        self.stack: list[Value] = []
        self.current: Value = None
        self.bindings: dict[str, Binding] = {}
        self.deferred: list[Value] = []

    def lookup(self, name: str) -> Binding | None:
        frame: Frame | None = self
        while frame is not None:
            binding = frame.bindings.get(name)
            if binding is not None:
                return binding
            frame = frame.parent
        return None


class BlockReturn(Exception):
    """Internal control flow: a trailing-space statement returned a value."""

    def __init__(self, value: Value) -> None:
        self.value = value


class Interpreter:
    def __init__(
        self,
        step_limit: int = DEFAULT_STEP_LIMIT,
        trace: bool = False,
        stdin: typing.TextIO | None = None,
        stdout: typing.TextIO | None = None,
        filename: str = "<source>",
    ) -> None:
        self.step_limit = step_limit
        self.trace = trace
        self.stdin = stdin if stdin is not None else sys.stdin
        self.stdout = stdout if stdout is not None else sys.stdout
        self.filename = filename
        self.steps = 0
        self._depth = 0  # lexical/frame depth, for tracing
        self.root = Frame(parent=None)
        from .stdlib import install_builtins

        install_builtins(self.root)

    # -- errors ------------------------------------------------------------------

    def _error(
        self,
        message: str,
        line: int = 0,
        raw: str | None = None,
        suggestion: str | None = None,
    ) -> NoURuntimeError:
        return NoURuntimeError(
            Diagnostic(
                category="RuntimeError",
                message=message,
                filename=self.filename,
                line=line,
                col=1 if line else 0,
                source_line=raw,
                suggestion=suggestion,
            )
        )

    def _expr_error(self, message: str, expr: Expr, stmt: Statement, suggestion: str | None = None) -> NoURuntimeError:
        tok = expr.token
        return NoURuntimeError(
            Diagnostic(
                category="RuntimeError",
                message=message,
                filename=self.filename,
                line=tok.line,
                col=tok.col,
                end_col=tok.end_col,
                source_line=stmt.raw,
                suggestion=suggestion,
            )
        )

    def _tick(self, stmt: Statement) -> None:
        self.steps += 1
        if self.steps > self.step_limit:
            raise self._error(
                f"step limit of {self.step_limit} operations exceeded",
                line=stmt.line,
                raw=stmt.raw,
                suggestion="raise the limit with --step-limit if the program is expected to run this long",
            )

    # -- entry -----------------------------------------------------------------

    def run_module(self, module: Module) -> Frame:
        self.filename = module.filename
        frame = Frame(parent=self.root)
        try:
            self.exec_block(module.block, frame)
        except RecursionError:
            raise self._error(
                "call depth exceeded: functions are nested too deeply"
            ) from None
        return frame

    # -- blocks -------------------------------------------------------------------

    def exec_block(self, block: Block, frame: Frame) -> Value:
        self._depth += 1
        try:
            for phase in block.phases():
                frame.deferred.clear()
                for stmt in block.statements:
                    if stmt.phase != phase:
                        continue
                    self._exec_statement(stmt, frame)
                for value in frame.deferred:
                    self._store_mut(DELAYED_TARGET, value, frame, stmt_line=0)
                frame.deferred.clear()
            return None
        except BlockReturn as ret:
            return ret.value
        finally:
            self._depth -= 1

    # -- statements ------------------------------------------------------------------

    def _exec_statement(self, stmt: Statement, frame: Frame) -> None:
        self._tick(stmt)
        if self.trace:
            self._trace_before(stmt, frame)

        pre_current = frame.current

        if isinstance(stmt, ExprStatement):
            value: Value = None
            pushed = False
            for expr in stmt.exprs:
                value, pushed = self._eval_expr(expr, stmt, frame)
            self._apply_trailing(stmt, frame, value, pushed, pre_current)
            if stmt.nested is not None:
                result = self.exec_block(stmt.nested, Frame(parent=frame))
                frame.stack.append(result)
                frame.current = result
        elif isinstance(stmt, FuncDefStatement):
            assert stmt.body is not None
            fn = Function(
                params=stmt.params,
                local_slots=stmt.local_slots,
                body=stmt.body,
                closure=frame,
                def_line=stmt.line,
            )
            frame.stack.append(fn)
            frame.current = fn
            self._apply_trailing(stmt, frame, fn, True, pre_current)
        elif isinstance(stmt, CondStatement):
            assert stmt.body is not None
            cond = self._pop(frame, 1, "the conditional 'NO U !'", stmt)[0]
            if truthy(cond):
                result = self.exec_block(stmt.body, Frame(parent=frame))
                frame.stack.append(result)
                frame.current = result
                self._apply_trailing(stmt, frame, result, True, pre_current)
            else:
                frame.current = None
                self._apply_trailing(stmt, frame, None, False, pre_current)
        elif isinstance(stmt, LoopStatement):
            assert stmt.body is not None
            while True:
                self._tick(stmt)
                cond = self._pop(frame, 1, "the loop 'NO u !'", stmt)[0]
                if not truthy(cond):
                    break
                result = self.exec_block(stmt.body, Frame(parent=frame))
                frame.stack.append(result)
                frame.current = result
            frame.current = None
            self._apply_trailing(stmt, frame, None, False, pre_current)
        elif isinstance(stmt, DelayedAssignStatement):
            frame.deferred.append(frame.current)
            # The construct's own result is the captured value; it is not
            # pushed and (by the parser) carries no trailing modifiers.
        else:  # pragma: no cover - defensive
            raise AssertionError(f"unknown statement type {type(stmt).__name__}")

        if self.trace:
            self._trace_after(stmt, frame)

    def _apply_trailing(
        self,
        stmt: Statement,
        frame: Frame,
        value: Value,
        pushed: bool,
        pre_current: Value,
    ) -> None:
        if stmt.trailing is Trailing.NONE:
            return
        if stmt.trailing is Trailing.RETURN:
            raise BlockReturn(value)
        if stmt.trailing is Trailing.SUPPRESS:
            if pushed:
                frame.stack.pop()
            frame.current = pre_current
            return
        if stmt.trailing is Trailing.NEGATE:
            negated = not truthy(value)
            if pushed:
                frame.stack[-1] = negated
            frame.current = negated
            return

    # -- expressions ----------------------------------------------------------------

    def _pop(self, frame: Frame, count: int, what: str, stmt: Statement) -> list[Value]:
        if len(frame.stack) < count:
            raise self._error(
                f"stack underflow: {what} needs {count} operand"
                f"{'s' if count != 1 else ''} but the stack holds {len(frame.stack)}",
                line=stmt.line,
                raw=stmt.raw,
            )
        values = frame.stack[-count:]
        del frame.stack[-count:]
        return values

    def _eval_expr(self, expr: Expr, stmt: Statement, frame: Frame) -> tuple[Value, bool]:
        """Evaluate one expression; returns (value, pushed)."""
        self._tick(stmt)

        if isinstance(expr, EqualityExpr):
            right, left = self._pop(frame, 2, "equality '!, !'", stmt)[::-1]
            result: Value = values_equal(left, right)
            frame.stack.append(result)
            frame.current = result
            return result, True

        if isinstance(expr, LiteralExpr):
            frame.stack.append(expr.value)
            frame.current = expr.value
            return expr.value, True

        kind = expr.token.kind

        if kind is TokenKind.PUSH_TRUE:
            return self._push(frame, True)
        if kind is TokenKind.PUSH_FALSE:
            return self._push(frame, False)
        if kind is TokenKind.PUSH_NULL:
            return self._push(frame, None)
        if kind is TokenKind.LOAD_CURRENT:
            return self._push(frame, frame.current)
        if kind is TokenKind.BANG:
            (operand,) = self._pop(frame, 1, "negation '!'", stmt)
            return self._push(frame, not truthy(operand))
        if kind is TokenKind.ADD:
            right, left = self._pop(frame, 2, "'nooo u'", stmt)[::-1]
            return self._push(frame, self._add(left, right, expr, stmt))
        if kind is TokenKind.LOAD_VAR:
            name = expr.token.name
            assert name is not None
            binding = frame.lookup(name)
            if binding is None:
                raise self._expr_error(
                    f"variable no{escape_name(name)}u is not bound",
                    expr,
                    stmt,
                    suggestion="bind it first with NO"
                    + escape_name(name)
                    + "u (mutable) or NO"
                    + escape_name(name)
                    + "U (immutable)",
                )
            return self._push(frame, binding.value)
        if kind is TokenKind.STORE_IMMUT:
            name = expr.token.name
            assert name is not None
            (value,) = self._pop(frame, 1, "'NO U' (immutable store)", stmt)
            existing = frame.bindings.get(name)
            if existing is not None:
                what = "an immutable" if not existing.mutable else "a mutable"
                raise self._expr_error(
                    f"cannot create immutable binding {escape_name(name)}: "
                    f"this block already has {what} binding with that name",
                    expr,
                    stmt,
                )
            frame.bindings[name] = Binding(value=value, mutable=False)
            return self._push(frame, value)
        if kind is TokenKind.STORE_MUT:
            name = expr.token.name
            assert name is not None
            (value,) = self._pop(frame, 1, "'NO u' (mutable store)", stmt)
            self._store_mut(name, value, frame, stmt_line=stmt.line, expr=expr, stmt=stmt)
            return self._push(frame, value)
        if kind is TokenKind.CALL0:
            (callee,) = self._pop(frame, 1, "'nou' (zero-argument call)", stmt)
            result = self._call(callee, [], expr, stmt)
            return self._push(frame, result)
        if kind is TokenKind.BIG_CALL:
            popped = self._pop(frame, 7, "'NOOOOOO UUUUUUUU' (a callable and six arguments)", stmt)
            callee = popped[0]
            args = popped[1:]  # a1..a6 in source order
            result = self._call(callee, args, expr, stmt)
            # Only user-function list returns fan out into multiple outputs.
            # Builtins return exactly one output (else append could never
            # hand back a usable list value).
            if isinstance(callee, Function) and type(result) is list:
                outputs = list(result[:8]) + [None] * max(0, 8 - len(result))
            else:
                outputs = [result] + [None] * 7
            frame.stack.extend(outputs)
            frame.current = outputs[-1]
            return outputs[-1], True

        raise AssertionError(f"unhandled token kind {kind}")  # pragma: no cover

    def _push(self, frame: Frame, value: Value) -> tuple[Value, bool]:
        frame.stack.append(value)
        frame.current = value
        return value, True

    def _add(self, left: Value, right: Value, expr: Expr, stmt: Statement) -> Value:
        if type(left) is int and type(right) is int:
            return left + right
        if type(left) is str and type(right) is str:
            return left + right
        if type(left) is list and type(right) is list:
            return left + right
        raise self._expr_error(
            f"'nooo u' cannot combine {to_repr(left)} and {to_repr(right)}: "
            "operands must be two integers, two strings, or two lists",
            expr,
            stmt,
        )

    def _store_mut(
        self,
        name: str,
        value: Value,
        frame: Frame,
        stmt_line: int,
        expr: Expr | None = None,
        stmt: Statement | None = None,
    ) -> None:
        target: Frame | None = frame
        while target is not None:
            binding = target.bindings.get(name)
            if binding is not None:
                if not binding.mutable:
                    message = (
                        f"cannot assign to immutable binding {escape_name(name)}"
                    )
                    if expr is not None and stmt is not None:
                        raise self._expr_error(message, expr, stmt)
                    raise self._error(message, line=stmt_line)
                binding.value = value
                return
            target = target.parent
        frame.bindings[name] = Binding(value=value, mutable=True)

    # -- calls -----------------------------------------------------------------------

    def _call(self, callee: Value, args: list[Value], expr: Expr, stmt: Statement) -> Value:
        if isinstance(callee, Builtin):
            padded = list(args[: callee.params])
            while len(padded) < callee.params:
                padded.append(None)
            return callee.fn(self, padded)
        if isinstance(callee, Function):
            frame = Frame(parent=callee.closure)
            for i in range(callee.params):
                name = " " * (i + 1)
                value = args[i] if i < len(args) else None
                frame.bindings[name] = Binding(value=value, mutable=True)
            return self.exec_block(callee.body, frame)
        raise self._expr_error(
            f"value {to_repr(callee)} is not callable",
            expr,
            stmt,
            suggestion="only functions (nooooo uuuuuu) and builtins can be called",
        )

    # -- tracing -----------------------------------------------------------------------

    def _trace_before(self, stmt: Statement, frame: Frame) -> None:
        code = stmt.raw.strip("\t")
        print(
            f"[trace] line {stmt.line} phase {stmt.phase} depth {self._depth} | {code!r}",
            file=sys.stderr,
        )
        print(
            f"        stack before: [{', '.join(to_repr(v) for v in frame.stack)}]",
            file=sys.stderr,
        )

    def _trace_after(self, stmt: Statement, frame: Frame) -> None:
        print(
            f"        stack after:  [{', '.join(to_repr(v) for v in frame.stack)}]",
            file=sys.stderr,
        )
        print(f"        current: {to_repr(frame.current)}", file=sys.stderr)
        bindings = ", ".join(
            f"{escape_name(k)}={to_repr(b.value)}{'' if b.mutable else ' (immutable)'}"
            for k, b in frame.bindings.items()
        )
        print(f"        bindings: {{{bindings}}}", file=sys.stderr)


def run_source(
    source: str,
    filename: str = "<source>",
    step_limit: int = DEFAULT_STEP_LIMIT,
    trace: bool = False,
    stdin: typing.TextIO | None = None,
    stdout: typing.TextIO | None = None,
) -> Frame:
    """Parse and execute source; returns the module's top-level frame."""
    from .parser import parse_source

    module = parse_source(source, filename)
    interp = Interpreter(
        step_limit=step_limit,
        trace=trace,
        stdin=stdin,
        stdout=stdout,
        filename=filename,
    )
    return interp.run_module(module)
