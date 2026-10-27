---
date: 2026-10-28
topic: closure ownership, lifetime safety, and reclamation
status: implemented-phase-2
---

# Vanta Closure Ownership — Design

## 1. Problem summary

The previous arena-based implementation allocated each closure environment
and mutable capture cell from a *static* bump arena created once per
`__make_closure_N` helper (and once per mutable captured variable). Those
arenas were never reset, so environments were unreachable-but-never-freed
and a literal's 1MB arena was permanently retained. Empirically 200,000
closures exhausted a literal's 1MB arena (`vanta: arena out of memory`).

Escaping `Str` captures worked because `Str` is itself refcounted and is
embedded by value in the environment, but environments were never destroyed
so Str backgrounds leaked too. Escaping `List<T>` captures could *crash*,
because each `List<T>` is an arena handle `{arena *, hdr *}`; when the
originating stack `Arena` (the `let a = ...`) was destroyed at scope
exit, the handle dangled.

No closures are destroyed (raw `Closure__N *`), so there is no ownership
contract at all, making reclamation or safe sharing impossible.

## 2. Scope and non-goals

In scope:
- Heap-allocated, reference-counted closure environments.
- Shared, reference-counted mutable capture cells.
- `Str` captures retain/reference correctly through env lifetime.
- `List<T>` escapes have fully-correct backing-storage lifetime.
- Non-capturing lambdas unchanged.

Out of scope (documented limitations):
- General cycle collection. Closure environments *can* be forced into cycles
  by capturing a mutable binding that holds another closure, but the runtime
  keeps refcount-only ownership; such cycles leak. Detected and documented.
- Hot-reload of closure environments is not exercised by this design beyond
  the existing "environments live outside any arena now" guarantee.

## 3. Ownership model

### 3.1 Arena becomes reference-counted

`vanta::Arena` gains an intrusive `refs_` counter. It is still non-copyable
at the C++ level (copy/assignment/move stay deleted) but gains:

    retain(Arena* a)  // ++refs
    release(Arena* a) // if (--refs==0) reset()+free (owned) or releaseShared_

Construction seeds `refs_=1`. The destructor calls `release()` only.
`list_new` retains the owning Arena so every List handle owns one share.

This makes **List<T> captures safe** — the handle's arena outlives the closure.

### 3.2 List<T> gains rule-of-five RAII

`List<T>` gets user-provided destructor (release arena), copy constructor
(+arena retain), move constructor (`h=nullptr`), and copy/move assignment.
No behavioural change (shallow aliasing retained); the lifetime gain is
automatic lifetime tracking for every List copy.

### 3.3 Closure environment is a heap-owned, refcounted object

Struct layout gains a leading `uint32_t v_refs` field:

    struct Closure__N {
        uint32_t v_refs;
        FnPtr1  v_invoke;
        /* captures */
    };

`__make_closure__N(...)`:

    auto* __c = static_cast<Closure__N*>(std::malloc(sizeof(Closure__N)));
    __c->v_refs = 1;
    __c->v_invoke = &vanta_user::fn_fn_closure__N;
    /* __c->cap = cap; (copies retain automatically for Str/List) */

A generated `__destroy_closure__N(c)` tears down non-trivial captured
fields and frees `c` after `freeCell`-style cleanup:
    - for a captured `Str` field: (dtor runs before free if placement-deleted)
    - for a captured mutable cell (`T*`, refcounted): cell.release()
    - for a captured `List<T>`: destructor field runs (releases arena)
    - primitives: nothing

Both `malloc`/`delete` would mix non-trivial types; we use manual
destruction in `__destroy_closure__N` (`obj.~T()` then `std::free`) so
RAII classes (Str/List) release and C++ constructors/destructors only run
once.

