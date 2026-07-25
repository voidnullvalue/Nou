"""Runtime tests: every operator, stack discipline, bindings, calls,
deferred assignments, truthiness, equality, phases, and step limits."""

from __future__ import annotations

import io
import unittest

from nou.diagnostics import NoURuntimeError
from nou.runtime import Frame, run_source
from nou.values import Builtin, Function


def run(source: str, stdin: str = "", step_limit: int = 1_000_000):
    """Run source; return (stdout text, top-level frame)."""
    out = io.StringIO()
    frame = run_source(
        source,
        filename="<test>",
        step_limit=step_limit,
        stdin=io.StringIO(stdin),
        stdout=out,
    )
    return out.getvalue(), frame


PRINT = "no\tu"
PAD = "No, No, No, No, No, NOOOOOO UUUUUUUU"

# Dropping the seven Null outputs a big call stacks on top of output one:
# three suppressed equalities (net -2 each) and one suppressed negation
# (net -1). This is the idiomatic No U "drop 7".
DROP7 = "!, !  \n!, !  \n!, !  \n!  "


def build_list_source(n: int) -> str:
    """Source that leaves the list [0, 1, ..., n-1] in the 8-space binding."""
    lines = ["no\t\t\t\t\t\tu, nou, NO        u"]
    for i in range(n):
        lines.append(
            f"no\t\t\t\t\t\t\tu, no        u, !{i}!, No, No, No, No, NOOOOOO UUUUUUUU"
        )
        lines.append(DROP7)
        lines.append("NO        u")
    return "\n".join(lines) + "\n"


class OperatorTests(unittest.TestCase):
    def test_push_true_false_null(self) -> None:
        _, frame = run("no, NO, No")
        self.assertEqual(frame.stack, [True, False, None])
        self.assertIsNone(frame.current)

    def test_load_current(self) -> None:
        _, frame = run("!7!, u")
        self.assertEqual(frame.stack, [7, 7])

    def test_load_current_with_no_value_is_null(self) -> None:
        _, frame = run("u")
        self.assertEqual(frame.stack, [None])

    def test_current_is_per_block(self) -> None:
        # The nested block starts with its own Null current value; its `u`
        # therefore stores Null into the pre-existing outer binding.
        _, frame = run("!9!, NO u\n!5!\n\tu, NO u\nno u")
        self.assertEqual(frame.stack, [9, 5, None, None])

    def test_negation(self) -> None:
        _, frame = run("!0!, !")
        self.assertEqual(frame.stack, [True])
        _, frame = run('!"x"!, !')
        self.assertEqual(frame.stack, [False])

    def test_addition(self) -> None:
        _, frame = run("!1!, !2!, nooo u")
        self.assertEqual(frame.stack, [3])

    def test_concatenation(self) -> None:
        _, frame = run('!"a"!, !"b"!, nooo u')
        self.assertEqual(frame.stack, ["ab"])

    def test_add_type_error(self) -> None:
        with self.assertRaises(NoURuntimeError) as ctx:
            run('!1!, !"b"!, nooo u')
        self.assertIn("nooo u", ctx.exception.diagnostic.message)

    def test_add_pops_right_then_left(self) -> None:
        _, frame = run('!"left"!, !"right"!, nooo u')
        self.assertEqual(frame.stack, ["leftright"])

    def test_literals(self) -> None:
        _, frame = run("!null!, !true!, !false!, !-45!")
        self.assertEqual(frame.stack, [None, True, False, -45])


class StackDisciplineTests(unittest.TestCase):
    def test_underflow_negation(self) -> None:
        with self.assertRaises(NoURuntimeError) as ctx:
            run("!")
        self.assertIn("stack underflow", ctx.exception.diagnostic.message)

    def test_underflow_addition(self) -> None:
        with self.assertRaises(NoURuntimeError) as ctx:
            run("!1!, nooo u")
        self.assertIn("needs 2 operands", ctx.exception.diagnostic.message)

    def test_underflow_big_call(self) -> None:
        with self.assertRaises(NoURuntimeError):
            run("no, NOOOOOO UUUUUUUU")

    def test_underflow_store(self) -> None:
        with self.assertRaises(NoURuntimeError):
            run("NO u")


