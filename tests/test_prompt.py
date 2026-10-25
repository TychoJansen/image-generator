"""The glossary and the prompt text."""

from image_generator.prompt import GlossaryEntry, build_prompt, describe_age, known_ages, match_glossary, parse_glossary


def test_parse_glossary():
    entries = parse_glossary(
        "- Whisky: a dog\n* Paris, Dalwhinnie and paarden / horses: two horses\nno colon here\n: empty"
    )
    assert entries == [
        GlossaryEntry(("whisky",), "Whisky: a dog"),
        GlossaryEntry(
            ("paris", "dalwhinnie", "paarden", "horses"), "Paris, Dalwhinnie and paarden / horses: two horses"
        ),
    ]


def test_match_glossary_uses_whole_words():
    glossary = "Scotch: their cat\nNoorwegen, Norway: their wedding trip\nWhisky: a dog"
    names = [e.names[0] for e in match_glossary(glossary, ["scotchtape", "bergen in Noorwegen", "Whisky!"])]
    assert names == ["noorwegen", "whisky"]


def test_prompt_with_words_glossary_and_photos():
    glossary = [GlossaryEntry(("whisky",), "Whisky: a dog")]
    prompt = build_prompt(["Whisky", "taart"], ["Whisky", ""], "A wedding.", glossary, 1)
    assert prompt.split("\n\n") == [
        "Create one detailed, colorful illustration based on these words: Whisky, taart.",
        "Always follow these instructions:\nA wedding.",
        "What some of these words mean:\n- Whisky: a dog",
        "Reference images: image 1 shows Whisky; image 2. Use them only for how these specific people, animals or "
        "places look (faces, hair, fur, build). Do not copy anything else from them: no extra people, animals, "
        "objects, poses or backgrounds.",
        "Only show the people and animals that are mentioned above. Do not add any other people or animals.",
    ]


def test_prompt_without_words():
    glossary = [GlossaryEntry(("whisky",), "Whisky: a dog")]
    prompt = build_prompt([], ["Whisky"], "", glossary, 0)
    assert prompt.startswith("Create one detailed, colorful illustration.\n\nBackground information:\n- Whisky: a dog")
    assert "image 0 shows Whisky" in prompt


def test_time_machine_year():
    prompt = build_prompt(["taart"], [], "", [], 0, 1925)
    assert "Time machine: show this scene as it would look in the year 1925:" in prompt
    assert prompt.endswith("Do not add any other people or animals.")
    assert "as it would look in 10000 BC:" in build_prompt([], [], "A wedding.", [], 0, -10000)
    assert "Time machine" not in build_prompt(["taart"], [], "", [], 0)


def test_time_machine_with_age():
    always = "\n".join(
        ["- Laureanne, the bride: a 30-year-old woman.", "Always include Jerrel (the groom, 32, with a beard)."]
    )
    older = build_prompt([], ["Laureanne"], always, [], 0, 2080, change_age=True, current_year=2026)
    assert "only their age, their clothing, the surroundings and the style change" in older
    assert "everyone is 54 years older than now" in older
    assert "Laureanne is 84 years old (very old); Jerrel is 86 years old (very old)." in older
    assert "grey or white hair" in older and "beards" not in older
    assert "they show them at their age today, so change their age" in older  # reference photo instruction

    younger = build_prompt([], [], always, [], 0, 2010, change_age=True, current_year=2026)
    assert "Laureanne is 14 years old (a teenager); Jerrel is 16 years old (a teenager)." in younger
    assert "wedding clothes and beards described above are for today and do not apply here" in younger
    babies = build_prompt([], [], always, [], 0, 1925, change_age=True, current_year=2026)
    assert "Laureanne is not born yet, so a newborn baby" in babies

    same_year = build_prompt([], ["Laureanne"], always, [], 0, 2026, change_age=True, current_year=2026)
    assert "Age" not in same_year and "only their clothing" in same_year
    assert "Use them only for how these specific people" in same_year
    assert "Age (most important)" not in build_prompt([], [], always, [], 0, 2080, current_year=2026)


def test_ages_from_glossary_and_without_known_ages():
    glossary = [GlossaryEntry(("whisky",), "Whisky: a dog, aged 3")]
    prompt = build_prompt(["Whisky"], [], "", glossary, 0, 2030, change_age=True, current_year=2026)
    assert "Whisky is 7 years old (a child)" in prompt
    unknown = build_prompt(["taart"], [], "A wedding.", [], 0, 2036, change_age=True, current_year=2026)
    assert "For example, someone who is 30 today is 40 years old (middle-aged) here." in unknown


def test_known_ages_and_life_stages():
    text = "\n".join(["Anna (mother, 61)", "- Bob: 8 jaar", "- Carl is 100 years old", "no name here: a 20-year-old"])
    assert known_ages(text) == [("Anna", 61), ("Bob", 8), ("Carl", 100)]
    assert describe_age(1) == "1 year old (a baby)"
    assert [describe_age(a).split("(")[1] for a in (4, 70)] == ["a toddler)", "elderly)"]
