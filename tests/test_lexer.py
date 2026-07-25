"""Lexer tests: operator recognition, whitespace sensitivity, comments,
literals, encodings, homoglyphs, and source spans."""

from __future__ import annotations

import unittest

from nou.diagnostics import NoUSyntaxError
from nou.lexer import Lexer, decode_source, lex_source
from nou.tokens import LineKind, TokenKind, Trailing


def lex_line(code: str):
    """Lex a single line and return its tokens."""
    lines = lex_source(code)
    assert len(lines) == 1, lines
    return lines[0]


class OperatorRecognitionTests(unittest.TestCase):
    CASES = {
        "no": TokenKind.PUSH_TRUE,
        "NO": TokenKind.PUSH_FALSE,
        "No": TokenKind.PUSH_NULL,
        "u": TokenKind.LOAD_CURRENT,
        "nou": TokenKind.CALL0,
        "!": TokenKind.BANG,
        "nooo u": TokenKind.ADD,
        "nooooo uuuuuu": TokenKind.FUNC_DEF,
        "NOOOOOO UUUUUUUU": TokenKind.BIG_CALL,
        "no u": TokenKind.LOAD_VAR,
        "NO U": TokenKind.STORE_IMMUT,
        "NO u": TokenKind.STORE_MUT,
    }

    def test_every_legal_operator(self) -> None:
        for spelling, kind in self.CASES.items():
            with self.subTest(spelling=spelling):
                line = lex_line(spelling)
                self.assertEqual(len(line.tokens), 1)
                self.assertIs(line.tokens[0].kind, kind)
                self.assertEqual(line.tokens[0].text, spelling)

    def test_nou_vs_no_u_vs_no_two_spaces_u(self) -> None:
        self.assertIs(lex_line("nou").tokens[0].kind, TokenKind.CALL0)
        one = lex_line("no u").tokens[0]
        self.assertIs(one.kind, TokenKind.LOAD_VAR)
        self.assertEqual(one.name, " ")
        two = lex_line("no  u").tokens[0]
        self.assertIs(two.kind, TokenKind.LOAD_VAR)
        self.assertEqual(two.name, "  ")
        four = lex_line("no    u").tokens[0]
        self.assertEqual(four.name, "    ")

    def test_variable_names_may_mix_tabs_and_spaces(self) -> None:
        tok = lex_line("no \tu").tokens[0]
        self.assertIs(tok.kind, TokenKind.LOAD_VAR)
        self.assertEqual(tok.name, " \t")
        tok = lex_line("no\tu").tokens[0]
        self.assertEqual(tok.name, "\t")

    def test_case_sensitivity(self) -> None:
        self.assertIs(lex_line("NO u").tokens[0].kind, TokenKind.STORE_MUT)
        self.assertIs(lex_line("NO U").tokens[0].kind, TokenKind.STORE_IMMUT)
        self.assertIs(lex_line("no u").tokens[0].kind, TokenKind.LOAD_VAR)
        with self.assertRaises(NoUSyntaxError):
            lex_line("No u")  # mixed case is not an operator
        with self.assertRaises(NoUSyntaxError):
            lex_line("nO u")
        with self.assertRaises(NoUSyntaxError):
            lex_line("NOU")

    def test_malformed_multi_o_spellings_rejected(self) -> None:
        for bad in ("noo u", "nooo  u", "nooooo uuuuu", "NOOOOO UUUUUUUU"):
            with self.subTest(bad=bad), self.assertRaises(NoUSyntaxError):
                lex_line(bad)

    def test_no_whitespace_normalization_in_operators(self) -> None:
        exc = None
        try:
            lex_line("nooo  u")  # two spaces: not the addition operator
        except NoUSyntaxError as e:
            exc = e
        assert exc is not None
        self.assertIn("nooo<SP><SP>u", exc.diagnostic.message)


