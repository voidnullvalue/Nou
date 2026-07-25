# No U — Language Reference

No U is a deliberately irritating, whitespace-sensitive, visually ambiguous
esoteric language. It is also deterministic: the same source bytes, standard
input, and arguments always produce the same behavior.

Throughout this document, `·` renders a space and `→` renders a tab. Real
programs contain real spaces and tabs; the markers are documentation only.

## Source rules

- Files are UTF-8. Invalid UTF-8 is rejected. No Unicode normalization is
  performed anywhere.
- LF and CRLF line endings are equivalent; a lone CR is an error. A final
  newline never changes behavior.
- Operators must use exact ASCII. Homoglyphs (Cyrillic `о`, Greek `υ`,
  fullwidth `！`, NBSP, …) in operator positions are rejected with a
  diagnostic naming the offending code point.
- Identifiers do not exist; variables are named by whitespace (below).
  String contents may contain any Unicode.

## Lines, indentation, and phases

Each physical line has two indentation coordinates: `(tab_depth, space_depth)`.
Indentation must be zero or more tabs followed by zero or more spaces. A tab
after a leading space is an `IndentationError`.

- **Leading tabs — lexical block depth.** A +1 tab increase opens a nested
  block attached to the immediately preceding statement. Jumps of more than
  +1 are errors. Dedenting closes blocks.
- **Leading spaces — execution phase.** At the end of parsing a block, its
  statements run grouped by ascending space depth; within a phase, in source
  order.

A tab-indented block after:

| Preceding line            | Meaning of the block            |
|---------------------------|---------------------------------|
| `nooooo uuuuuu`           | function body (required)        |
| `NO U !`                  | conditional body (required)     |
| `NO u !`                  | loop body (required)            |
| any other statement       | anonymous block, executed right after its anchor statement in the anchor's phase; its result is pushed in the parent |

Whitespace-only lines are validated (indentation legality) and appear in
`tokens` output, but execute nothing. Completely empty lines are ignored,
except that any physical line — including an empty one — between `No` and
`  U` prevents them from forming the delayed-assignment construct.

## Statements and expressions

One line is one statement. A statement is one or more expressions separated
by **mandatory** commas:

```text
!1!, !2!, nooo u
```

Expressions evaluate left to right. Whitespace around commas is
insignificant; whitespace *inside* an operator is part of the operator.

### Trailing whitespace

Whitespace at the very end of a line (after all code and comments) modifies
the statement:

| Trailing            | Effect |
|---------------------|--------|
| none                | normal execution |
| `·` (one space)     | **return** the statement's value from the current block immediately; remaining statements, later phases, and unapplied deferred assignments are abandoned |
| `··` (two spaces)   | **suppress** the value: its push is undone and the current value reverts to its pre-statement value |
| `→` (one tab)       | **negate** the value: replaced by the Boolean `not truthy(value)` |
| three or more spaces| syntax error |
| two or more tabs    | syntax error |
| mixed spaces/tabs   | syntax error |

`!··` (a negation with two trailing spaces) pops one value and discards the
result — the idiomatic "drop".

## Values

Null, Boolean, Integer (arbitrary precision), String, List, Function.

Truthiness: Null, `false`, `0`, `""`, and `[]` are falsy; everything else
(including functions) is truthy.

Equality (`!, !`) is structural and type-strict: `!1!` ≠ `!true!`,
`!0!` ≠ `!false!`; lists compare element-wise; functions compare by identity.

## Literals

Delimited by `!`:

```text
!null!   !true!   !false!   !123!   !-45!   !"hello"!   !"line\nbreak"!
```

An unquoted payload must be exactly `null`, `true`, `false`, or a base-10
integer matching `-?[0-9]+`. String escapes: `\n` `\r` `\t` `\\` `\"`
`\uXXXX`. A standalone `!` is the negation operator, never a literal
delimiter.

## Variables