### 3.4 Closure values are RAII (`vanta::ClosureHandle<T>`)

    template<class T> struct ClosureHandle {
        T* p;
        ClosureHandle() noexcept : p(nullptr) {}
        explicit ClosureHandle(T* q) noexcept : p(q) {}  // consumes 1 owned ref
        ~ClosureHandle() { release(); }
        ClosureHandle(const ClosureHandle& o) : p(o.p) { if (p) vanta::closure_retain(p); }
        ClosureHandle(ClosureHandle&& o) noexcept : p(o.p) { o.p=nullptr; }
        ClosureHandle& operator=(const ClosureHandle& o) { if(p!=o.p){release(); p=o.p; if(p)vanta::closure_retain(p);} return *this; }
        ClosureHandle& operator=(ClosureHandle&& o) noexcept { if(p!=o.p){release(); p=o.p;} o.p=nullptr; return *this; }
        void release() { if(p){vanta::closure_release(p,&amp;__destroy_closure<T>); p=nullptr;} }
        T* get() const { return p; }
        explicit operator bool() const { return p != nullptr; }
        // invoke-X guard tested via get()
    };

The generated C++ for a closure-typed Vanta variable is a
`ClosureHandle<Closure__N>` rather than a raw pointer. This collapses
every scope (function, block, loop, branch) and return path to a
single destructor at ordinary block scope exit, eliminating manual
emit-current-repeated release bookkeeping.

    vanta::closure_retain(p)  = ++p->v_refs
    vanta::closure_release(p, destroy) :
        if (--p->v_refs == 0) { destroy(p); std::free(p); }

### 3.5 Mutable capture cells

A `mut`-qualified local that is captured gets a heap-allocated cell
holding one value of its (possibly mutably-linked) type:

    template<class T> struct CaptureCell { T value; uint32_t refs; ... };
    // retain/release/free semantics

Each capturing closure receives an **owned reference**, i.e. `retain()`.
The enclosing function's local cell reference releases on scope exit, but
live closures still own theirs, so the shared binding survives function
returns correctly.

Container-capture aliasing: two closures capturing the same `mut count = 0`
share one cell pointer, so writes via `*cell` are observable through the
other closure.

### 3.6 Captured typed fields

Every captured name results in a corresponding env field. Its
copy/teardown rules derive from the C++ type:
- `Str`: field destroys via `Str::~Str` ⇒ Str buffer released.
- `List<T>`: field uses rule-of-five ⇒ arena released when env freed.
- primitive/pointer: nothing.
- Another `Closure__M` (nested): field is a `ClosureHandle` whose release
  ensures nested environment is destroyed, producing chained teardown.
- mutable cell pointer: `cell.release()`.

### 3.7 Globals and stored closures

A `let`/`mut` global of closure type would be stored in the
state-segment-backed global cell. Given Vanta's current limitations, we
allow locals and function returns; globals holding closures are unusual.
If used, the global holds a `ClosureHandle` and the destructor runs only
on process exit (leak acceptable). Documented.

### 3.8 Hot reload interaction

Environments are now heap-owned; arena resets cannot invalidate them.
Mutable cells are heap-owned too. Only `Str`/`List` backing (heap arenas for
List now refcounted) survives reload as before. No additional allocator
reset issue.

### 3.9 Cycles

Vanta can express potential cycles via mutable capture cells containing
closure pointers (mut binding of closure type, captured by another
closure). Reference counting preserves those cycles → leak. This Phase 2
policy documents rather than fixes: ordinary non-cycle closures reclaim
deterministically; cyclic ownership leaks and is outside the supported
reclamation contract. A future marker-root / weak-edge recommendation is
given at the end of the user docs.

### 3.10 Compiler coverage

`TypeChecker._is_constexpr` etc. unchanged. Changes confined to:
- `compiler/codegen_cpp.py`: __make_closure_N (alloc place new), capture cells,
  `__destroy_closure_N`; VarDecl/Assign/Return/lambda emit typed RAII handle.
- `runtime/vanta_runtime.hpp`: Arena refs, List rule of five,
  CaptureCell, closure_retain/release, closure handle templates, helper macros.

## 4. Ordering

Steps 3 through 8 as described in the binding playbook — implemented now
incrementally with TDD gates.
---
