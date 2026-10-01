# Code standards

The baseline `refactor-ticket` refactors against, in three groups: **code smells**, which are local, **bad architecture**, which is structural, and **test rules**, which are report only. Every entry cites the section of Leif Lindbäck's *A First Course in Object-Oriented Development* it comes from, so a finding can be checked against the source.

## Gates

Apply these before judging any entry:

- **A rule the project doesn't have doesn't apply.** Skip it silently rather than inventing structure the codebase never chose. The architecture group is gated further, see its opening note.
- **Skip what a linter, typechecker, or compiler already enforces.**

**Reading this in a non-OO codebase.** The book is Java, so it says *class*. Read that as whatever the language groups behaviour and data into: a class, a module, a struct with its functions, a package. Read *method* as function. Cohesion, coupling, encapsulation, naming and duplication all apply unchanged to modules of pure functions. Entries that genuinely need classes are marked **(OO only)**; drop them elsewhere.

---

## Code smells

- **Meaningless name.** An identifier that doesn't say what it holds or does: `tmp`, `data`, `info`, `manager`, a bare letter. Rename it. `i`, `j`, `k` for loop counters and single-letter names that really are one letter, like an `x` coordinate, are fine. (6.4)
- **Numbered identifier.** `account1` and `account2`, where numbering stands in for saying what differs. Rename to `fromAccount` and `toAccount`. Long names are fine; a short name that lies is not. (6.4)
- **Anonymous value.** A literal with no explaining name, even one used once. `connect(10000)` tells the reader nothing. Name it as a constant, or extract a predicate whose name is the explanation: `if (c == 10)` becomes `if (isUnixEol(c))`. A name is compiler-checked, a comment isn't. (6.4)
- **Duplicated code.** The same statement or logic shape in more than one place. The target is that nothing is repeated anywhere. Extract it and call from both sites. Watch the subtle cases: a repeated index expression like `seq[1]` is duplication, and it's where off-by-ones hide. Duplicated doc comments count too. (6.4)
- **Long function.** Not a line count. The test is whether the name tells you everything needed to understand the body. A comment inside the body is direct evidence it doesn't. Extract a function with an explaining name. Call overhead is not a reason to avoid this. (6.4)
- **Large unit.** Again not line count, but cohesion: it knows or does things belonging to more than one abstraction. The cheapest tell is fields or values more closely related to each other than to the rest, often sharing a name suffix, like `startTime` and `endTime` wanting to be a `TimePeriod`. Split it, taking along any function that belongs to the extracted part. (6.4)
- **Long parameter list.** Too long is when encapsulation, cohesion or coupling would improve by shortening it, not at any fixed count. Three fixes: pass the whole object the caller is unpacking, group the parameters that always travel together into one type, or drop a parameter the callee can reach itself. (6.4)
- **Primitive obsession.** A primitive or string standing in for a domain concept: a long list of primitive fields, a value plus the function that only validates that value, an array whose positions mean different things, a string or int for a fixed set of outcomes. Give the concept a type. Validating in its constructor makes an invalid value unrepresentable; an enum turns a misspelling into a compile error. (6.4)
- **Unnecessary shared mutable state.** Global or static state that belongs to an instance or a parameter. A top-level pure function is not this smell. (5.4, 5.6)
- **Complicated flow control.** Two shapes. Deep nesting, where an `if` wraps a whole body and the reader carries the condition through everything below, fixed by guarding on the invalid case and returning early. And unnecessary flags, where a `found` boolean is set in a loop and returned after it, when the answer was already known. Return at the point you know. (6.4)
- **Feature envy.** A function that reaches into another unit's data more than its own. Move it onto the data it envies. (6.4)
- **Data clumps.** The same few fields or parameters keep travelling together. Bundle them into one type. (6.4)
- **Repeated switches.** The same `switch` or `if`-cascade on the same type recurs across the change. Replace with dispatch on the type, or one table both sites share. (6.4)
- **Message chains.** Long `a.b().c().d()` navigation the caller shouldn't depend on. Hide the walk behind one call on the first object. (5.2)
- **Middle man.** A unit that mostly just delegates onward. Cut it and call the real target. (5.2)
- **Missing or wrong doc comments.** Every public declaration needs one, covering parameters and return value. It says *what*, never *how*, so the implementation stays free to change. Getters and setters included, since a blanket rule means nothing gets missed. (6.3, 6.6)
- **Comments inside a body.** Needing one means the function is too long or does too much. Fix the code and delete the comment. (6.3)
- **Refused bequest. (OO only)** A subclass that ignores or overrides most of what it inherits. Drop the inheritance and use composition. (6.4)
- **Inheritance used for code reuse. (OO only)** Reuse is better served by holding a reference and calling the methods. Inheritance passes down the implementation, not just the contract, so a superclass change silently breaks the subclass. Composition is usually longer and less elegant, and it works. Inherit only to modify behaviour through an overridable step, or to supply a default implementation. (9.3)
- **Unsound hierarchy. (OO only)** Four conditions must all hold: every superclass member is meaningful in the subclass, the superclass is genuinely more general, the subclass genuinely more specialised, and the is-a reads true. They're necessary, not sufficient. Hierarchies suit invented abstractions, like `List`/`AbstractList`/`ArrayList`, and fail on real-world entities, which refuse to be a tree. (9.3)

