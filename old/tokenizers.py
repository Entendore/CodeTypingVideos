"""
Syntax-highlighting tokenizers.

Each tokenizer compiles a single master regex on first use (thread-safe,
double-checked locking) and returns ``(token_type, token_text)`` tuples
that the renderer maps to theme colors.

Languages supported:
  - Python
  - JavaScript / TypeScript (shared)
  - C / C++ / Java
  - Go
  - Rust
"""

from __future__ import annotations

import re
import threading
from typing import List, Tuple, Type


class BaseTokenizer:
    """Base class with lazy, thread-safe regex compilation."""

    _PATTERNS: List[Tuple[str, str]] = []
    _COMPILED: re.Pattern | None = None
    _LOCK = threading.Lock()

    @classmethod
    def _compile(cls) -> re.Pattern:
        if cls._COMPILED is None:
            with cls._LOCK:
                if cls._COMPILED is None:
                    pat = "|".join(f"(?P<{n}>{p})" for n, p in cls._PATTERNS)
                    cls._COMPILED = re.compile(pat, re.MULTILINE | re.DOTALL)
        return cls._COMPILED

    @classmethod
    def tokenize(cls, text: str) -> List[Tuple[str, str]]:
        """Return list of (token_type, token_text) for the given source."""
        compiled = cls._COMPILED
        if compiled is None:
            compiled = cls._compile()
        return [(m.lastgroup, m.group()) for m in compiled.finditer(text)]


class PythonTokenizer(BaseTokenizer):
    KEYWORDS = {
        "def", "class", "if", "elif", "else", "for", "while", "return",
        "import", "from", "as", "try", "except", "finally", "with",
        "raise", "pass", "break", "continue", "and", "or", "not",
        "in", "is", "lambda", "yield", "global", "nonlocal", "assert",
        "del", "async", "await", "True", "False", "None",
    }
    BUILTINS = {
        "print", "len", "range", "int", "str", "float", "list", "dict",
        "set", "tuple", "type", "isinstance", "enumerate", "zip", "map",
        "filter", "sorted", "reversed", "any", "all", "min", "max", "sum",
        "abs", "round", "input", "open", "super", "property", "staticmethod",
        "classmethod", "hasattr", "getattr", "setattr", "delattr",
        "object", "Exception", "ValueError", "TypeError", "KeyError",
        "IndexError", "AttributeError", "RuntimeError", "self", "cls",
    }
    _PATTERNS = [
        ("comment",       r"#[^\n]*"),
        ("triple_string", r'"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\''),
        ("string",        r'"[^"\\]*(?:\\.[^"\\]*)*"|\'[^\'\\]*(?:\\.[^\'\\]*)*\''),
        ("decorator",     r"@\w+"),
        ("number",        r"\b\d+\.?\d*(?:e[+-]?\d+)?\b|0[xXoObB][0-9a-fA-F]+\b"),
        ("keyword",       r"\b(?:" + "|".join(KEYWORDS) + r")\b"),
        ("builtin",       r"\b(?:" + "|".join(BUILTINS) + r")\b"),
        ("function",      r"\b([a-zA-Z_]\w*)\s*(?=\()"),
        ("identifier",    r"\b[a-zA-Z_]\w*\b"),
        ("operator",      r"[+\-*/%=<>!&|^~]+"),
        ("bracket",       r"[(){}[\]]"),
        ("punctuation",   r"[;:,.]"),
        ("whitespace",    r"\s+"),
        ("other",         r"."),
    ]


class JSTokenizer(BaseTokenizer):
    """Tokenizer for JavaScript and TypeScript (TS keywords merged in)."""
    KEYWORDS = {
        "var", "let", "const", "if", "else", "for", "while", "do",
        "switch", "case", "break", "continue", "function", "return",
        "class", "new", "this", "super", "extends", "import", "export",
        "from", "default", "try", "catch", "finally", "throw", "typeof",
        "instanceof", "in", "of", "async", "await", "yield", "true",
        "false", "null", "undefined", "void", "delete",  # TS extras
        "interface", "type", "enum", "implements", "namespace",
        "public", "private", "protected", "readonly", "abstract",
        "as", "is", "number", "string", "boolean", "any", "unknown",
        "never",
    }
    BUILTINS = {
        "console", "document", "window", "Math", "Array", "Object",
        "String", "Number", "Boolean", "Promise", "Symbol", "Map", "Set",
        "Date", "RegExp", "Error", "JSON", "parseInt", "parseFloat",
        "isNaN", "isFinite", "require", "module", "process",
    }
    _PATTERNS = [
        ("comment",     r"//[^\n]*|/\*[\s\S]*?\*/"),
        ("string",      r'"[^"\\]*(?:\\.[^"\\]*)*"|\'[^\'\\]*(?:\\.[^\'\\]*)*\'|`[^`\\]*(?:\\.[^`\\]*)*`'),
        ("number",      r"\b\d+\.?\d*(?:e[+-]?\d+)?\b|0x[0-9a-fA-F]+\b"),
        ("keyword",     r"\b(?:" + "|".join(KEYWORDS) + r")\b"),
        ("builtin",     r"\b(?:" + "|".join(BUILTINS) + r")\b"),
        ("function",    r"\b([a-zA-Z_]\w*)\s*(?=\()"),
        ("identifier",  r"\b[a-zA-Z_]\w*\b"),
        ("operator",    r"[+\-*/%=<>!&|^~?]+"),
        ("bracket",     r"[(){}[\]]"),
        ("punctuation", r"[;:,.]"),
        ("whitespace",  r"\s+"),
        ("other",       r"."),
    ]


