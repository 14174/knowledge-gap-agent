import re
import unicodedata


_ASCII_TERM_PATTERN = re.compile(r"[A-Za-z0-9_]+")
_HAN_NAME_PREFIXES = (
    "CJK UNIFIED IDEOGRAPH-",
    "CJK COMPATIBILITY IDEOGRAPH-",
)


def _is_han(character: str) -> bool:
    return unicodedata.name(character, "").startswith(_HAN_NAME_PREFIXES)


def tokenize(text: str) -> list[str]:
    """按中文二元字组与英文数字标识符生成确定性词项。"""
    terms: list[str] = []
    index = 0
    while index < len(text):
        ascii_match = _ASCII_TERM_PATTERN.match(text, index)
        if ascii_match is not None:
            terms.append(ascii_match.group().lower())
            index = ascii_match.end()
            continue

        if _is_han(text[index]):
            end = index + 1
            while end < len(text) and _is_han(text[end]):
                end += 1
            segment = text[index:end]
            if len(segment) == 1:
                terms.append(segment)
            else:
                terms.extend(segment[index : index + 2] for index in range(len(segment) - 1))
            index = end
            continue

        index += 1
    return terms