class BindingTests(unittest.TestCase):
    def test_mutable_create_update_read(self) -> None:
        _, frame = run("!1!, NO u\n!2!, NO u\nno u")
        self.assertEqual(frame.stack[-1], 2)

    def test_store_returns_value(self) -> None:
        _, frame = run("!5!, NO u")
        self.assertEqual(frame.stack, [5])
        self.assertEqual(frame.current, 5)

    def test_immutable_overwrite_fails(self) -> None:
        with self.assertRaises(NoURuntimeError) as ctx:
            run("!1!, NO U\n!2!, NO U")
        self.assertIn("immutable", ctx.exception.diagnostic.message)

    def test_mutable_store_over_immutable_fails(self) -> None:
        with self.assertRaises(NoURuntimeError):
            run("!1!, NO U\n!2!, NO u")

    def test_distinct_whitespace_names_are_distinct_slots(self) -> None:
        _, frame = run("!1!, NO u\n!2!, NO  u\n!3!, NO   u\nno u, no  u, no   u")
        self.assertEqual(frame.stack[-3:], [1, 2, 3])

    def test_unbound_variable(self) -> None:
        with self.assertRaises(NoURuntimeError) as ctx:
            run("no u")
        self.assertIn("no<SP>u is not bound", ctx.exception.diagnostic.message)

    def test_inner_block_updates_outer_mutable(self) -> None:
        _, frame = run("!1!, NO u\nno\n\t!2!, NO u\nno u")
        self.assertEqual(frame.stack[-1], 2)

    def test_immutable_shadowing_in_inner_block_allowed(self) -> None:
        # Immutable stores always create locally, so an inner block may
        # shadow an outer immutable binding of the same name.
        out, _ = run(f"!1!, NO U\nno\n\t!2!, NO U\n\t{PRINT}, no u, {PAD}\n{PRINT}, no u, {PAD}")
        self.assertEqual(out, "2\n1\n")

    def test_builtin_bindings_are_immutable(self) -> None:
        with self.assertRaises(NoURuntimeError):
            run("!1!, NO\tu")


class FunctionTests(unittest.TestCase):
    def test_zero_arg_call(self) -> None:
        _, frame = run('nooooo uuuuuu\n\t!"r"! \nnou')
        self.assertEqual(frame.stack, ["r"])

    def test_missing_arguments_are_null(self) -> None:
        # Called with zero args, parameter one is Null; return it.
        _, frame = run("nooooo uuuuuu\n\tno u \nnou")
        self.assertEqual(frame.stack, [None])

    def test_call_non_callable(self) -> None:
        with self.assertRaises(NoURuntimeError) as ctx:
            run("!1!, nou")
        self.assertIn("not callable", ctx.exception.diagnostic.message)

    def test_function_returns_null_without_block_return(self) -> None:
        _, frame = run("nooooo uuuuuu\n\t!1!\nnou")
        self.assertEqual(frame.stack, [None])

    def test_five_parameters_in_order(self) -> None:
        src = (
            "nooooo uuuuuu\n"
            "\tno u, no  u, nooo u, no   u, nooo u, no    u, nooo u, no     u, nooo u \n"
            "!1!, !2!, !3!, !4!, !5!, !0!, NOOOOOO UUUUUUUU"
        )
        # Stack: fn a1..a6 -> call.
        _, frame = run(src)
        self.assertEqual(frame.stack[0], 15)

    def test_closure_reads_defining_scope(self) -> None:
        # Parameters occupy the one- to five-space slots, so the closure
        # test must use a six-space name to avoid being shadowed.
        _, frame = run("!9!, NO      U\nnooooo uuuuuu\n\tno      u \nnou")
        self.assertEqual(frame.stack[-1], 9)

    def test_parameters_shadow_closure_slots(self) -> None:
        # A two-space binding in the closure is shadowed by parameter two,
        # which is Null in a zero-argument call.
        _, frame = run("!9!, NO  U\nnooooo uuuuuu\n\tno  u \nnou")
        self.assertIsNone(frame.stack[-1])


class BigCallTests(unittest.TestCase):
    def test_scalar_result_padded_to_eight(self) -> None:
        _, frame = run('nooooo uuuuuu\n\t!"x"! \nNo, No, No, No, No, No, NOOOOOO UUUUUUUU')
        self.assertEqual(frame.stack, ["x"] + [None] * 7)
        self.assertIsNone(frame.current)

    def test_builtin_list_result_is_single_output(self) -> None:
        # Builtins never fan out: append([], null) comes back as one list
        # output plus seven Nulls.
        src = (
            "no\t\t\t\t\t\t\tu, no\t\t\t\t\t\tu, nou, !null!, No, No, No, No, "
            "NOOOOOO UUUUUUUU"
        )
        _, frame = run(src)
        self.assertEqual(frame.stack, [[None]] + [None] * 7)

    def test_user_function_list_returns_fan_out(self) -> None:
        src = build_list_source(3) + (
            "nooooo uuuuuu\n"
            "\tno        u \n"
            "No, No, No, No, No, No, NOOOOOO UUUUUUUU"
        )
        _, frame = run(src)
        # [0, 1, 2] padded with five Nulls.
        self.assertEqual(frame.stack[-8:], [0, 1, 2, None, None, None, None, None])

    def test_list_longer_than_eight_truncated(self) -> None:
        src = build_list_source(9) + (
            "nooooo uuuuuu\n"
            "\tno        u \n"
            "No, No, No, No, No, No, NOOOOOO UUUUUUUU"
        )
        _, frame = run(src)
        self.assertEqual(frame.stack[-8:], [0, 1, 2, 3, 4, 5, 6, 7])

    def test_arguments_in_source_order(self) -> None:
        src = (
            "nooooo uuuuuu\n"
            '\tno u, no  u, nooo u \n'
            '!"a"!, !"b"!, !"c"!, !"d"!, !"e"!, !"f"!, NOOOOOO UUUUUUUU'
        )
        _, frame = run(src)
        self.assertEqual(frame.stack[0], "ab")


