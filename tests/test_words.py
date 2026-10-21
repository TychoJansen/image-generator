"""Words: anyone can add them, only the admin can list or delete them."""


def test_add_word_is_public_and_trimmed(client, admin):
    response = client.post("/api/words", json={"text": "  zonsondergang  "})
    assert response.status_code == 201
    assert response.json() == {"text": "zonsondergang"}
    assert [w["text"] for w in admin.get("/api/words").json()] == ["zonsondergang"]


def test_add_word_validation(client):
    assert client.post("/api/words", json={"text": "   "}).json() == {"error": "Het woord mag niet leeg zijn."}
    assert client.post("/api/words", json={"text": 42}).status_code == 400
    too_long = client.post("/api/words", json={"text": "a" * 51})
    assert too_long.status_code == 400
    assert too_long.json()["error"] == "Een woord mag maximaal 50 tekens lang zijn."


def test_invalid_or_non_object_json(client):
    invalid = client.post("/api/words", content=b"{not json", headers={"content-type": "application/json"})
    assert invalid.status_code == 400 and invalid.json() == {"error": "Ongeldige invoer."}
    assert client.post("/api/words", json=["a", "list"]).json() == {"error": "Ongeldige invoer."}


def test_body_too_large(client):
    response = client.post("/api/words", content=b"x" * (2 * 1024 * 1024 + 1))
    assert response.status_code == 413
    assert response.json() == {"error": "Het verzoek is te groot."}


def test_listing_words_needs_login(client):
    response = client.get("/api/words")
    assert response.status_code == 401
    assert response.json() == {"error": "Log eerst in op het tabblad Genereren."}


def test_words_are_listed_newest_first(admin):
    for text in ["eerste", "tweede"]:
        admin.post("/api/words", json={"text": text})
    words = admin.get("/api/words").json()
    assert [w["text"] for w in words] == ["tweede", "eerste"]
    assert set(words[0]) == {"id", "text", "created_at"}


def test_delete_one_word(admin):
    admin.post("/api/words", json={"text": "taart"})
    word_id = admin.get("/api/words").json()[0]["id"]
    assert admin.delete(f"/api/words/{word_id}").status_code == 204
    assert admin.delete(f"/api/words/{word_id}").json() == {"error": "Woord niet gevonden."}
    assert admin.delete("/api/words/abc").json() == {"error": "Ongeldig woord-id."}
    assert admin.delete("/api/words/1.5").status_code == 400


def test_delete_all_words(client, admin):
    for text in ["a", "b", "c"]:
        admin.post("/api/words", json={"text": text})
    assert admin.delete("/api/words").json() == {"deleted": 3}
    assert admin.get("/api/words").json() == []


def test_deleting_needs_login(client):
    assert client.delete("/api/words").status_code == 401
    assert client.delete("/api/words/1").status_code == 401
