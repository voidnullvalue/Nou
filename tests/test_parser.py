"""Parser tests: block structure, phases, headers, delayed assignment,
indentation errors, comma lists, and equality fusion."""

from __future__ import annotations

import unittest

from nou.ast import (
    CondStatement,
    DelayedAssignStatement,
    EqualityExpr,
    ExprStatement,
    FuncDefStatement,
    LoopStatement,
    OpExpr,
)
from nou.diagnostics import NoUSyntaxError
from nou.parser import parse_source
from nou.tokens import TokenKind, Trailing


class BlockStructureTests(unittest.TestCase):
    def test_flat_block(self) -> None:
        mod = parse_source("no\nNO\nu")
        self.assertEqual(len(mod.block.statements), 3)

    def test_nested_anonymous_block(self) -> None:
        mod = parse_source("no\n\tNO\n\tu\nno")
        stmts = mod.block.statements
        self.assertEqual(len(stmts), 2)
        first = stmts[0]
        assert isinstance(first, ExprStatement)
        self.assertIsNotNone(first.nested)
        self.assertEqual(len(first.nested.statements), 2)

    def test_deeper_nesting(self) -> None:
        mod = parse_source("no\n\tno\n\t\tno\nno")
        outer = mod.block.statements[0]
        assert isinstance(outer, ExprStatement)
        inner = outer.nested.statements[0]
        assert isinstance(inner, ExprStatement)
        self.assertIsNotNone(inner.nested)

    def test_indent_jump_rejected(self) -> None:
        with self.assertRaises(NoUSyntaxError) as ctx:
            parse_source("no\n\t\tno")
        self.assertEqual(ctx.exception.diagnostic.category, "IndentationError")

    def test_indent_without_anchor_rejected(self) -> None:
        with self.assertRaises(NoUSyntaxError):
            parse_source("\tno")

    def test_dedent_closes_blocks(self) -> None:
        mod = parse_source("no\n\tno\n\t\tno\nNO")
        self.assertEqual(len(mod.block.statements), 2)


class PhaseTests(unittest.TestCase):
    def test_space_depth_becomes_phase(self) -> None:
        mod = parse_source("  no\nno\n no")
        phases = [s.phase for s in mod.block.statements]
        self.assertEqual(phases, [2, 0, 1])
        self.assertEqual(mod.block.phases(), [0, 1, 2])

    def test_phases_inside_nested_block(self) -> None:
        mod = parse_source("no\n\t no\n\tno")
        nested = mod.block.statements[0].nested
        self.assertEqual([s.phase for s in nested.statements], [1, 0])


class HeaderTests(unittest.TestCase):
    def test_conditional_header(self) -> None:
        mod = parse_source("no\nNO U !\n\tno")
        cond = mod.block.statements[1]
        self.assertIsInstance(cond, CondStatement)
        self.assertIsNotNone(cond.body)

    def test_loop_header(self) -> None:
        mod = parse_source("no\nNO u !\n\tno ")
        loop = mod.block.statements[1]
        self.assertIsInstance(loop, LoopStatement)
        self.assertIsNotNone(loop.body)

    def test_headers_require_bodies(self) -> None:
        with self.assertRaises(NoUSyntaxError):
            parse_source("no\nNO U !")
        with self.assertRaises(NoUSyntaxError):
            parse_source("no\nNO u !\nno")

    def test_store_without_bang_is_not_a_header(self) -> None:
        mod = parse_source("no, NO U")
        stmt = mod.block.statements[0]
        assert isinstance(stmt, ExprStatement)
        self.assertIs(stmt.exprs[1].token.kind, TokenKind.STORE_IMMUT)

    def test_header_with_comma_is_plain_expressions(self) -> None:
        # `NO U, !` is a store followed by negation, not a header.
        mod = parse_source("no, NO U, !")
        stmt = mod.block.statements[0]
        assert isinstance(stmt, ExprStatement)
        self.assertEqual(len(stmt.exprs), 3)


class FunctionDefTests(unittest.TestCase):
    def test_funcdef_with_body(self) -> None:
        mod = parse_source("nooooo uuuuuu\n\tno ")
        fd = mod.block.statements[0]
        assert isinstance(fd, FuncDefStatement)
        self.assertEqual(fd.params, 5)
        self.assertEqual(fd.local_slots, 6)
        self.assertIsNotNone(fd.body)

    def test_funcdef_requires_body(self) -> None:
        with self.assertRaises(NoUSyntaxError):
            parse_source("nooooo uuuuuu")

    def test_funcdef_must_stand_alone(self) -> None:
        with self.assertRaises(NoUSyntaxError):
            parse_source("no, nooooo uuuuuu\n\tno")