class TrailingBehaviorTests(unittest.TestCase):
    def test_trailing_space_returns_from_function(self) -> None:
        _, frame = run('nooooo uuuuuu\n\t!"early"! \n\t!"late"!\nnou')
        self.assertEqual(frame.stack, ["early"])

    def test_trailing_space_skips_later_phases(self) -> None:
        out, _ = run(
            "nooooo uuuuuu\n"
            "\t!1! \n"
            f"\t {PRINT}, !\"phase one never runs\"!, {PAD}\n"
            "nou"
        )
        self.assertEqual(out, "")

    def test_trailing_two_spaces_suppresses(self) -> None:
        _, frame = run("!1!\n!2!  \nu")
        # !2! was suppressed: popped, and current restored to 1.
        self.assertEqual(frame.stack, [1, 1])

    def test_trailing_tab_negates(self) -> None:
        _, frame = run("!0!\t")
        self.assertEqual(frame.stack, [True])
        _, frame = run("!17!\t")
        self.assertEqual(frame.stack, [False])

    def test_trailing_tab_negates_last_expression_only(self) -> None:
        _, frame = run("!1!, !2!\t")
        self.assertEqual(frame.stack, [1, False])

    def test_module_level_return_stops_program(self) -> None:
        out, _ = run(f"!1! \n{PRINT}, !2!, {PAD}")
        self.assertEqual(out, "")


class ControlFlowTests(unittest.TestCase):
    def test_conditional_true(self) -> None:
        out, _ = run(f'!1!\nNO U !\n\t{PRINT}, !"yes"!, {PAD}')
        self.assertEqual(out, "yes\n")

    def test_conditional_false(self) -> None:
        out, frame = run(f'!0!\nNO U !\n\t{PRINT}, !"no"!, {PAD}')
        self.assertEqual(out, "")
        self.assertEqual(frame.stack, [])  # condition consumed, nothing pushed

    def test_conditional_pushes_body_result(self) -> None:
        _, frame = run("!1!\nNO U !\n\t!42! ")
        self.assertEqual(frame.stack, [42])

    def test_while_loop_countdown(self) -> None:
        out, _ = run(
            "!3!, NO u\nno u\nNO u !\n"
            f"\t{PRINT}, no u, {PAD}\n"
            "\tno u, !-1!, nooo u, NO u "
        )
        self.assertEqual(out, "3\n2\n1\n")

    def test_loop_leaves_null_current(self) -> None:
        _, frame = run("!0!\nNO u !\n\tno ")
        self.assertIsNone(frame.current)

    def test_step_limit(self) -> None:
        with self.assertRaises(NoURuntimeError) as ctx:
            run("no\nNO u !\n\tno ", step_limit=500)
        self.assertIn("step limit", ctx.exception.diagnostic.message)

    def test_equality(self) -> None:
        _, frame = run("!1!, !1!, !, !")
        self.assertEqual(frame.stack, [True])
        _, frame = run('!"a"!, !"b"!, !, !')
        self.assertEqual(frame.stack, [False])

    def test_equality_is_type_strict(self) -> None:
        _, frame = run("!1!, !true!, !, !")
        self.assertEqual(frame.stack, [False])
        _, frame = run("!0!, !false!, !, !")
        self.assertEqual(frame.stack, [False])

    def test_equality_structural_lists(self) -> None:
        # Two separately built single-element lists compare structurally equal.
        one = (
            "no\t\t\t\t\t\t\tu, no\t\t\t\t\t\tu, nou, !5!, No, No, No, No, "
            "NOOOOOO UUUUUUUU\n" + DROP7 + "\n"
        )
        src = one + "NO         u\n" + one + "NO          u\n" + "no         u, no          u, !, !"
        _, frame = run(src)
        self.assertEqual(frame.stack[-1], True)


