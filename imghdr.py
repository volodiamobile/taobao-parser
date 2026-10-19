"""Minimal imghdr replacement.

Python 3.13 removed the stdlib imghdr module, but Streamlit 1.22 imports it
(streamlit/elements/image.py) to detect image format. This shim restores the
what() API that Streamlit uses: what(h, bytes) -> 'jpeg'|'png'|'gif'|'webp'|...
"""


def what(file=None, h=None):
    if h is None:
        if file is None:
            return None
        if isinstance(file, (bytes, bytearray)):
            h = bytes(file)
        elif isinstance(file, str):
            with open(file, "rb") as f:
                h = f.read(32)
        else:
            head = file.read(32)
            h = head if isinstance(head, bytes) else bytes(head)
    if not h:
        return None
    b = bytes(h)
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if b[:2] == b"\xff\xd8":
        return "jpeg"
    if b[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "webp"
    if b[:2] in (b"BM",):
        return "bmp"
    if b[:4] in (b"II*\x00", b"MM\x00*"):
        return "tiff"
    return None


def tests():
    return [what]
