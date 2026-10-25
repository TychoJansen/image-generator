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


# Ages in the context, e.g. "- Laureanne, the bride: a 30-year-old woman" or "Laureanne (the bride, 30)".
AGE_IN_LINE = re.compile(
    r"\b(\d{1,3})\s*-?\s*(?:years?|yrs?)[\s-]*old\b|\baged?\s+(\d{1,3})\b|\b(\d{1,3})\s+jaar\b", re.I
)
NAME_AT_START = re.compile(r"^[-*•\s]*([A-Z][\w'’-]+)")
NAME_WITH_AGE = re.compile(r"\b([A-Z][\w'’-]+)\s*\((?:[^()]*?,\s*)?(\d{1,3})\b[^()]*\)")


def known_ages(text: str) -> list[tuple[str, int]]:
    """Names with their age today, as far as the context mentions them (first mention wins)."""
    ages: dict[str, int] = {}
    for line in text.splitlines():
        for name, age in NAME_WITH_AGE.findall(line):
            ages.setdefault(name, int(age))
        name = NAME_AT_START.match(line)
        age = AGE_IN_LINE.search(line)
        if name and age:
            ages.setdefault(name[1], int(next(group for group in age.groups() if group)))
    return list(ages.items())


def describe_age(age: int) -> str:
    """'14 years old (a teenager)', or a newborn baby when the person would not be born yet."""
    if age <= 0:
        return "not born yet, so a newborn baby"
    stages = [(2, "a baby"), (5, "a toddler"), (12, "a child"), (19, "a teenager"), (35, "a young adult"),
              (60, "middle-aged"), (80, "elderly")]  # fmt: skip
    stage = next((label for limit, label in stages if age <= limit), "very old")
    return f"{age} {'year' if age == 1 else 'years'} old ({stage})"


def is_aging(year: int | None, change_age: bool, current_year: int) -> bool:
    """Whether the time machine changes everyone's age."""
    return year is not None and change_age and year != current_year


def time_machine(year: int, change_age: bool, current_year: int, people: str = "") -> list[str]:
    """The prompt parts for the time machine: the scene in another year, and optionally everyone older or younger.

    `people` is the text that describes the people (context and glossary); the ages in it are recalculated.
    """
    when = f"{-year} BC" if year < 0 else f"the year {year}"
    aging = is_aging(year, change_age, current_year)
    changes = (
        "their age, their clothing, the surroundings and the style"
        if aging
        else ("their clothing, the surroundings and the style")
    )
    parts = [
        f"Time machine: show this scene as it would look in {when}: the clothing, hairstyles, buildings, vehicles, "
        f"technology and art style of that time. Keep the same people and animals recognisable; only {changes} "
        "change. This replaces the usual style."
    ]
    if not aging:
        return parts

    years = year - current_year
    if years > 0:
        direction = f"{years} years after today ({current_year}), so everyone is {years} years older than now"
        today = "The ages described above are for today: show everyone at these older ages, with grey or white hair, "
        today += "wrinkles and a matching posture, in clothes that suit their age and that time."
        animals = "Animals are old too (grey snouts, slower)."
    else:
        direction = f"{-years} years before today ({current_year}), so everyone is {-years} years younger than now"
        today = "The ages, wedding clothes and beards described above are for today and do not apply here: show "
        today += "everyone at these younger ages, in clothes that suit their age and that time."
        animals = "Animals are young too (puppies, kittens, foals), or newborn if they would not be born yet."
    ages = known_ages(people)
    if ages:
        detail = "So in this image: " + "; ".join(f"{name} is {describe_age(age + years)}" for name, age in ages) + "."
    else:
        detail = f"For example, someone who is 30 today is {describe_age(30 + years)} here."
    parts.append(f"Age (most important): this scene is {direction}. {detail} {today} {animals}")
    return parts


def build_prompt(
    words: list[str],
    captions: list[str],
    always: str,
    glossary: list[GlossaryEntry],
    first_image_number: int,
    year: int | None = None,
    change_age: bool = False,
    current_year: int = 0,
) -> str:
    """Build the English prompt; context and captions are passed as written.

    FLUX (Cloudflare) numbers reference images from 0, OpenAI from 1. With a `year` (time machine), the same scene
    is shown in that year; negative years are before Christ. With `change_age`, everyone is as much older or younger
    as `year` is after or before `current_year`.
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
        if is_aging(year, change_age, current_year):
            # The photos show everyone at their age today: use them to recognise people, not for their age.
            use = (
                "Use them only to keep these specific people and animals recognisable (face shape, eye colour, hair "
                "and fur colour); they show them at their age today, so change their age as described below."
            )
        else:
            use = "Use them only for how these specific people, animals or places look (faces, hair, fur, build)."
        parts.append(
            f"Reference images: {refs}. {use} Do not copy anything else from them: no extra people, animals, "
            "objects, poses or backgrounds."
        )
    if year is not None:
        people = "\n".join([always, *(entry.line for entry in glossary)])
        parts.extend(time_machine(year, change_age, current_year, people))
    parts.append("Only show the people and animals that are mentioned above. Do not add any other people or animals.")
    return "\n\n".join(parts)
