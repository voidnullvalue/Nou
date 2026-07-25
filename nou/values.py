"""Runtime values for No U.

Value types: Null (Python None), Boolean, Integer, String, List (Python list,
manipulated only through non-mutating operations), Function, Builtin.
"""

from __future__ import annotations

import typing
from dataclasses import dataclass

from .diagnostics import escape_name

if typing.TYPE_CHECKING:
    from .ast import Block
    from .runtime import Frame, Interpreter

Value = typing.Union[None, bool, int, str, list, "Function", "Builtin"]


@dataclass(eq=False)
class Function:
    """A user-defined function. Equality is identity."""

    params: int  # number of parameters (bound to <SP>, <SP><SP>, ...)
    local_slots: int  # declared local-slot capacity (metadata only)
    body: "Block"
    closure: "Frame"
    def_line: int


@dataclass(eq=False)
class Builtin:
    """A native function exposed through a whitespace binding."""

    name: str  # human-readable name, e.g. "print"
    binding: str  # the whitespace binding, e.g. "\t"
    params: int
    fn: typing.Callable[["Interpreter", list[Value]], Value]


def truthy(value: Value) -> bool:
    if value is None:
        return False
    if value is False:
        return False
    if type(value) is int and value == 0:
        return False
    if type(value) is str and value == "":
        return False
    if type(value) is list and len(value) == 0:
        return False
    return True


def values_equal(a: Value, b: Value) -> bool:
    """Structural equality. Booleans and integers are distinct types."""
    if type(a) is not type(b):
        return False
    if isinstance(a, (Function, Builtin)):
        return a is b
    if type(a) is list:
        assert type(b) is list
        if len(a) != len(b):
            return False
        return all(values_equal(x, y) for x, y in zip(a, b))
    return a == b


def quote_string(s: str) -> str:
    out = ['"']
    for ch in s:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def to_display(value: Value) -> str:
    """The canonical string form of a value (used by print and to-string)."""
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if type(value) is int:
        return str(value)
    if type(value) is str:
        return value
    if type(value) is list:
        return "[" + ", ".join(to_repr(v) for v in value) + "]"
    if isinstance(value, Function):
        return f"<function params={value.params} locals={value.local_slots}>"
    if isinstance(value, Builtin):
        return f"<builtin {value.name} {escape_name(value.binding)}>"
    raise AssertionError(f"unknown value type: {type(value)!r}")


def to_repr(value: Value) -> str:
    """Like to_display, but quotes strings (used inside lists and traces)."""
    if type(value) is str:
        return quote_string(value)
    return to_display(value)
