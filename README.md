# No U

An esoteric programming language that is deliberately irritating,
whitespace-sensitive, and visually ambiguous — while remaining
deterministic, documented, tested, and genuinely usable.

```text
no→u, !"Hello, World!"!, No, No, No, No, No, NOOOOOO UUUUUUUU
```

(`→` renders a tab; the real file contains a real tab. That line loads the
`print` builtin from the `<TAB>` binding, pushes a string and five padding
nulls, and calls it with the six-argument invocation operator.)

## The pitch, such as it is

- The entire operator vocabulary is variations of "no u":
  `no`, `NO`, `No`, `u`, `nou`, `no u`, `NO U`, `NO u`, `nooo u`,
  `nooooo uuuuuu`, `NOOOOOO UUUUUUUU`, `!`, and the two-line `No` / `  U`.
- Variables are named by the **exact whitespace** between `no` and `u`.
  `no u`, `no  u`, and `no→u` are three different variables.
- Leading **tabs** are lexical block depth; leading **spaces** are
  execution *phase* — statements run in ascending phase order regardless
  of source order.
- Trailing whitespace changes statement behavior: one space returns, two
  spaces suppress, one tab negates. Three is a syntax error, obviously.
- It is still deterministic, ships a real test suite (157 tests), exact
  diagnostics with visible-whitespace excerpts, a tracer, and a REPL.

See [docs/language-reference.md](docs/language-reference.md) and
[docs/whitespace.md](docs/whitespace.md).

## Requirements

Python 3.12+. Standard library only.

## Usage

From a checkout:

```bash
python -m nou run    examples/01-hello.nou
python -m nou run    examples/14-snake.nou --step-limit 100000000
python -m nou check  examples/06-while.nou
python -m nou tokens examples/01-hello.nou --show-whitespace
python -m nou ast    examples/05-conditional.nou
python -m nou repl
```

Options: `--step-limit NUMBER` (default 1,000,000 operations) and
`--trace` (statements, stacks, bindings, phases, and depth to stderr).

Installed as a package (`pip install .`), the same commands are available
as `nou run …`, `nou repl`, etc.

## A taste

Counting down (`examples/06-while.nou`; `·` marks the significant trailing
space that returns the body's value — which becomes the next loop
condition):

```text
!3!, NO u
no u
NO u !
→no→u, no u, No, No, No, No, No, NOOOOOO UUUUUUUU
→no u, !-1!, nooo u, NO u·
```

```text
$ python -m nou run examples/06-while.nou
3
2
1
```

Diagnostics render whitespace so you can see what you actually typed:

```text
IndentationError: tab appears after indentation space
  --> example.nou:4:3
   |
 4 | ··→no·u
   |   ^ tabs may not follow leading spaces
```

## Examples

Fourteen verified programs live in [examples/](examples/). The shorter
programs cover every operator, phases vs. blocks, delayed assignment,
trailing-whitespace modifiers, and deliberate diagnostics. The 464-line
Snake program demonstrates closure-encoded linked structures, traversal,
collision detection, board rendering, growth, wrapping, scoring, and input
without adding any operators or builtins.

## Development

```bash
python -m unittest discover -s tests
```

Project layout:

```text
nou/            lexer, parser, AST, runtime, values, stdlib, diagnostics, CLI
tests/          lexer / parser / runtime / end-to-end suites (unittest)
examples/       runnable .nou programs (real tabs, real trailing spaces)
docs/           language reference and whitespace semantics
```

Editor warning: this repository contains files where trailing whitespace
and tab/space distinctions are semantically load-bearing. Disable
"trim trailing whitespace on save" before touching `examples/` or the
test fixtures, and no, your formatter is not welcome here.
