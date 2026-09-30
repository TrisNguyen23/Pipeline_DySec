from __future__ import annotations

import ast
import hashlib
import tokenize
from io import StringIO


def _tokens(source: str) -> list[str]:
    result = []

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

            result.append(
                token.string
            )

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

    result = []

    for node in ast.walk(tree):
        result.append(
            type(node).__name__
        )

    return result


def _similarity(
    a: list[str],
    b: list[str],
) -> float:
    if not a and not b:
        return 1.0

    if not a or not b:
        return 0.0

    from difflib import SequenceMatcher

    return SequenceMatcher(
        None,
        a,
        b,
    ).ratio()


def source_change_guard(
    original_source: str,
    generated_source: str,
    minimum_token_similarity: float = 0.55,
    minimum_ast_similarity: float = 0.70,
) -> dict:
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
        "token_similarity": token_similarity,
        "ast_similarity": ast_similarity,
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