A variable is named by the **exact whitespace** between `no` and `u` (or
`NO` and `U`/`u`): count, kind, and order of spaces and tabs all matter.
`no·u`, `no··u`, `no→u`, and `no·→u` are four different slots. Diagnostics
render names in escaped form: `no<SP><SP>u`, `<TAB>`.

Operator-internal whitespace may freely mix tabs and spaces — the
tabs-before-spaces rule applies only to leading indentation.

## Operator reference

Stack notation: `( before -- after )`, top of stack on the right. Every
expression also sets the block's *current value* to its result.

| Operator | Stack effect | Semantics |
|----------|--------------|-----------|
| `no` | `( -- true )` | push Boolean true |
| `NO` | `( -- false )` | push Boolean false |
| `No` | `( -- null )` | push Null (see delayed assignment) |
| `u` | `( -- current )` | push the block's current value (Null if none yet) |
| `nou` | `( f -- result )` | pop a callable, call it with zero arguments (missing parameters become Null), push its return value un-fanned |
| `no…u` (lowercase, internal ws) | `( -- value )` | load the variable named by the internal whitespace; unbound is a runtime error |
| `NO…U` | `( v -- v )` | pop, bind **immutably in the current block**, push back. Rebinding a name already bound in this block is a runtime error; shadowing outer bindings is allowed |
| `NO…u` | `( v -- v )` | pop, store **mutably**: updates the nearest enclosing binding of that name (error if it is immutable), else creates it in the current block; push back |
| `!` | `( v -- bool )` | logical negation by truthiness |
| `!, !` | `( a b -- bool )` | two consecutive bare `!` expressions fuse into structural equality (parse-time, greedy left-to-right) |
| `nooo u` | `( a b -- a+b )` | pop right then left; Integer+Integer, String+String, or List+List; anything else is a type error |
| `nooooo uuuuuu` | `( -- fn )` | define a function: 5 parameters (o-count), 6 declared local slots (u-count, recorded metadata); the following tab-indented block is the body; pushes the function |
| `NOOOOOO UUUUUUUU` | `( f a1 a2 a3 a4 a5 a6 -- o1 o2 o3 o4 o5 o6 o7 o8 )` | pop six arguments (a6 first), then the callable; call with a1..a6 in source order; push eight outputs, o1 first, **o8 ends on top** and becomes the current value |
| `No` + next line `··U` | `( -- )` | delayed assignment (below) |

Stack underflow anywhere is a runtime error stating what was needed and what
was present.

### Functions

`nooooo uuuuuu` has five parameters, bound in deterministic order to the
one-, two-, three-, four-, and five-space slots as mutable bindings in the
call frame. Missing arguments are Null; extra arguments are popped and
discarded. The function's return value is the value of a body statement
executed with one trailing space; otherwise Null. Functions close over their
defining frame (parameters shadow closure slots of the same names).

### Multiple outputs

`NOOOOOO UUUUUUUU` requests eight outputs:

- A **scalar** return becomes output 1, outputs 2–8 are Null.
- A **user function returning a list** fans out: the first eight elements
  become the outputs, padded with Null; elements beyond eight are discarded.
- A **builtin** result is always a single scalar output — even when it is a
  list (this is what lets `append` hand back a usable list; see
  `docs/design-decisions.md`).

All eight outputs are pushed in order; to reach output 1, drop the seven
values above it (three suppressed equalities `!, !··` and one suppressed
negation `!··`).

### Delayed assignment

A line whose sole content is `No`, when the **immediately next physical
line** is exactly the same leading tabs, the `No` line's space depth **plus
two** spaces, and `U`:

```text
No
··U
```

schedules a mutable assignment of the current value *at the time the `No`
line executes* to the canonical two-space binding (`<SP><SP>`). Scheduled
assignments apply in source order when the current phase's statements
finish. Neither line may carry trailing-whitespace modifiers. Any
intervening line (blank included) breaks the pair — the `No` becomes a
plain Null push and the `U` line becomes a "stray U" syntax error.

