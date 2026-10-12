"""Read actual RGBA pixels on every supported Pillow version."""


def rgba_pixels(image):
    with image.convert("RGBA") as rgba:
        raw = rgba.tobytes()
    return zip(raw[0::4], raw[1::4], raw[2::4], raw[3::4], strict=True)
