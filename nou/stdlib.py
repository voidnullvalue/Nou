"""The No U standard library.

Builtins are installed as immutable bindings in the root frame, under
tab-based whitespace names:

    <TAB>                                print value        (1 parameter)
    <TAB><TAB>                           read one line      (0 parameters)
    <TAB><TAB><TAB>                      convert to string  (1 parameter)
    <TAB><TAB><TAB><TAB>                 convert to integer (1 parameter)
    <TAB><TAB><TAB><TAB><TAB>            length             (1 parameter)
    <TAB><TAB><TAB><TAB><TAB><TAB>       create empty list  (0 parameters)
    <TAB><TAB><TAB><TAB><TAB><TAB><TAB>  append             (2 parameters)

Load one with `no<TAB>u`, `no<TAB><TAB>u`, and so on. Because they are
immutable root bindings, `NO<TAB>u` / `NO<TAB>U` fail with a runtime error
rather than shadow or overwrite them (shadowing in an inner block with
`NO<TAB>U` is allowed, since immutable stores always create locally).

Call zero-parameter builtins with `nou`; call the others with
`NOOOOOO UUUUUUUU` (extra arguments are discarded; append returns a new
list and never mutates its argument).
"""

from __future__ import annotations

import re
import typing

from .diagnostics import Diagnostic, NoURuntimeError
from .values import Builtin, Function, Value, to_display, to_repr

if typing.TYPE_CHECKING:
    from .runtime import Frame, Interpreter

_STRICT_INT_RE = re.compile(r"-?[0-9]+")


def _rt_error(interp: "Interpreter", message: str, suggestion: str | None = None) -> NoURuntimeError:
    return NoURuntimeError(
        Diagnostic(
            category="RuntimeError",
            message=message,
            filename=interp.filename,
            line=0,
            col=0,
            suggestion=suggestion,
        )
    )


def _print(interp: "Interpreter", args: list[Value]) -> Value:
    interp.stdout.write(to_display(args[0]) + "\n")
    return None


def _read_line(interp: "Interpreter", args: list[Value]) -> Value:
    line = interp.stdin.readline()
    if line == "":
        return None
    if line.endswith("\n"):
        line = line[:-1]
    if line.endswith("\r"):
        line = line[:-1]
    return line


def _to_string(interp: "Interpreter", args: list[Value]) -> Value:
    return to_display(args[0])


def _to_int(interp: "Interpreter", args: list[Value]) -> Value:
    v = args[0]
    if type(v) is int:
        return v
    if v is True:
        return 1
    if v is False:
        return 0
    if type(v) is str:
        if _STRICT_INT_RE.fullmatch(v):
            return int(v, 10)
        raise _rt_error(
            interp,
            f"to-int cannot parse {to_repr(v)} as a base-10 integer",
            suggestion="the string must match -?[0-9]+ exactly, with no surrounding whitespace",
        )
    raise _rt_error(interp, f"to-int cannot convert {to_repr(v)}")


def _length(interp: "Interpreter", args: list[Value]) -> Value:
    v = args[0]
    if type(v) is str or type(v) is list:
        return len(v)
    raise _rt_error(interp, f"length requires a string or a list, not {to_repr(v)}")


def _make_list(interp: "Interpreter", args: list[Value]) -> Value:
    return []


def _append(interp: "Interpreter", args: list[Value]) -> Value:
    lst, item = args
    if type(lst) is not list:
        raise _rt_error(interp, f"append requires a list as its first argument, not {to_repr(lst)}")
    return lst + [item]  # a new list; No U lists are never mutated in place


BUILTINS: list[Builtin] = [
    Builtin(name="print", binding="\t", params=1, fn=_print),
    Builtin(name="read-line", binding="\t\t", params=0, fn=_read_line),
    Builtin(name="to-string", binding="\t\t\t", params=1, fn=_to_string),
    Builtin(name="to-int", binding="\t\t\t\t", params=1, fn=_to_int),
    Builtin(name="length", binding="\t\t\t\t\t", params=1, fn=_length),
    Builtin(name="make-list", binding="\t\t\t\t\t\t", params=0, fn=_make_list),
    Builtin(name="append", binding="\t\t\t\t\t\t\t", params=2, fn=_append),
]


def install_builtins(root: "Frame") -> None:
    from .runtime import Binding

    for builtin in BUILTINS:
        root.bindings[builtin.binding] = Binding(value=builtin, mutable=False)