## Control flow

Because commas are mandatory, a line reading exactly `NO U !` or `NO u !`
(single spaces, a lone `!`, no comma) cannot be an expression list — these
are block headers.

### Conditional — `NO U !`

Pops one condition from the enclosing stack. If truthy, the body runs in a
child frame and the body's result is pushed in the parent (and becomes the
current value). If falsy, nothing is pushed and the current value becomes
Null.

### While loop — `NO u !`

Before **every** iteration, pops the condition from the enclosing stack
(underflow if absent). While truthy: the body runs in a child frame and its
result is pushed — feeding the next condition test. The idiomatic loop ends
its body with a trailing-space return of the next condition:

```text
!3!, NO u
no u
NO u !
→no→u, no u, No, No, No, No, No, NOOOOOO UUUUUUUU
→no u, !-1!, nooo u, NO u·
```

After the loop, the current value is Null. The interpreter enforces a step
limit (default 1,000,000 operations; `--step-limit` changes it).

## Comments

`no!` opens a comment anywhere outside a string; the first following `!no`
closes it. Comments do not nest; their contents are ignored entirely.
Same-line comments behave as separator whitespace and may appear before,
between, or after expressions. A comment that spans lines must occupy whole
lines: nothing but whitespace may precede its opener or follow its
terminator on those lines. Unterminated comments are syntax errors. Inside
string literals, `no!` and `!no` are plain text.

## Blocks, frames, and scope

Every executing block has its own operand stack, current value (initially
Null), bindings, and deferred-assignment queue. Child frames chain to their
parent (function frames chain to the defining frame). Loads walk the chain
outward; mutable stores update the nearest binding; immutable stores always
create locally. Builtins live in an immutable root frame.

## Standard library

Builtins are immutable root bindings with tab-based names:

| Binding | Name | Params | Behavior |
|---------|------|--------|----------|
| `<TAB>` | print | 1 | write the display form of the value plus `\n` to stdout; returns Null |
| `<TAB><TAB>` | read-line | 0 | read one line from stdin without its newline; Null at EOF |
| `<TAB><TAB><TAB>` | to-string | 1 | display form: `null`, `true`, `false`, decimal integers, strings verbatim, lists as `[1, "x"]` |
| `<TAB><TAB><TAB><TAB>` | to-int | 1 | integers pass through, `true`/`false` → 1/0, strings must match `-?[0-9]+` exactly |
| `<TAB><TAB><TAB><TAB><TAB>` | length | 1 | length of a string or list |
| `<TAB><TAB><TAB><TAB><TAB><TAB>` | make-list | 0 | a new empty list |
| `<TAB><TAB><TAB><TAB><TAB><TAB><TAB>` | append | 2 | a **new** list with the item appended; never mutates |

Call zero-parameter builtins with `nou`; call the rest with
`NOOOOOO UUUUUUUU` (extra arguments are discarded). Example — printing:

```text
no→u, !"Hello, World!"!, No, No, No, No, No, NOOOOOO UUUUUUUU
```

## Command-line interface

```text
python -m nou run     program.nou [--step-limit N] [--trace]
python -m nou check   program.nou
python -m nou tokens  program.nou [--show-whitespace]
python -m nou ast     program.nou
python -m nou repl    [--step-limit N] [--trace]
```

Installed as a package, the `nou` console script provides the same commands.
`--trace` writes each statement, the stack before and after, the current
value, bindings, phase, and lexical depth to stderr. Diagnostics carry exact
line/column spans and render whitespace visibly:

```text
IndentationError: tab appears after indentation space
  --> example.nou:4:3
   |
 4 | ··→no·u
   |   ^ tabs may not follow leading spaces
```

## Determinism

Behavior depends only on source bytes, stdin, and arguments — never on
timestamps, locale, terminal width, tab display width, hash randomization,
CPU count, or the working directory (beyond resolving supplied paths). All
observable orderings use ordered data structures.
