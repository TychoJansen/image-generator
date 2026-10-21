"""Building the image prompt from the words, the context, the glossary and the reference photos."""

from __future__ import annotations

import re
from dataclasses import dataclass

# Everything before the first colon of a glossary line are names, separated by commas, "/", "and" or "en".
NAME_SEPARATORS = re.compile(r",|/|\s+(?:and|en|&)\s+", re.IGNORECASE)
BULLET = re.compile(r"^[-*•]\s*")


@dataclass(frozen=True)
class GlossaryEntry:
    """One glossary line, e.g. "Paris, Dalwhinnie: two brown horses"."""

    names: tuple[str, ...]
    line: str


def parse_glossary(text: str) -> list[GlossaryEntry]:
    """Turn the glossary text into entries; lines without "name:" are ignored."""
    entries = []
    for raw in text.split("\n"):
        line = BULLET.sub("", raw.strip())
        colon = line.find(":")
        if colon < 1:
            continue
        names = tuple(name.strip().lower() for name in NAME_SEPARATORS.split(line[:colon]) if name.strip())
        entries.append(GlossaryEntry(names, line))
    return entries


def _contains_word(haystack: str, name: str) -> bool:
    # A whole word: not directly next to another letter or digit (so "scotchtape" does not match "Scotch").
    return re.search(rf"(?<![^\W_]){re.escape(name)}(?![^\W_])", haystack) is not None


def match_glossary(glossary_text: str, texts: list[str]) -> list[GlossaryEntry]:
    """Keep only the glossary entries whose name occurs (as a whole word) in the given texts."""
    haystack = " | ".join(texts).lower()
    return [entry for entry in parse_glossary(glossary_text) if any(_contains_word(haystack, n) for n in entry.names)]


def build_prompt(
    words: list[str],
    captions: list[str],
    always: str,
    glossary: list[GlossaryEntry],
    first_image_number: int,
) -> str:
    """Build the English prompt; context and captions are passed as written.

    FLUX (Cloudflare) numbers reference images from 0, OpenAI from 1.
    """
    if words:
        parts = [f"Create one detailed, colorful illustration based on these words: {', '.join(words)}."]
    else:
        parts = ["Create one detailed, colorful illustration."]
    if always:
        parts.append(f"Always follow these instructions:\n{always}")
    if glossary:
        heading = "What some of these words mean" if words else "Background information"
        parts.append(f"{heading}:\n" + "\n".join(f"- {entry.line}" for entry in glossary))
    if captions:
        refs = "; ".join(
            f"image {i + first_image_number}" + (f" shows {caption}" if caption else "")
            for i, caption in enumerate(captions)
        )
        parts.append(
            f"Reference images: {refs}. Use them only for how these specific people, animals or places look "
            "(faces, hair, fur, build). Do not copy anything else from them: no extra people, animals, objects, "
            "poses or backgrounds."
        )
    parts.append("Only show the people and animals that are mentioned above. Do not add any other people or animals.")
    return "\n\n".join(parts)