class DelayedAssignmentTests(unittest.TestCase):
    def test_recognized(self) -> None:
        mod = parse_source("no\nNo\n  U")
        stmt = mod.block.statements[1]
        self.assertIsInstance(stmt, DelayedAssignStatement)

    def test_indented_form(self) -> None:
        mod = parse_source("no\n\tNo\n\t  U\nno")
        nested = mod.block.statements[0].nested
        self.assertIsInstance(nested.statements[0], DelayedAssignStatement)

    def test_blank_line_terminates_construct(self) -> None:
        # An intervening empty line breaks the pair; the U line is then stray.
        with self.assertRaises(NoUSyntaxError) as ctx:
            parse_source("No\n\n  U")
        self.assertIn("stray 'U' line", ctx.exception.diagnostic.message)

    def test_wrong_space_depth_rejected(self) -> None:
        with self.assertRaises(NoUSyntaxError) as ctx:
            parse_source("No\n   U")
        self.assertIn("misindented 'U' line", ctx.exception.diagnostic.message)

    def test_wrong_tab_depth_rejected(self) -> None:
        with self.assertRaises(NoUSyntaxError):
            parse_source("no\nNo\n\t  U")

    def test_no_with_other_exprs_is_plain_null(self) -> None:
        with self.assertRaises(NoUSyntaxError) as ctx:
            parse_source("no, No\n  U")
        self.assertIn("stray 'U' line", ctx.exception.diagnostic.message)

    def test_trailing_whitespace_on_no_line_rejected(self) -> None:
        with self.assertRaises(NoUSyntaxError) as ctx:
            parse_source("No \n  U")
        self.assertIn("trailing whitespace", ctx.exception.diagnostic.message)

    def test_stray_u_alone(self) -> None:
        with self.assertRaises(NoUSyntaxError):
            parse_source("  U")

    def test_u_mid_line_rejected(self) -> None:
        with self.assertRaises(NoUSyntaxError):
            parse_source("no, U")

    def test_nested_block_after_delayed_rejected(self) -> None:
        with self.assertRaises(NoUSyntaxError):
            parse_source("no\nNo\n  U\n\tno")


class ExpressionListTests(unittest.TestCase):
    def test_comma_separated(self) -> None:
        mod = parse_source("!1!, !2!, nooo u")
        stmt = mod.block.statements[0]
        assert isinstance(stmt, ExprStatement)
        self.assertEqual(len(stmt.exprs), 3)

    def test_empty_segment_rejected(self) -> None:
        for bad in ("no,, u", "no,", ", no", "no, "):
            with self.subTest(bad=bad), self.assertRaises(NoUSyntaxError):
                parse_source(bad)

    def test_equality_fusion(self) -> None:
        mod = parse_source("!1!, !1!, !, !")
        stmt = mod.block.statements[0]
        assert isinstance(stmt, ExprStatement)
        self.assertEqual(len(stmt.exprs), 3)
        self.assertIsInstance(stmt.exprs[2], EqualityExpr)

    def test_three_bangs_fuse_left_to_right(self) -> None:
        mod = parse_source("no, !, !, !")
        stmt = mod.block.statements[0]
        kinds = [type(e).__name__ for e in stmt.exprs]
        self.assertEqual(kinds, ["OpExpr", "EqualityExpr", "OpExpr"])

    def test_bang_separated_by_operand_does_not_fuse(self) -> None:
        mod = parse_source("no, !, no, !")
        stmt = mod.block.statements[0]
        self.assertEqual(len(stmt.exprs), 4)
        self.assertTrue(all(isinstance(e, OpExpr) for e in stmt.exprs))


class AmbiguityTests(unittest.TestCase):
    def test_trailing_modifiers_recorded_on_statements(self) -> None:
        mod = parse_source("no \nno")
        self.assertIs(mod.block.statements[0].trailing, Trailing.RETURN)

    def test_conditional_vs_loop_headers_distinct(self) -> None:
        mod = parse_source("no\nNO U !\n\tno\nno\nNO u !\n\tno")
        self.assertIsInstance(mod.block.statements[1], CondStatement)
        self.assertIsInstance(mod.block.statements[3], LoopStatement)

    def test_bare_no_line_without_u_is_null_statement(self) -> None:
        mod = parse_source("No\nno")
        stmt = mod.block.statements[0]
        assert isinstance(stmt, ExprStatement)
        self.assertIs(stmt.exprs[0].token.kind, TokenKind.PUSH_NULL)


if __name__ == "__main__":
    unittest.main()
