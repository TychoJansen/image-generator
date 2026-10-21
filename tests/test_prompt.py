"""The glossary and the prompt text."""

from image_generator.prompt import GlossaryEntry, build_prompt, match_glossary, parse_glossary


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
