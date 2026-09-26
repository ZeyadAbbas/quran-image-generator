from pathlib import Path

import rendering
from layout import ImageLayout, PositionedLine, TextStyle, VerseMarker
from rendering import WandImageRenderer


def test_wand_renderer_draws_text_and_saves_destination(
    monkeypatch, settings_factory, tmp_path
):
    created_images = []
    drawn_text = []
    applied_images = []
    saved_paths = []
    composites = []
    resized = []

    class FakeImage:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            created_images.append(self)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def save(self, filename):
            saved_paths.append(filename)

        def composite(self, other, x, y):
            composites.append((self, other, x, y))

        def resize(self, width, height):
            resized.append((self, width, height))

    class FakeDrawing:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def text(self, x, y, text):
            drawn_text.append((x, y, text))

        def __call__(self, image):
            applied_images.append(image)

    monkeypatch.setattr(rendering, "Image", FakeImage)
    monkeypatch.setattr(rendering, "Drawing", FakeDrawing)
    style = TextStyle("Fixture Quran", 24, "#FFFFFF", 0.0, 200, " ")
    image_layout = ImageLayout(
        width=300,
        height=200,
        content_height=10,
        lines=(PositionedLine("verse", 12.9, 34.8, 50, 10, style),),
        markers=(VerseMarker(1, 2.9, 3.9, 55, 55),),
    )
    destination = tmp_path / "output.png"
    settings = settings_factory(background_image=tmp_path / "background.png")

    result = WandImageRenderer().render(image_layout, settings, destination)

    assert result == destination
    assert created_images[0].kwargs == {
        "width": 300,
        "height": 200,
        "pseudo": "xc:#000000",
    }
    assert drawn_text == [(12, 34, "verse")]
    assert applied_images == [created_images[0]]
    assert saved_paths == [str(destination)]
    assert created_images[1].kwargs == {"filename": str(settings.background_image)}
    assert created_images[2].kwargs == {
        "filename": str(Path("assets/verse_numbers/1.png"))
    }
    assert composites == [
        (created_images[0], created_images[1], 0, 0),
        (created_images[0], created_images[2], 2, 3),
    ]
    assert resized == [(created_images[2], 55, 55)]