class IndentationTests(unittest.TestCase):
    def test_tab_and_space_coordinates(self) -> None:
        lines = lex_source("no\n\tno\n  no\n\t\t  no")
        coords = [(l.tab_depth, l.space_depth) for l in lines]
        self.assertEqual(coords, [(0, 0), (1, 0), (0, 2), (2, 2)])

    def test_tab_after_leading_space_rejected(self) -> None:
        with self.assertRaises(NoUSyntaxError) as ctx:
            lex_source("  \tno")
        self.assertIn("tab appears after indentation space", ctx.exception.diagnostic.message)
        self.assertEqual(ctx.exception.diagnostic.col, 3)

    def test_whitespace_only_line_is_recorded(self) -> None:
        lines = lex_source("no\n\t \nno")
        self.assertIs(lines[1].kind, LineKind.WS_ONLY)
        self.assertEqual((lines[1].tab_depth, lines[1].space_depth), (1, 1))

    def test_blank_line_is_recorded(self) -> None:
        lines = lex_source("no\n\nno")
        self.assertIs(lines[1].kind, LineKind.BLANK)


class TrailingWhitespaceTests(unittest.TestCase):
    def test_trailing_variants(self) -> None:
        self.assertIs(lex_line("no").trailing, Trailing.NONE)
        self.assertIs(lex_line("no ").trailing, Trailing.RETURN)
        self.assertIs(lex_line("no  ").trailing, Trailing.SUPPRESS)
        self.assertIs(lex_line("no\t").trailing, Trailing.NEGATE)

    def test_trailing_errors(self) -> None:
        for bad in ("no   ", "no\t\t", "no \t", "no\t "):
            with self.subTest(bad=repr(bad)), self.assertRaises(NoUSyntaxError):
                lex_line(bad)

    def test_trailing_space_does_not_join_variable(self) -> None:
        line = lex_line("no u ")
        self.assertEqual(line.tokens[0].name, " ")
        self.assertIs(line.trailing, Trailing.RETURN)


class CommentTests(unittest.TestCase):
    def test_comment_only_line(self) -> None:
        lines = lex_source("no! anything, even NO U ! !no")
        self.assertIs(lines[0].kind, LineKind.COMMENT_ONLY)

    def test_comment_after_operator(self) -> None:
        line = lex_line("no, u no! trailing comment !no")
        kinds = [t.kind for t in line.tokens]
        self.assertEqual(kinds, [TokenKind.PUSH_TRUE, TokenKind.LOAD_CURRENT])

    def test_comment_between_operators(self) -> None:
        line = lex_line("no no! middle !no , u")
        self.assertEqual(len(line.tokens), 2)

    def test_multiline_comment(self) -> None:
        lines = lex_source("no! starts here\nstill comment\nends !no\nno")
        self.assertIs(lines[0].kind, LineKind.COMMENT_ONLY)
        self.assertIs(lines[-1].kind, LineKind.STATEMENT)

    def test_unterminated_comment(self) -> None:
        with self.assertRaises(NoUSyntaxError) as ctx:
            lex_source("no! never closed\nno")
        self.assertIn("unterminated comment", ctx.exception.diagnostic.message)

    def test_multiline_comment_may_not_follow_code(self) -> None:
        with self.assertRaises(NoUSyntaxError):
            lex_source("no, no! spans\nlines !no")

    def test_code_after_multiline_terminator_rejected(self) -> None:
        with self.assertRaises(NoUSyntaxError):
            lex_source("no! spans\nends !no no")

    def test_comment_delimiters_inside_string_are_text(self) -> None:
        line = lex_line('!"no! not a comment !no"!')
        self.assertEqual(line.tokens[0].value, "no! not a comment !no")

    def test_comments_do_not_nest(self) -> None:
        # The first !no closes; the rest must be valid code (it is not).
        with self.assertRaises(NoUSyntaxError):
            lex_line("no! outer no! inner !no still-comment? !no")


