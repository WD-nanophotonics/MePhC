from __future__ import annotations

from contextlib import contextmanager
from io import BytesIO
from pathlib import Path


@contextmanager
def _export_size(figure, width: float, height: float):
    previous = tuple(float(value) for value in figure.get_size_inches())
    figure.set_size_inches(float(width), float(height), forward=False)
    try:
        yield
    finally:
        figure.set_size_inches(*previous, forward=False)


def render_png(figure, *, width: float, height: float, dpi: int) -> bytes:
    buffer = BytesIO()
    with _export_size(figure, width, height):
        figure.savefig(buffer, format="png", dpi=int(dpi), bbox_inches=None)
    return buffer.getvalue()


def save_figure(figure, destination: str | Path, *, width: float, height: float, dpi: int) -> Path:
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with _export_size(figure, width, height):
        figure.savefig(destination, dpi=int(dpi), bbox_inches=None)
    return destination
