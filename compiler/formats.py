"""Format-string parsing shared by the type checker and the C++ code generator.

The format mini-language is deliberately tiny:

    {}        consumes one argument
    {{        a literal '{'
    }}        a literal '}'

Anything else is copied through verbatim. The format string must be a string
literal, because the placeholders are resolved at compile time: the type checker
counts them, and the code generator turns each one into a printf conversion
specifier chosen from the argument's type.
"""


def parse_format(fmt: str):
    """Return (pieces, count) for a format literal.

    ``pieces`` has ``count + 1`` entries: the literal text before the first
    placeholder, between placeholders, and after the last one. Chunks are
    already unescaped (``{{`` -> ``{``).

    Raises ValueError with a human-readable message on a lone brace.
    """
    pieces = []
    cur = []
    count = 0
    i = 0
    n = len(fmt)
    while i < n:
        c = fmt[i]
        if c == '{':
            if i + 1 < n and fmt[i + 1] == '{':
                cur.append('{')
                i += 2
                continue
            if i + 1 < n and fmt[i + 1] == '}':
                pieces.append(''.join(cur))
                cur = []
                count += 1
                i += 2
                continue
            raise ValueError("unmatched '{' (use '{{' for a literal brace)")
        if c == '}':
            if i + 1 < n and fmt[i + 1] == '}':
                cur.append('}')
                i += 2
                continue
            raise ValueError("unmatched '}' (use '}}' for a literal brace)")
        cur.append(c)
        i += 1
    pieces.append(''.join(cur))
    return pieces, count
