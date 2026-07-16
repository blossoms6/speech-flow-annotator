from __future__ import annotations

import re
from dataclasses import dataclass


WORD_PATTERN = re.compile(r"[A-Za-z]+(?:['’-][A-Za-z]+)*|\d+(?:[.,]\d+)*")
TOKEN_PATTERN = re.compile(r"[A-Za-z]+(?:['’-][A-Za-z]+)*|\d+(?:[.,]\d+)*|[.,!?;:…—-]")
VOWEL_GROUP = re.compile(r"[aeiouy]+", re.IGNORECASE)


@dataclass
class TextToken:
    text: str
    normalized: str
    punctuation_after: str = ""


def normalize_word(value: str) -> str:
    return re.sub(r"[^a-z0-9']", "", value.lower().replace("’", "'"))


def normalize_transcript(text: str) -> str:
    text = text.replace("’", "'").replace("“", '"').replace("”", '"')
    text = re.sub(r"\s+", " ", text).strip()
    return text


def tokenize_transcript(text: str) -> list[TextToken]:
    raw = TOKEN_PATTERN.findall(normalize_transcript(text))
    result: list[TextToken] = []
    for token in raw:
        if WORD_PATTERN.fullmatch(token):
            result.append(TextToken(text=token, normalized=normalize_word(token)))
        elif result:
            result[-1].punctuation_after += token
    return result


def syllable_count(word: str) -> int:
    value = normalize_word(word)
    if not value:
        return 1
    value = re.sub(r"(?:'s|'d|'ll|'re|'ve)$", "", value)
    groups = VOWEL_GROUP.findall(value)
    count = len(groups)
    if len(value) > 2 and value.endswith("e") and not value.endswith(("le", "ye")):
        count -= 1
    if value.endswith("ed") and len(value) > 3 and not value.endswith(("ted", "ded")):
        count -= 1
    if value.endswith("es") and len(value) > 3 and not value.endswith(("ses", "xes", "zes", "ches", "shes")):
        count -= 1
    return max(1, count)


def rebuild_transcript(tokens: list[TextToken]) -> str:
    pieces: list[str] = []
    for token in tokens:
        pieces.append(token.text + token.punctuation_after)
    return " ".join(pieces)


def initial_letter(word: str) -> str:
    normalized = normalize_word(word)
    return normalized[:1]


def final_letter(word: str) -> str:
    normalized = normalize_word(word)
    return normalized[-1:] if normalized else ""