class LiteralTests(unittest.TestCase):
    def test_scalar_literals(self) -> None:
        for text, value in [
            ("!null!", None),
            ("!true!", True),
            ("!false!", False),
            ("!123!", 123),
            ("!-45!", -45),
            ("!0!", 0),
        ]:
            with self.subTest(text=text):
                tok = lex_line(text).tokens[0]
                self.assertIs(tok.kind, TokenKind.LITERAL)
                self.assertEqual(tok.value, value)
                if isinstance(value, bool) or value is None:
                    self.assertIs(tok.value, value)

    def test_string_escapes(self) -> None:
        tok = lex_line(r'!"a\nb\rc\td\\e\"fA"!').tokens[0]
        self.assertEqual(tok.value, 'a\nb\rc\td\\e"f' + "A")

    def test_string_with_comma_and_bang(self) -> None:
        tok = lex_line('!"a,b!c"!').tokens[0]
        self.assertEqual(tok.value, "a,b!c")

    def test_invalid_payloads(self) -> None:
        for bad in ("!nul!", "!TRUE!", "!1.5!", "!+5!", "!-!", "! 1!", "!!"):
            with self.subTest(bad=bad), self.assertRaises(NoUSyntaxError):
                lex_line(bad)

    def test_bad_escape(self) -> None:
        with self.assertRaises(NoUSyntaxError):
            lex_line(r'!"\q"!')
        with self.assertRaises(NoUSyntaxError):
            lex_line(r'!"\u12"!')

    def test_unterminated_string(self) -> None:
        with self.assertRaises(NoUSyntaxError):
            lex_line('!"open')

    def test_standalone_bang_is_not_a_literal(self) -> None:
        line = lex_line("!, !")
        self.assertEqual([t.kind for t in line.tokens], [TokenKind.BANG, TokenKind.BANG])


class EncodingTests(unittest.TestCase):
    def test_crlf_and_lf_equivalent(self) -> None:
        a = lex_source("no\nno u\n")
        b = lex_source("no\r\nno u\r\n")
        self.assertEqual(
            [(l.kind, [t.kind for t in l.tokens]) for l in a],
            [(l.kind, [t.kind for t in l.tokens]) for l in b],
        )

    def test_final_newline_is_invisible(self) -> None:
        a = lex_source("no")
        b = lex_source("no\n")
        self.assertEqual(len(a), len(b))

    def test_invalid_utf8_rejected(self) -> None:
        with self.assertRaises(NoUSyntaxError) as ctx:
            decode_source(b"no\n\xff\xfe", "bad.nou")
        self.assertEqual(ctx.exception.diagnostic.category, "EncodingError")
        self.assertEqual(ctx.exception.diagnostic.line, 2)

    def test_lone_carriage_return_rejected(self) -> None:
        with self.assertRaises(NoUSyntaxError):
            lex_source("no\rno")

    def test_unicode_in_strings_not_normalized(self) -> None:
        # é as NFC vs NFD must stay distinct.
        nfc = lex_line('!"é"!').tokens[0].value
        nfd = lex_line('!"é"!').tokens[0].value
        self.assertNotEqual(nfc, nfd)


class HomoglyphTests(unittest.TestCase):
    def test_cyrillic_o_rejected_with_hint(self) -> None:
        with self.assertRaises(NoUSyntaxError) as ctx:
            lex_line("nо")  # CYRILLIC SMALL LETTER O
        self.assertIn("CYRILLIC SMALL LETTER O", ctx.exception.diagnostic.message)
        self.assertIn("U+043E", ctx.exception.diagnostic.message)

    def test_nbsp_between_no_and_u(self) -> None:
        with self.assertRaises(NoUSyntaxError) as ctx:
            lex_line("no u")
        self.assertIn("NO-BREAK SPACE", ctx.exception.diagnostic.message)

    def test_fullwidth_bang_rejected(self) -> None:
        with self.assertRaises(NoUSyntaxError) as ctx:
            lex_line("！")
        self.assertIn("FULLWIDTH", ctx.exception.diagnostic.message)


class SpanTests(unittest.TestCase):
    def test_token_spans_are_exact(self) -> None:
        line = lex_line("no, !12!, nooo u")
        spans = [(t.col, t.end_col) for t in line.tokens]
        self.assertEqual(spans, [(1, 3), (5, 9), (11, 17)])

    def test_spans_account_for_indentation(self) -> None:
        lines = lex_source("\t no")
        tok = lines[0].tokens[0]
        self.assertEqual((tok.col, tok.end_col), (3, 5))

    def test_spans_after_inline_comment(self) -> None:
        line = lex_line("no! c !no no, u")
        self.assertEqual(line.tokens[0].col, 11)
        self.assertEqual(line.tokens[1].col, 15)

    def test_error_positions(self) -> None:
        with self.assertRaises(NoUSyntaxError) as ctx:
            lex_source("no\nno, xyz")
        diag = ctx.exception.diagnostic
        self.assertEqual((diag.line, diag.col), (2, 5))


if __name__ == "__main__":
    unittest.main()
