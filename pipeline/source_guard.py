from __future__ import annotations

import ast
import hashlib
import tokenize
from difflib import SequenceMatcher
from io import StringIO


def _tokens(
    source: str,
) -> list[str]:

    result: list[str] = []

    try:
        stream = StringIO(
            source
        ).readline

        for token in tokenize.generate_tokens(
            stream
        ):

            if token.type in {
                tokenize.ENCODING,
                tokenize.ENDMARKER,
                tokenize.NL,
                tokenize.NEWLINE,
                tokenize.INDENT,
                tokenize.DEDENT,
                tokenize.COMMENT,
            }:
                continue

            result.append(token.string)

    except (
        tokenize.TokenError,
        IndentationError,
    ):
        return []

    return result


def _ast_structure(
    source: str,
) -> list[str]:

    tree = ast.parse(source)

    return [
        type(node).__name__
        for node in ast.walk(tree)
    ]


def _similarity(
    a: list[str],
    b: list[str],
) -> float:

    if not a and not b:
        return 1.0

    if not a or not b:
        return 0.0

    return SequenceMatcher(
        None,
        a,
        b,
        autojunk=False,
    ).ratio()


def source_change_guard(
    original_source: str,
    generated_source: str,
    minimum_token_similarity: float = 0.55,
    minimum_ast_similarity: float = 0.70,
) -> dict:

    if not original_source.strip():
        return {
            "accepted": False,
            "reason": "Original source is empty.",
        }

    if not generated_source.strip():
        return {
            "accepted": False,
            "reason": "Generated source is empty.",
        }

    try:
        original_tokens = _tokens(
            original_source
        )

        generated_tokens = _tokens(
            generated_source
        )

        original_ast = _ast_structure(
            original_source
        )

        generated_ast = _ast_structure(
            generated_source
        )

    except SyntaxError as exc:
        return {
            "accepted": False,
            "reason": (
                f"Python parsing failed: {exc}"
            ),
        }

    token_similarity = _similarity(
        original_tokens,
        generated_tokens,
    )

    ast_similarity = _similarity(
        original_ast,
        generated_ast,
    )

    accepted = (
        token_similarity
        >= minimum_token_similarity
        and ast_similarity
        >= minimum_ast_similarity
    )

    return {
        "accepted": accepted,
        "reason": (
            "Source satisfies similarity guard."
            if accepted
            else
            "Source failed similarity guard."
        ),
        "token_similarity": round(
            token_similarity,
            4,
        ),
        "ast_similarity": round(
            ast_similarity,
            4,
        ),
        "original_token_count": len(
            original_tokens
        ),
        "generated_token_count": len(
            generated_tokens
        ),
        "original_ast_nodes": len(
            original_ast
        ),
        "generated_ast_nodes": len(
            generated_ast
        ),
        "original_hash": hashlib.sha256(
            original_source.encode(
                "utf-8"
            )
        ).hexdigest(),
        "generated_hash": hashlib.sha256(
            generated_source.encode(
                "utf-8"
            )
        ).hexdigest(),
    }