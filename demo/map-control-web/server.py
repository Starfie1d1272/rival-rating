#!/usr/bin/env python3
"""Local web demo for CS2 nav-area map control visualization."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import subprocess
import sys
import uuid
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse


REPO_ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = Path(__file__).resolve().parent / "static"
CACHE_DIR = REPO_ROOT / ".map-control-cache"
UPLOAD_DIR = CACHE_DIR / "uploads"
RESULT_DIR = CACHE_DIR / "results"
PYTHON = REPO_ROOT / ".venv" / "bin" / "python"
EXPORTER = REPO_ROOT / "scripts" / "map-control-export.py"
AWPY_MAPS = REPO_ROOT / ".awpy-home" / ".awpy" / "maps"
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from map_control_static_cache import (  # noqa: E402
    SUPPORTED_MAPS,
    StaticCacheError,
    query_map_info,
    summarize_cache,
)


class MapControlHandler(SimpleHTTPRequestHandler):
    server_version = "MapControlDemo/0.1"

    def do_HEAD(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.serve_file(STATIC_DIR / "index.html", "text/html; charset=utf-8", head_only=True)
            return
        if parsed.path.startswith("/static/"):
            rel = parsed.path.removeprefix("/static/")
            self.serve_file(STATIC_DIR / rel, head_only=True)
            return
        if parsed.path.startswith("/api/map-image/"):
            map_name = parsed.path.rsplit("/", 1)[-1]
            self.serve_file(AWPY_MAPS / f"{map_name}.png", "image/png", head_only=True)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.serve_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
            return
        if parsed.path.startswith("/static/"):
            rel = parsed.path.removeprefix("/static/")
            self.serve_file(STATIC_DIR / rel)
            return
        if parsed.path == "/api/datasets":
            self.send_json({"demos": list_dataset_demos()})
            return
        if parsed.path.startswith("/api/map-info/"):
            self.serve_map_info(parsed.path.rsplit("/", 1)[-1], parse_qs(parsed.query))
            return
        if parsed.path.startswith("/api/static-cache/"):
            self.serve_static_cache_summary(parsed.path.rsplit("/", 1)[-1])
            return
        if parsed.path.startswith("/api/map-image/"):
            map_name = parsed.path.rsplit("/", 1)[-1]
            self.serve_file(AWPY_MAPS / f"{map_name}.png", "image/png")
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        try:
            if parsed.path == "/api/analyze-existing":
                rel_path = single(query, "path")
                demo_path = (REPO_ROOT / unquote(rel_path)).resolve()
                if REPO_ROOT not in demo_path.parents:
                    raise ValueError("Demo must be inside the repository.")
                self.analyze_demo(demo_path, query)
                return
            if parsed.path == "/api/upload":
                filename = Path(single(query, "filename", default=f"upload-{uuid.uuid4().hex}.dem")).name
                length = int(self.headers.get("content-length", "0"))
                if length <= 0:
                    raise ValueError("Upload body is empty.")
                UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
                demo_path = UPLOAD_DIR / f"{uuid.uuid4().hex}-{filename}"
                with open(demo_path, "wb") as fh:
                    remaining = length
                    while remaining > 0:
                        chunk = self.rfile.read(min(1024 * 1024, remaining))
                        if not chunk:
                            break
                        fh.write(chunk)
                        remaining -= len(chunk)
                self.analyze_demo(demo_path, query)
                return
        except Exception as exc:  # noqa: BLE001
            self.send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def analyze_demo(self, demo_path: Path, query: dict[str, list[str]]) -> None:
        sample_seconds = single(query, "sampleSeconds", default="4")
        max_frames = single(query, "maxFrames", default="360")
        residual_seconds = single(query, "residualSeconds", default="3")
        vertical_fov_deg = single(query, "verticalFovDeg", default="75")
        static_los = single(query, "staticLos", default="0") == "1"
        if not demo_path.exists():
            raise FileNotFoundError(str(demo_path))

        RESULT_DIR.mkdir(parents=True, exist_ok=True)
        cache_key = cache_key_for(demo_path, sample_seconds, max_frames, residual_seconds, vertical_fov_deg, static_los)
        output_path = RESULT_DIR / f"{cache_key}.json"

        if not output_path.exists():
            cmd = [
                str(PYTHON),
                str(EXPORTER),
                str(demo_path),
                str(output_path),
                "--sample-seconds",
                sample_seconds,
                "--max-frames",
                max_frames,
                "--residual-seconds",
                residual_seconds,
                "--vertical-fov-deg",
                vertical_fov_deg,
            ]
            if not static_los:
                cmd.append("--no-static-los")
            proc = subprocess.run(
                cmd,
                cwd=REPO_ROOT,
                text=True,
                capture_output=True,
                timeout=600,
                check=False,
            )
            if proc.returncode != 0:
                raise RuntimeError((proc.stderr or proc.stdout or "analysis failed").strip())

        with open(output_path, encoding="utf8") as fh:
            self.send_json(json.load(fh))

    def serve_map_info(self, map_name: str, query: dict[str, list[str]]) -> None:
        try:
            position = {
                "x": float(single(query, "x")),
                "y": float(single(query, "y")),
            }
            z = optional_float(query, "z")
            if z is not None:
                position["z"] = z
            compute_missing = single(query, "computeMissing", default="1") == "1"
            payload = query_map_info(map_name, position, compute_missing=compute_missing)
            self.send_json(payload)
        except (StaticCacheError, ValueError) as exc:
            self.send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

    def serve_static_cache_summary(self, map_name: str) -> None:
        try:
            self.send_json(summarize_cache(map_name))
        except StaticCacheError as exc:
            self.send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

    def serve_file(self, path: Path, content_type: str | None = None, *, head_only: bool = False) -> None:
        path = path.resolve()
        allowed_roots = [STATIC_DIR.resolve(), AWPY_MAPS.resolve()]
        if not any(path == root or root in path.parents for root in allowed_roots):
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if not path.exists() or not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        ctype = content_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        body = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("content-type", ctype)
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        if not head_only:
            self.wfile.write(body)

    def send_json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf8")
        self.send_response(status)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def list_dataset_demos() -> list[dict[str, object]]:
    demos = []
    for path in sorted((REPO_ROOT / ".demo-cache").glob("**/*.dem")):
        analysis_path = path.with_suffix(".analysis.json")
        map_name = None
        if analysis_path.exists():
            try:
                data = json.loads(analysis_path.read_text(encoding="utf8"))
                map_name = data.get("match", {}).get("map_name") or data.get("header", {}).get("map_name")
            except Exception:
                map_name = None
        if map_name not in SUPPORTED_MAPS:
            continue
        rel = path.relative_to(REPO_ROOT)
        demos.append(
            {
                "path": str(rel),
                "name": path.name,
                "mapName": map_name,
                "sizeBytes": path.stat().st_size,
            }
        )
    return demos


def single(query: dict[str, list[str]], key: str, *, default: str | None = None) -> str:
    values = query.get(key)
    if not values:
        if default is not None:
            return default
        raise ValueError(f"Missing query parameter: {key}")
    return values[0]


def optional_float(query: dict[str, list[str]], key: str) -> float | None:
    values = query.get(key)
    if not values or values[0] == "":
        return None
    return float(values[0])


def cache_key_for(
    demo_path: Path,
    sample_seconds: str,
    max_frames: str,
    residual_seconds: str,
    vertical_fov_deg: str,
    static_los: bool,
) -> str:
    stat = demo_path.stat()
    raw = (
        f"{demo_path}:{stat.st_size}:{stat.st_mtime_ns}:"
        f"{sample_seconds}:{max_frames}:{residual_seconds}:{vertical_fov_deg}:{static_los}"
    )
    return hashlib.sha256(raw.encode("utf8")).hexdigest()[:24]


class FastLocalHTTPServer(ThreadingHTTPServer):
    def server_bind(self) -> None:
        self.socket.bind(self.server_address)
        self.server_name = self.server_address[0]
        self.server_port = self.server_address[1]


def main() -> None:
    if not PYTHON.exists():
        raise SystemExit("Missing .venv. Run `python3 -m venv .venv && .venv/bin/python -m pip install awpy`.")
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8787
    server = FastLocalHTTPServer(("127.0.0.1", port), MapControlHandler)
    print(f"Map control demo: http://127.0.0.1:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
