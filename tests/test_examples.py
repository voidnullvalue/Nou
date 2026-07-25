"""End-to-end tests: run every example program and assert exact output."""

from __future__ import annotations

import io
import pathlib
import subprocess
import sys
import unittest

from nou.diagnostics import NoURuntimeError
from nou.lexer import decode_source
from nou.parser import parse_source
from nou.runtime import Interpreter

EXAMPLES = pathlib.Path(__file__).resolve().parent.parent / "examples"

EXPECTED: dict[str, str] = {
    "01-hello.nou": "Hello, World!\n",
    "02-add.nou": "3\n",
    "03-mutable.nou": "42\n",
    "05-conditional.nou": "yes\n",
    "06-while.nou": "3\n2\n1\n",
    "07-function.nou": "from function\n",
    "08-five-args.nou": "15\n",
    "09-delayed.nou": "first\nfirst\nsecond\n",
    "10-meanings.nou": "10\n20\n99\ncalled\n",
    "11-phases.nou": (
        "phase zero\nnested phase zero\nnested phase one\nphase one\nphase two\n"
    ),
    "12-return.nou": "early\n",
    "13-negate.nou": "true\n",
    "14-snake.nou": (
        "NO U SNAKE\n"
        "A closure-linked snake, written entirely in No U.\n"
        "+------------+\n"
        "|            |\n"
        "|            |\n"
        "|            |\n"
        "|            |\n"
        "|  oo@   *   |\n"
        "|            |\n"
        "|            |\n"
        "|            |\n"
        "+------------+\n"
        "Score: 0\n"
        "Move with w/a/s/d; q quits.\n"
        "Thanks for playing No U Snake.\n"
    ),
}

INPUTS: dict[str, str] = {
    "14-snake.nou": "q\n",
}


def run_file(path: pathlib.Path, stdin: str = "") -> str:
    source = decode_source(path.read_bytes(), str(path))
    module = parse_source(source, str(path))
    out = io.StringIO()
    interp = Interpreter(stdin=io.StringIO(stdin), stdout=out, filename=str(path))
    interp.run_module(module)
    return out.getvalue()


class ExampleTests(unittest.TestCase):
    def test_every_example_has_a_test(self) -> None:
        files = {p.name for p in EXAMPLES.glob("*.nou")}
        self.assertEqual(files, set(EXPECTED) | {"04-immutable-error.nou"})

    def test_examples_produce_exact_output(self) -> None:
        for name, expected in sorted(EXPECTED.items()):
            with self.subTest(example=name):
                self.assertEqual(
                    run_file(EXAMPLES / name, INPUTS.get(name, "")),
                    expected,
                )

    def test_snake_grows_after_eating(self) -> None:
        output = run_file(EXAMPLES / "14-snake.nou", "d\nd\nd\nd\nq\n")
        self.assertIn("Score: 1\n", output)
        self.assertIn("|     ooo@   |\n", output)

    def test_immutable_error_example(self) -> None:
        with self.assertRaises(NoURuntimeError) as ctx:
            run_file(EXAMPLES / "04-immutable-error.nou")
        self.assertIn("immutable", ctx.exception.diagnostic.message)
        self.assertEqual(ctx.exception.diagnostic.line, 3)

    def test_examples_parse_under_check(self) -> None:
        for path in sorted(EXAMPLES.glob("*.nou")):
            with self.subTest(example=path.name):
                parse_source(decode_source(path.read_bytes(), str(path)), str(path))


class CliTests(unittest.TestCase):
    """Drive the actual CLI as a subprocess for run/check/tokens/ast/repl."""

    ROOT = str(EXAMPLES.parent)

    def _cli(self, *args: str, stdin: str = "") -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "nou", *args],
            capture_output=True,
            text=True,
            input=stdin,
            cwd=self.ROOT,
        )

    def test_run(self) -> None:
        proc = self._cli("run", "examples/01-hello.nou")
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, "Hello, World!\n")

    def test_run_error_exit_code_and_diagnostic(self) -> None:
        proc = self._cli("run", "examples/04-immutable-error.nou")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("RuntimeError", proc.stderr)
        self.assertIn("04-immutable-error.nou:3", proc.stderr)

    def test_check(self) -> None:
        proc = self._cli("check", "examples/06-while.nou")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("OK", proc.stdout)

    def test_tokens_show_escaped_whitespace(self) -> None:
        proc = self._cli("tokens", "examples/01-hello.nou", "--show-whitespace")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("no<TAB>u", proc.stdout)
        self.assertIn("name=<TAB>", proc.stdout)

    def test_ast(self) -> None:
        proc = self._cli("ast", "examples/05-conditional.nou")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("Conditional", proc.stdout)

    def test_step_limit_option(self) -> None:
        proc = self._cli("run", "examples/06-while.nou", "--step-limit", "5")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("step limit", proc.stderr)

    def test_trace_goes_to_stderr(self) -> None:
        proc = self._cli("run", "examples/02-add.nou", "--trace")
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, "3\n")
        self.assertIn("[trace]", proc.stderr)
        self.assertIn("phase", proc.stderr)

    def test_repl_basic(self) -> None:
        proc = self._cli("repl", stdin="!1!, !2!, nooo u\n")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("=> 3", proc.stdout)

    def test_repl_reports_errors_and_continues(self) -> None:
        proc = self._cli("repl", stdin="nooo u\n!5!\n")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("stack underflow", proc.stderr)
        self.assertIn("=> 5", proc.stdout)

    def test_determinism_across_runs(self) -> None:
        a = self._cli("run", "examples/11-phases.nou")
        b = self._cli("run", "examples/11-phases.nou")
        self.assertEqual(a.stdout, b.stdout)
        self.assertEqual(a.stdout, EXPECTED["11-phases.nou"])


if __name__ == "__main__":
    unittest.main()
