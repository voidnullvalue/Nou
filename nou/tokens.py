"""Token and logical-line data structures produced by the lexer."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field

from .diagnostics import escape_token_text


class TokenKind(enum.Enum):
    PUSH_TRUE = "PUSH_TRUE"  # no
    PUSH_FALSE = "PUSH_FALSE"  # NO
    PUSH_NULL = "PUSH_NULL"  # No
    LOAD_CURRENT = "LOAD_CURRENT"  # u
    CALL0 = "CALL0"  # nou
    LOAD_VAR = "LOAD_VAR"  # no<ws>u
    STORE_IMMUT = "STORE_IMMUT"  # NO<ws>U
    STORE_MUT = "STORE_MUT"  # NO<ws>u
    BANG = "BANG"  # !
    ADD = "ADD"  # nooo u
    FUNC_DEF = "FUNC_DEF"  # nooooo uuuuuu
    BIG_CALL = "BIG_CALL"  # NOOOOOO UUUUUUUU
    LITERAL = "LITERAL"  # !...!
    U_MARKER = "U_MARKER"  # bare U (second line of delayed assignment)


class Trailing(enum.Enum):
    NONE = "none"  # no trailing whitespace
    RETURN = "return"  # one trailing space
    SUPPRESS = "suppress"  # two trailing spaces
    NEGATE = "negate"  # one trailing tab


class LineKind(enum.Enum):
    STATEMENT = "statement"
    COND_HEADER = "cond-header"  # NO U !
    LOOP_HEADER = "loop-header"  # NO u !
    BLANK = "blank"  # completely empty line
    WS_ONLY = "ws-only"  # whitespace-only line
    COMMENT_ONLY = "comment-only"


@dataclass
class Token:
    kind: TokenKind
    text: str  # exact source spelling
    line: int  # 1-based physical line
    col: int  # 1-based character column of first character
    end_col: int  # exclusive
    name: str | None = None  # whitespace name for LOAD_VAR / STORE_*
    value: object = None  # decoded value for LITERAL

    def escaped(self) -> str:
        return escape_token_text(self.text)


@dataclass
class LogicalLine:
    line_no: int  # 1-based physical line number
    kind: LineKind
    tab_depth: int
    space_depth: int
    tokens: list[Token] = field(default_factory=list)
    trailing: Trailing = Trailing.NONE
    raw: str = ""  # raw source line without newline