---

## Bad architecture

**The layer rules below apply only if the codebase already has layers**, meaning directories or packages that separate UI, application logic, domain and data access, whatever they're named. If it doesn't, skip every entry marked **(layered)** rather than proposing a restructure. Proposing an architecture is not a refactor. The unmarked entries apply everywhere.

- **Low cohesion.** A unit whose knowledge and tasks don't belong to one abstraction, or whose name doesn't identify what it is. Split it so each unit represents one thing. This applies at every size: function, type, module, package. Cohesion is the main test for whether a unit is too big, and low cohesion usually means a type is missing rather than that one is too long. (5.2)
- **Unnecessary coupling.** A dependency that isn't needed. What matters is how many, not what kind. The classic case is a shortcut reference to something already reachable through an existing path. Delete it. (5.2)
- **Spider in the web.** One unit holding references to many peripheral units that reference almost nothing themselves. The spider gets pulled into every operation and grows messy, the peripherals decay into empty data bags. Move associations outward so peripherals reference each other. This can lower coupling without changing the total number of references. (5.2, 5.6)
- **Leaky public interface.** Anything exported that no outside caller uses. The public interface is everything that breaks callers when changed: name, parameters, return type, and the thrown-exception list. Narrow it. In OO, `protected` counts as public interface, not implementation. (5.2)
- **Exposed internal state.** Mutable fields reachable and writable from outside the unit that owns them. Make them private and expose only the operation actually needed. (5.2)
- **I/O outside the presentation layer. (layered)** Console reads and writes, or UI calls, in application logic, domain or data access. Return the value upward and render it at the edge. (5.6)
- **Storage access in the domain. (layered)** Database or external-system calls in the layer that holds business rules. Move them into the integration layer and call that. (5.6)
- **Business rules in the integration layer. (layered)** That layer exists to call external systems and nothing else. Move the rule back to the domain. (5.6)
- **Upward dependency. (layered)** A lower layer calling a higher one. Execution flows down from the user, so the reverse dependency is never forced and is pure added coupling. (5.3)
- **Presentation reaching past the controller. (layered)** The UI holding a reference into the domain. Data should arrive as return values from the layer below it. Adding getters to the domain for the UI to poll bloats the controller and is the wrong fix. (5.3)
- **Error text built in a lower layer. (layered)** A low-level message surfaced verbatim to the user. It's unfriendly, and database detail leaked to users is a security problem. Build user-facing text at the edge; use the underlying message as diagnostic input only. (8.2)
- **Mutable data-transfer type. (layered)** A type that exists only to carry data between layers should be immutable, read-only, and named for that role. A setter or a business method on it means either the name or the setter is wrong. (5.3)
- **Errors reported by return value.** A return value carrying both a result and an error signal has low cohesion by construction, and no detail rides along with it. Use the language's error mechanism. (8.2)
- **Errors used for normal flow.** Needing to catch on a successful path means the interface is wrong. Fix the interface. (8.2)
- **Wrong error abstraction level.** A low-level error travelling up through many layers. Catch it and raise a more generic one, keeping the original as the cause. Catching a storage error at the UI creates a dependency across the whole stack. (8.2)
- **Catch-and-rethrow.** Catching only to raise the same thing again. Let it propagate. This is the standard overcorrection of the rule above, so check for it right after applying that one. (8.4)
- **Swallowed error.** An empty catch block. Execution continues as if nothing happened and the behaviour becomes unexplainable. (8.2)
- **State changed on failure.** After a failed operation the object must hold exactly the state it had before the call. Prefer immutability, then validating before mutating, then rollback. Storing a mutable argument without copying defeats immutability. (8.2)
- **Scattered error handling.** Near-identical handling copied across many catch sites. One component builds user messages, one writes the log. Business-rule violations are normal flow and don't belong in the log; everything else does. (8.2)
- **Missing failure handling.** Unvalidated parameters and unhandled failure paths. A passing happy path proves nothing here. (8.4)
- **Wrong error category. (OO only)** In languages with both, checked errors are for business-rule violations a caller can recover from, unchecked for programming bugs. Name the type after the condition. (8.2)

---

## Test rules, report only

Report these and leave them.

- **Too few tests.** Every branch uncovered, and boundary and illegal values untested: null, zero, negative, wrong type. (7.5)
- **Too many assertions in one test.** Execution stops at the first failure, so the rest never run. Prefer one per test. (7.5)
- **Not self-evaluating.** Results checked with conditionals, or by making a human read output. (7.5)
- **Test writes to standard output.** (7.5)
- **Design worsened for testability.** Visibility widened or a seam added purely so a test can reach something. (7.5)
- **Bug fixed with no test.** Every fix in the diff should arrive with a test that fails without it. (7.2)
- **Test deleted.** Disable it instead. (7.2)

Trivial accessors and private functions need no direct test. Not a finding.
