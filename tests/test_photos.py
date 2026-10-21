"""Reference photos: upload, list, serve and delete (admin only)."""

from conftest import JPEG, data_url

from image_generator import config


def upload(admin, **body):
    return admin.post("/api/photos", json={"image": data_url(), **body})


def test_upload_with_large_copy(admin, settings):
    response = upload(admin, caption=" Whisky ", large=data_url(JPEG + b"large"))
    assert response.status_code == 201
    photo = response.json()
    assert photo["caption"] == "Whisky"
    filename = photo["url"].removeprefix("/photos/")
    assert (settings.photos_dir / filename).read_bytes() == JPEG
    assert (settings.photos_dir / filename.replace(".jpg", "-large.jpg")).read_bytes() == JPEG + b"large"
    assert admin.get("/api/photos").json() == [photo]
    served = admin.get(photo["url"])
    assert served.status_code == 200 and served.content == JPEG


def test_upload_with_empty_large_copy(admin, settings):
    assert upload(admin, large="").status_code == 201
    assert [p.name.endswith("-large.jpg") for p in settings.photos_dir.iterdir()] == [False]


def test_upload_validation(admin, monkeypatch):
    assert admin.post("/api/photos", json={"image": "data:text/plain;base64,aGk="}).json() == {
        "error": "Ongeldige foto. Kies een JPG- of PNG-bestand."
    }
    assert admin.post("/api/photos", json={"image": "data:image/jpeg;base64,abc"}).status_code == 400  # bad padding
    assert admin.post("/api/photos", json={}).status_code == 400
    assert upload(admin, caption="a" * 101).json() == {"error": "De beschrijving mag maximaal 100 tekens lang zijn."}
    assert upload(admin, large="nope").json() == {"error": "De grote versie van de foto is ongeldig of te groot."}

    monkeypatch.setattr(config, "MAX_PHOTO_BYTES", 10)
    assert upload(admin).json() == {"error": "De foto is te groot."}


def test_maximum_number_of_photos(admin, monkeypatch):
    monkeypatch.setattr(config, "MAX_PHOTOS_STORED", 1)
    assert upload(admin).status_code == 201
    assert upload(admin).json() == {"error": "Je kunt maximaal 1 foto's bewaren. Verwijder er eerst een."}


def test_delete_photo_removes_both_files(admin, settings):
    photo = upload(admin, large=data_url()).json()
    assert admin.delete(f"/api/photos/{photo['id']}").status_code == 204
    assert list(settings.photos_dir.iterdir()) == []
    assert admin.delete(f"/api/photos/{photo['id']}").json() == {"error": "Foto niet gevonden."}
    assert admin.delete("/api/photos/abc").status_code == 404


def test_photo_files_are_protected(client, admin):
    photo = upload(admin).json()
    client.post("/api/logout")
    assert client.get(photo["url"]).status_code == 401
    assert client.get("/api/photos").status_code == 401
    assert client.post("/api/photos", json={"image": data_url()}).status_code == 401


def test_only_valid_photo_names_are_served(admin):
    assert admin.get("/photos/1234-abcdef12.jpg").status_code == 404  # valid name, no such file
    assert admin.get("/photos/secret.txt").status_code == 404