class GenericCTokenizer(BaseTokenizer):
    """Shared tokenizer for C, C++, Java, C#."""
    KEYWORDS = {
        "int", "float", "double", "char", "void", "if", "else", "for",
        "while", "do", "switch", "case", "break", "continue", "return",
        "struct", "typedef", "enum", "union", "const", "static", "extern",
        "unsigned", "signed", "long", "short", "class", "public", "private",
        "protected", "virtual", "override", "namespace", "using", "new",
        "delete", "try", "catch", "throw", "true", "false", "null",
        "auto", "nullptr", "template", "typename",
    }
    BUILTINS = {
        "printf", "scanf", "malloc", "free", "sizeof", "strlen", "std",
        "cout", "cin", "endl", "string", "vector", "map", "set",
    }
    _PATTERNS = [
        ("comment",     r"//[^\n]*|/\*[\s\S]*?\*/"),
        ("string",      r'"[^"\\]*(?:\\.[^"\\]*)*"|\'[^\'\\]*(?:\\.[^\'\\]*)*\''),
        ("number",      r"\b\d+\.?\d*(?:e[+-]?\d+)?\b|0x[0-9a-fA-F]+\b"),
        ("keyword",     r"\b(?:" + "|".join(KEYWORDS) + r")\b"),
        ("builtin",     r"\b(?:" + "|".join(BUILTINS) + r")\b"),
        ("function",    r"\b([a-zA-Z_]\w*)\s*(?=\()"),
        ("identifier",  r"\b[a-zA-Z_]\w*\b"),
        ("operator",    r"[+\-*/%=<>!&|^~]+"),
        ("bracket",     r"[(){}[\]]"),
        ("punctuation", r"[;:,.]"),
        ("whitespace",  r"\s+"),
        ("other",       r"."),
    ]


class GoTokenizer(BaseTokenizer):
    KEYWORDS = {
        "break", "case", "chan", "const", "continue", "default", "defer",
        "else", "fallthrough", "for", "func", "go", "goto", "if", "import",
        "interface", "map", "package", "range", "return", "select",
        "struct", "switch", "type", "var", "nil", "true", "false", "iota",
    }
    BUILTINS = {
        "fmt", "os", "io", "strings", "strconv", "math", "time", "len",
        "cap", "make", "new", "append", "copy", "delete", "panic",
        "recover", "print", "println",
    }
    _PATTERNS = [
        ("comment",     r"//[^\n]*|/\*[\s\S]*?\*/"),
        ("string",      r'"[^"\\]*(?:\\.[^"\\]*)*"|\'[^\'\\]*(?:\\.[^\'\\]*)*\'|`[^`]*`'),
        ("number",      r"\b\d+\.?\d*(?:e[+-]?\d+)?\b|0x[0-9a-fA-F]+\b"),
        ("keyword",     r"\b(?:" + "|".join(KEYWORDS) + r")\b"),
        ("builtin",     r"\b(?:" + "|".join(BUILTINS) + r")\b"),
        ("function",    r"\b([a-zA-Z_]\w*)\s*(?=\()"),
        ("identifier",  r"\b[a-zA-Z_]\w*\b"),
        ("operator",    r"[+\-*/%=<>!&|^~]+"),
        ("bracket",     r"[(){}[\]]"),
        ("punctuation", r"[;:,.]"),
        ("whitespace",  r"\s+"),
        ("other",       r"."),
    ]


class RustTokenizer(BaseTokenizer):
    KEYWORDS = {
        "fn", "let", "mut", "const", "static", "if", "else", "for",
        "while", "loop", "match", "return", "break", "continue", "in",
        "as", "use", "mod", "pub", "struct", "enum", "trait", "impl",
        "where", "self", "Self", "super", "crate", "extern", "ref",
        "move", "async", "await", "dyn", "unsafe", "true", "false",
    }
    BUILTINS = {
        "println", "print", "format", "vec", "String", "Vec", "Option",
        "Result", "Box", "Rc", "Arc", "Some", "None", "Ok", "Err",
        "HashMap", "BTreeMap", "HashSet",
    }
    _PATTERNS = [
        ("comment",     r"//[^\n]*|/\*[\s\S]*?\*/"),
        ("string",      r'"[^"\\]*(?:\\.[^"\\]*)*"|\'[^\'\\]*(?:\\.[^\'\\]*)*\''),
        ("number",      r"\b\d+\.?\d*(?:e[+-]?\d+)?\b|0x[0-9a-fA-F]+\b"),
        ("keyword",     r"\b(?:" + "|".join(KEYWORDS) + r")\b"),
        ("builtin",     r"\b(?:" + "|".join(BUILTINS) + r")\b"),
        ("function",    r"\b([a-zA-Z_]\w*)\s*(?=\()"),
        ("identifier",  r"\b[a-zA-Z_]\w*\b"),
        ("operator",    r"[+\-*/%=<>!&|^~?]+"),
        ("bracket",     r"[(){}[\]]"),
        ("punctuation", r"[;:,.]"),
        ("whitespace",  r"\s+"),
        ("other",       r"."),
    ]


# Map UI-friendly language names to tokenizer classes.
TOKENIZER_MAP: dict[str, Type[BaseTokenizer]] = {
    "Python": PythonTokenizer,
    "JavaScript": JSTokenizer,
    "TypeScript": JSTokenizer,
    "C/C++/Java": GenericCTokenizer,
    "Go": GoTokenizer,
    "Rust": RustTokenizer,
}
