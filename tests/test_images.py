"""Generated images: list, serve and delete (admin only), and never via the public static files."""

from conftest import JPEG


def add_images(settings, *names):
    settings.images_dir.mkdir(parents=True, exist_ok=True)
    for name in names:
        (settings.images_dir / name).write_bytes(JPEG)


def test_list_newest_first_and_only_images(admin, settings):
    add_images(settings, "100.jpg", "300.png", "200.jpg", ".gitkeep", "notes.txt")
    assert [i["filename"] for i in admin.get("/api/images").json()] == ["300.png", "200.jpg", "100.jpg"]
    assert admin.get("/api/images").json()[0]["url"] == "/images/300.png"


def test_serve_and_delete(admin, settings):
    add_images(settings, "100.jpg")
    assert admin.get("/images/100.jpg").content == JPEG
    assert admin.get("/images/999.jpg").status_code == 404
    assert admin.delete("/api/images/100.jpg").status_code == 204
    assert admin.delete("/api/images/100.jpg").json() == {"error": "Afbeelding niet gevonden."}
    assert admin.delete("/api/images/server.js").json() == {"error": "Ongeldige bestandsnaam."}


def test_images_are_protected(client, settings):
    add_images(settings, "100.jpg")
    assert client.get("/images/100.jpg").status_code == 401
    assert client.get("/api/images").status_code == 401
    assert client.delete("/api/images/100.jpg").status_code == 401


def test_data_folder_is_not_part_of_the_public_files(client, settings):
    add_images(settings, "100.jpg")
    assert not settings.images_dir.is_relative_to(settings.public_dir)
    assert client.get("/data/images/100.jpg").status_code == 404
