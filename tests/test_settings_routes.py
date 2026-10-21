"""Context, glossary and word cloud variants (admin only)."""


def test_context_and_glossary(client, admin):
    assert admin.get("/api/context").json() == {"context": "", "glossary": ""}
    saved = admin.put("/api/context", json={"context": "  Always both.  ", "glossary": "Whisky: a dog"})
    assert saved.json() == {"context": "Always both.", "glossary": "Whisky: a dog"}
    assert admin.get("/api/context").json() == {"context": "Always both.", "glossary": "Whisky: a dog"}


def test_context_limits(admin):
    too_long = admin.put("/api/context", json={"context": "a" * 1001})
    assert too_long.json() == {"error": '"Altijd meesturen" mag maximaal 1000 tekens lang zijn.'}
    glossary = admin.put("/api/context", json={"glossary": "a" * 3001})
    assert glossary.json() == {"error": "De woordenlijst mag maximaal 3000 tekens lang zijn."}


def test_merges(admin):
    assert admin.get("/api/merges").json() == {"merges": ""}
    assert admin.put("/api/merges", json={"merges": "paarden = paard"}).json() == {"merges": "paarden = paard"}
    assert admin.get("/api/merges").json() == {"merges": "paarden = paard"}
    too_long = admin.put("/api/merges", json={"merges": "a" * 3001})
    assert too_long.json() == {"error": "De lijst mag maximaal 3000 tekens lang zijn."}


def test_settings_need_login(client):
    for method, path in [
        ("get", "/api/context"),
        ("put", "/api/context"),
        ("get", "/api/merges"),
        ("put", "/api/merges"),
    ]:
        assert getattr(client, method)(path).status_code == 401
