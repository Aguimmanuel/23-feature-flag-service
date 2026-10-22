"""Built-frontend adapter, mounted LAST after API/health routers.

The frontend component owns the React build; this module creates no mock frontend and never fetches a
CDN. Reserved API/health paths and missing assets cannot become index.html.
"""

from pathlib import Path
from typing import Any


def resolve_frontend_path(directory: Path, requested_path: str) -> Path:
    """Select a safe real file or SPA index; raise FileNotFoundError on misses."""
    root = directory.resolve(strict=True)
    if not root.is_dir() or not (root / "index.html").is_file():
        raise FileNotFoundError("Built frontend is unavailable")
    try:
        index = (root / "index.html").resolve(strict=True)
        index.relative_to(root)
    except (ValueError, OSError, RuntimeError):
        raise FileNotFoundError("Built frontend is unavailable") from None
    parts = requested_path.split("/")
    if (
        parts[0] in {"api", "health"}
        or any(part.startswith(".") for part in parts if part)
        or "\\" in requested_path
        or "\x00" in requested_path
    ):
        raise FileNotFoundError("Not found")
    try:
        target = (root / requested_path).resolve()
        target.relative_to(root)
    except (ValueError, OSError, RuntimeError):
        raise FileNotFoundError("Not found") from None
    if target.is_file():
        return target
    # A missing JS/CSS/JSON/image or assets URL is a real 404, not an HTML file.
    if Path(requested_path).suffix or parts[0] == "assets":
        raise FileNotFoundError("Not found")
    return index


def mount_frontend(app: Any, directory: str | Path) -> None:
    from starlette.exceptions import HTTPException
    from starlette.responses import FileResponse

    root = Path(directory).resolve(strict=True)
    try:
        resolve_frontend_path(root, "")
    except (FileNotFoundError, OSError, ValueError):
        raise RuntimeError("Build the frontend before mounting it") from None

    # Starlette HEAD handling avoids an unnecessary HTML response body. Register
    # LAST; no replacement FastAPI bootstrap is introduced by this adapter.
    @app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    def frontend(path: str):
        try:
            selected = resolve_frontend_path(root, path)
        except (FileNotFoundError, OSError, ValueError):
            raise HTTPException(status_code=404, detail="Not found") from None
        return FileResponse(selected, headers={"Cache-Control": "no-cache"})