class TruthinessTests(unittest.TestCase):
    def test_falsy_values(self) -> None:
        for lit in ("!null!", "!false!", "!0!", '!""!'):
            with self.subTest(lit=lit):
                _, frame = run(f"{lit}, !")
                self.assertEqual(frame.stack[-1], True)

    def test_empty_list_falsy(self) -> None:
        _, frame = run("no\t\t\t\t\t\tu, nou, !")
        self.assertEqual(frame.stack[-1], True)

    def test_truthy_values(self) -> None:
        for lit in ("!true!", "!-1!", '!"x"!', "!42!"):
            with self.subTest(lit=lit):
                _, frame = run(f"{lit}, !")
                self.assertEqual(frame.stack[-1], False)


class PhaseAndDeferredTests(unittest.TestCase):
    def test_phase_ordering(self) -> None:
        out, _ = run(
            f"  {PRINT}, !\"two\"!, {PAD}\n"
            f"{PRINT}, !\"zero\"!, {PAD}\n"
            f" {PRINT}, !\"one\"!, {PAD}"
        )
        self.assertEqual(out, "zero\none\ntwo\n")

    def test_deferred_applies_at_phase_end(self) -> None:
        out, _ = run(
            '!"first"!, NO  u\n'
            '!"second"!\n'
            "No\n"
            "  U\n"
            f"{PRINT}, no  u, {PAD}\n"
            f" {PRINT}, no  u, {PAD}"
        )
        self.assertEqual(out, "first\nsecond\n")

    def test_deferred_in_source_order(self) -> None:
        # Two delayed assignments in one phase: the later one wins.
        out, _ = run(
            '!"a"!\n'
            "No\n"
            "  U\n"
            '!"b"!\n'
            "No\n"
            "  U\n"
            f" {PRINT}, no  u, {PAD}"
        )
        self.assertEqual(out, "b\n")

    def test_deferred_creates_binding_if_missing(self) -> None:
        _, frame = run("!5!\nNo\n  U\n no  u")
        self.assertEqual(frame.stack[-1], 5)

    def test_deterministic_repeat(self) -> None:
        src = (
            "!3!, NO u\nno u\nNO u !\n"
            f"\t{PRINT}, no u, {PAD}\n"
            "\tno u, !-1!, nooo u, NO u "
        )
        outputs = {run(src)[0] for _ in range(5)}
        self.assertEqual(len(outputs), 1)


class StdlibTests(unittest.TestCase):
    def test_print(self) -> None:
        out, _ = run(f"{PRINT}, !123!, {PAD}")
        self.assertEqual(out, "123\n")

    def test_read_line(self) -> None:
        out, _ = run(
            f"no\t\tu, nou, NO u\n{PRINT}, no u, {PAD}",
            stdin="hello there\nunused\n",
        )
        self.assertEqual(out, "hello there\n")

    def test_read_line_eof_is_null(self) -> None:
        _, frame = run("no\t\tu, nou", stdin="")
        self.assertIsNone(frame.stack[-1])

    def test_to_string(self) -> None:
        _, frame = run("no\t\t\tu, !true!, No, No, No, No, No, NOOOOOO UUUUUUUU")
        self.assertEqual(frame.stack[0], "true")

    def test_to_int(self) -> None:
        _, frame = run('no\t\t\t\tu, !"-42"!, No, No, No, No, No, NOOOOOO UUUUUUUU')
        self.assertEqual(frame.stack[0], -42)

    def test_to_int_error(self) -> None:
        with self.assertRaises(NoURuntimeError):
            run('no\t\t\t\tu, !"4x"!, No, No, No, No, No, NOOOOOO UUUUUUUU')

    def test_length(self) -> None:
        _, frame = run('no\t\t\t\t\tu, !"abc"!, No, No, No, No, No, NOOOOOO UUUUUUUU')
        self.assertEqual(frame.stack[0], 3)

    def test_make_list_and_append(self) -> None:
        src = (
            "no\t\t\t\t\t\t\tu, no\t\t\t\t\t\tu, nou, !9!, No, No, No, No, NOOOOOO UUUUUUUU"
        )
        _, frame = run(src)
        self.assertEqual(frame.stack, [[9]] + [None] * 7)

    def test_append_does_not_mutate(self) -> None:
        src = (
            "no\t\t\t\t\t\tu, nou, NO u\n"
            "no\t\t\t\t\t\t\tu, no u, !1!, No, No, No, No, NOOOOOO UUUUUUUU\n"
            "no u"
        )
        _, frame = run(src)
        self.assertEqual(frame.stack[-1], [])


if __name__ == "__main__":
    unittest.main()
