"""Command-line interface for No U.

    python -m nou run program.nou
    python -m nou check program.nou
    python -m nou tokens program.nou
    python -m nou ast program.nou
    python -m nou repl
"""

from __future__ import annotations

import argparse
import sys

from . import __version__
from . import ast as nou_ast
from .diagnostics import NoUError, escape_name, render_whitespace
from .lexer import Lexer, decode_source
from .parser import Parser
from .runtime import DEFAULT_STEP_LIMIT, Frame, Interpreter
from .tokens import LineKind, LogicalLine, Trailing
from .values import to_repr


def _read_file(path: str) -> str:
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError as exc:
        print(f"error: cannot read {path}: {exc.strerror}", file=sys.stderr)
        raise SystemExit(2) from None
    return decode_source(data, path)


def _lex(path: str) -> list[LogicalLine]:
    return Lexer(_read_file(path), path).lex()


def _parse(path: str) -> nou_ast.Module:
    return Parser(_lex(path), path).parse_module()


def cmd_run(args: argparse.Namespace) -> int:
    module = _parse(args.file)
    interp = Interpreter(
        step_limit=args.step_limit,
        trace=args.trace,
        filename=args.file,
    )
    interp.run_module(module)
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    module = _parse(args.file)
    count = sum(1 for _ in _walk_statements(module.block))
    print(f"OK: {args.file} ({count} statement{'s' if count != 1 else ''})")
    return 0


def _walk_statements(block: nou_ast.Block):
    for stmt in block.statements:
        yield stmt
        for child in (
            getattr(stmt, "body", None),
            getattr(stmt, "nested", None),
        ):
            if child is not None:
                yield from _walk_statements(child)


def cmd_tokens(args: argparse.Namespace) -> int:
    for line in _lex(args.file):
        head = (
            f"{args.file}:{line.line_no}: {line.kind.value} "
            f"indent(tabs={line.tab_depth}, spaces={line.space_depth})"
        )
        if line.trailing is not Trailing.NONE:
            head += f" trailing={line.trailing.value}"
        print(head)
        if args.show_whitespace and line.raw:
            print(f"    | {render_whitespace(line.raw)}")
        for tok in line.tokens:
            desc = f"    {tok.line}:{tok.col}-{tok.end_col}  {tok.kind.value:<12} {tok.escaped()}"
            if tok.name is not None:
                desc += f"  name={escape_name(tok.name)}"
            if tok.kind.value == "LITERAL":
                desc += f"  value={to_repr(tok.value)}"
            print(desc)
    return 0


def cmd_ast(args: argparse.Namespace) -> int:
    print(nou_ast.dump(_parse(args.file)))
    return 0


# -- REPL -----------------------------------------------------------------------

_NEEDS_BLOCK = {"NO U !", "NO u !", "nooooo uuuuuu", "No"}


def cmd_repl(args: argparse.Namespace) -> int:
    print(f"No U {__version__} — an esoteric language. Ctrl-D exits.")
    print("End a multi-line construct by submitting an empty line.")
    interp = Interpreter(step_limit=args.step_limit, trace=args.trace, filename="<repl>")
    frame = Frame(parent=interp.root)
    buffer: list[str] = []
    while True:
        prompt = "....> " if buffer else "no u> "
        try:
            line = input(prompt)
        except EOFError:
            print()
            return 0
        except KeyboardInterrupt:
            print()
            buffer.clear()
            continue
        if buffer:
            if line == "":
                _repl_execute(interp, frame, "\n".join(buffer))
                buffer.clear()
            else:
                buffer.append(line)
            continue
        if line.strip(" \t") == "":
            continue
        if line.rstrip(" \t") in _NEEDS_BLOCK:
            buffer.append(line)
            continue
        _repl_execute(interp, frame, line)


def _repl_execute(interp: Interpreter, frame: Frame, source: str) -> None:
    try:
        module = Parser(Lexer(source, "<repl>").lex(), "<repl>").parse_module()
        interp.exec_block(module.block, frame)
    except NoUError as exc:
        print(exc.render(), file=sys.stderr)
        return
    except RecursionError:
        print("RuntimeError: call depth exceeded", file=sys.stderr)
        return
    print(f"=> {to_repr(frame.current)}")


# -- argument parsing ---------------------------------------------------------------


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nou",
        description="No U — a deliberately irritating, whitespace-sensitive esoteric language.",
    )
    parser.add_argument("--version", action="version", version=f"nou {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--step-limit",
            type=int,
            default=DEFAULT_STEP_LIMIT,
            metavar="NUMBER",
            help=f"maximum interpreter operations (default {DEFAULT_STEP_LIMIT})",
        )
        p.add_argument(
            "--trace",
            action="store_true",
            help="trace statements, stacks, bindings, phases, and depth to stderr",
        )

    p_run = sub.add_parser("run", help="execute a program")
    p_run.add_argument("file")
    add_common(p_run)
    p_run.set_defaults(fn=cmd_run)

    p_check = sub.add_parser("check", help="lex and parse without executing")
    p_check.add_argument("file")
    p_check.set_defaults(fn=cmd_check)

    p_tokens = sub.add_parser("tokens", help="print tokens with escaped whitespace")
    p_tokens.add_argument("file")
    p_tokens.add_argument(
        "--show-whitespace",
        action="store_true",
        help="also render each source line with visible whitespace markers",
    )
    p_tokens.set_defaults(fn=cmd_tokens)

    p_ast = sub.add_parser("ast", help="print a readable AST")
    p_ast.add_argument("file")
    p_ast.set_defaults(fn=cmd_ast)

    p_repl = sub.add_parser("repl", help="interactive mode")
    add_common(p_repl)
    p_repl.set_defaults(fn=cmd_repl)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    try:
        return args.fn(args)
    except NoUError as exc:
        print(exc.render(), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
