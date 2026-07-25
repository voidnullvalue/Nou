# No U — Whitespace Semantics

Whitespace is the load-bearing wall of No U. This document catalogs every
place it matters. Markers: `·` is a space, `→` is a tab (documentation
rendering only; source files contain the real characters).

## The four whitespace roles

1. **Leading tabs** — lexical block depth.
2. **Leading spaces (after the tabs)** — execution phase.
3. **Operator-internal whitespace** — variable identity.
4. **Trailing whitespace** — statement modifier.

The same physical character means completely different things in each
position. This is intentional.

## 1. Leading tabs: lexical depth

```text
no→u, !"outer"!, No, No, No, No, No, NOOOOOO UUUUUUUU
→no→u, !"inner"!, No, No, No, No, No, NOOOOOO UUUUUUUU
```

The tab-indented line forms a nested block attached to the line above it.
Rules:

- Indentation is `TAB* SPACE*`. A tab after a leading space is an
  `IndentationError` at the exact column.
- Depth may increase only by exactly one tab at a time.
- A nested block may not be the first thing in its enclosing block.
- Tab display width is irrelevant; one tab is one level.

Each block executes in its own frame: fresh stack, fresh current value,
fresh binding table, chained to the parent frame for name lookup.

## 2. Leading spaces: execution phase

Within one block, statements are grouped by space depth and the groups run
in ascending order; source order applies within a group.

```text
··no→u, !"runs third"!, No, No, No, No, No, NOOOOOO UUUUUUUU
no→u, !"runs first"!, No, No, No, No, No, NOOOOOO UUUUUUUU
·no→u, !"runs second"!, No, No, No, No, No, NOOOOOO UUUUUUUU
```

Phases are block-local: a function body or nested block has its own phase
sequence. Delayed assignments (`No` / `··U`) scheduled during a phase are
applied, in source order, when that phase's statements finish.

## 3. Operator-internal whitespace: variable identity

The whitespace between `no`/`NO` and `u`/`U` *is* the variable name —
exact count, kind, and order:

```text
no·u        loads <SP>
no··u       loads <SP><SP>
no→u        loads <TAB>            (the print builtin)
no·→u       loads <SP><TAB>        (distinct from <TAB><SP>!)
NO·u        stores <SP> mutably
NO·U        stores <SP> immutably
```

Internal whitespace may mix tabs and spaces in any order — the
tabs-before-spaces rule constrains only indentation. Diagnostics, `tokens`
output, and traces always show the escaped form (`no<SP><TAB>u`) so two
identical-looking spellings can be told apart.

Reserved conventions:

- One to five spaces: function parameters (in a function frame).
- Two spaces: the target of delayed assignment.
- One to seven tabs: the standard library (immutable, in the root frame).

## 4. Trailing whitespace: statement modifiers

Measured at the absolute end of the line, after all code and comments:

```text
!5!         push 5
!5!·        return 5 from this block, immediately
!5!··       push 5, then un-push it (value suppressed)
!5!→        push false (5 negated by truthiness)
```

Errors: three or more trailing spaces, two or more trailing tabs, or any
mix of trailing spaces and tabs.

Notes:

- Suppression also restores the current value to what it was before the
  statement. `!··` is therefore a pure "drop one".
- Return abandons remaining statements, later phases, and unapplied
  deferred assignments of the block being returned from.
- The delayed-assignment pair (`No` / `··U`) forbids trailing modifiers on
  both of its lines.

## Blank and whitespace-only lines

- Completely empty lines execute nothing and are ignored — except that any
  physical line between `No` and `··U` (empty ones included) prevents the
  delayed-assignment pairing.
- Whitespace-only lines are significant to the extent that they are
  validated (indentation legality, homoglyph checks) and reported by
  `tokens`; they also break the `No`/`··U` pairing. They execute nothing.
- A final newline never changes behavior. Trailing whitespace is never
  stripped by any tool in this repository.

## The `··U` line

The second line of the delayed-assignment construct has indentation
coordinates like any line (its two extra spaces put it two phases deeper),
but it is consumed syntactically by the construct: the pair is one
statement at the `No` line's coordinates. A `U` line anywhere else is a
syntax error with a pointer at the `U`.

## Seeing what you wrote

```text
python -m nou tokens program.nou --show-whitespace
```

renders every line with `→`/`·` markers and prints each token in escaped
form, exact spans included. Error excerpts use the same rendering:

```text
SyntaxError: unrecognized operator (recognized token: nooo<SP><SP>u)
  --> program.nou:2:1
   |
 2 | nooo··u
   | ^~~~~~~
```
