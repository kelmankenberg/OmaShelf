#!/usr/bin/env python3
"""Local, read-only media catalog backend for the OmaShelf Omarchy plugin."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import sqlite3
import stat
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from contextlib import closing
from datetime import datetime
from pathlib import Path

DATA_DIR = Path(
    os.environ.get(
        "OMASHELF_DATA_DIR",
        str(Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "omashelf"),
    )
)
DB_PATH = DATA_DIR / "catalog.sqlite3"
STATUS_PATH = DATA_DIR / "status.json"
PREFERENCES_PATH = DATA_DIR / "preferences.json"
MAX_FILES = 200_000
MAX_SEARCH_RESULTS = 500
MAX_RESPONSE_BYTES = 1_000_000
MAX_ARTWORK_BYTES = 5_000_000
MAX_LIBRARY_BYTES = 256 * 1024 * 1024
MAX_REQUEST_BYTES = 2 * 1024 * 1024
LIBRARY_FIELDS = (
    "id", "label", "source", "path", "kind", "scanned_at", "file_count",
    "size_bytes", "artist", "external_url", "disc_number", "disc_count",
)
SUPPORTED_FILESYSTEMS = {
    "btrfs", "ext2", "ext3", "ext4", "exfat", "f2fs", "iso9660",
    "ntfs", "ntfs3", "udf", "vfat", "xfs",
}
EXCLUDED_MOUNT_PREFIXES = (
    "/proc", "/sys", "/dev", "/etc", "/usr", "/var",
    "/home", "/boot",
)
TRACK_ROW = re.compile(
    r"^\s*(\d+)\.\s+(\d+)\s+\[[^\]]+\]\s+(\d+)\s+\[[^\]]+\]",
    re.MULTILINE,
)


def ensure_private_data_dir() -> None:
    DATA_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(DATA_DIR, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        if os.fstat(fd).st_uid != os.geteuid():
            raise PermissionError("OmaShelf's data directory must be owned by the current user.")
        os.fchmod(fd, 0o700)
    finally:
        os.close(fd)


def connect() -> sqlite3.Connection:
    ensure_private_data_dir()
    fd = os.open(DB_PATH, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid():
            raise PermissionError("OmaShelf's catalog must be a regular file owned by the current user.")
        os.fchmod(fd, 0o600)
    finally:
        os.close(fd)
    db = sqlite3.connect(DB_PATH, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS disks (
            id TEXT PRIMARY KEY,
            label TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT '',
            path TEXT NOT NULL,
            kind TEXT NOT NULL,
            scanned_at TEXT NOT NULL,
            file_count INTEGER NOT NULL DEFAULT 0,
            size_bytes INTEGER NOT NULL DEFAULT 0,
            artist TEXT NOT NULL DEFAULT '',
            artwork TEXT NOT NULL DEFAULT '',
            external_url TEXT NOT NULL DEFAULT '',
            disc_number INTEGER,
            disc_count INTEGER
        );
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY,
            disk_id TEXT NOT NULL REFERENCES disks(id) ON DELETE CASCADE,
            path TEXT NOT NULL,
            size_bytes INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS files_disk_id ON files(disk_id);
        CREATE INDEX IF NOT EXISTS files_path ON files(path COLLATE NOCASE);
        CREATE TABLE IF NOT EXISTS disk_tags (
            disk_id TEXT NOT NULL REFERENCES disks(id) ON DELETE CASCADE,
            name TEXT NOT NULL COLLATE NOCASE,
            PRIMARY KEY (disk_id, name)
        );
        CREATE TABLE IF NOT EXISTS disk_edits (
            disk_id TEXT PRIMARY KEY REFERENCES disks(id) ON DELETE CASCADE,
            metadata TEXT NOT NULL
        );
        """
    )
    columns = {row["name"] for row in db.execute("PRAGMA table_info(disks)")}
    for column in ("disc_number", "disc_count"):
        if column not in columns:
            db.execute(f"ALTER TABLE disks ADD COLUMN {column} INTEGER")
    return db


EDIT_FIELDS = {"label": 240, "artist": 4096, "path": 4096}


def apply_disk_edits(db: sqlite3.Connection, disk_id: str) -> sqlite3.Row:
    saved = db.execute("SELECT metadata FROM disk_edits WHERE disk_id = ?", (disk_id,)).fetchone()
    if saved:
        edits = json.loads(saved["metadata"])
        fields = [field for field in (*EDIT_FIELDS, "disc_number", "disc_count") if field in edits]
        if fields:
            db.execute(
                "UPDATE disks SET " + ", ".join(f"{field} = ?" for field in fields) + " WHERE id = ?",
                [edits[field] for field in fields] + [disk_id],
            )
    return db.execute("SELECT * FROM disks WHERE id = ?", (disk_id,)).fetchone()


def validate_edit_fields(values: object) -> dict[str, object]:
    allowed = {*EDIT_FIELDS, "disc_number", "disc_count"}
    if not isinstance(values, dict) or not set(values) <= allowed:
        raise ValueError("Choose valid disc fields to edit.")
    metadata: dict[str, object] = {}
    for field, limit in EDIT_FIELDS.items():
        if field not in values:
            continue
        value = values[field]
        if not isinstance(value, str) or len(value) > limit:
            raise ValueError(f"{field.capitalize()} must be text of at most {limit} characters.")
        metadata[field] = value.strip()
        if field in {"label", "path"} and not metadata[field]:
            raise ValueError("Disc label and location cannot be empty.")
    if "disc_number" in values or "disc_count" in values:
        if not {"disc_number", "disc_count"} <= set(values):
            raise ValueError("Provide both the CD number and total.")
        number, count = values["disc_number"], values["disc_count"]
        if not (number is None and count is None) and not (
            type(number) is int and type(count) is int and 1 <= number <= count <= 1000
        ):
            raise ValueError("Enter a CD number and total between 1 and 1000, or leave both blank.")
        metadata.update(disc_number=number, disc_count=count)
    return metadata


def normalize_tags(tags: object) -> dict[str, str]:
    if not isinstance(tags, list) or any(
        not isinstance(tag, str) or not tag.strip() or len(tag) > 300 for tag in tags
    ):
        raise ValueError("Use up to 100 nonempty tags, each at most 300 characters.")
    unique_tags = {tag.strip().casefold(): tag.strip() for tag in reversed(tags)}
    if len(unique_tags) > 100:
        raise ValueError("Each disc can have at most 100 tags.")
    return unique_tags


def edit_disk(disk_id: str, values: object) -> dict[str, object]:
    required = {*EDIT_FIELDS, "disc_number", "disc_count", "tags"}
    if not isinstance(values, dict) or set(values) != required:
        raise ValueError("Provide the disc label, artist, location, CD numbers, and tags.")
    edit_disks([disk_id], {
        "fields": {field: value for field, value in values.items() if field != "tags"},
        "tagOperation": "replace", "tags": values["tags"],
    }, only_changes=True)
    return {"diskId": disk_id, "saved": True}


def edit_disks(disk_ids: object, changes: object, *, only_changes: bool = False) -> dict[str, object]:
    if not isinstance(disk_ids, list) or not 1 <= len(disk_ids) <= 500 or any(
        not isinstance(disk_id, str) or not disk_id or len(disk_id) > 256 for disk_id in disk_ids
    ):
        raise ValueError("Choose between 1 and 500 valid discs to edit.")
    disk_ids = list(dict.fromkeys(disk_ids))
    if not isinstance(changes, dict) or set(changes) != {"fields", "tagOperation", "tags"}:
        raise ValueError("Provide fields and a tag operation for the selected discs.")
    metadata = validate_edit_fields(changes["fields"])
    operation = changes["tagOperation"]
    if operation not in ("keep", "add", "remove", "replace"):
        raise ValueError("Choose whether to keep, add, remove, or replace tags.")
    tags = normalize_tags(changes["tags"])
    if not metadata and (operation == "keep" or (operation in ("add", "remove") and not tags)):
        raise ValueError("Enable a field to change or choose tags to add, remove, or replace.")
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        placeholders = ",".join("?" for _ in disk_ids)
        disks = db.execute(f"SELECT * FROM disks WHERE id IN ({placeholders})", disk_ids).fetchall()
        if len(disks) != len(disk_ids):
            raise ValueError("One or more selected discs are no longer in the library.")
        if metadata.get("disc_number") is not None and any(disk["kind"] != "audio" for disk in disks):
            raise ValueError("CD numbering is only available for audio CDs.")
        for current in disks:
            disk_id = current["id"]
            if metadata:
                previous = db.execute("SELECT metadata FROM disk_edits WHERE disk_id = ?", (disk_id,)).fetchone()
                edits = json.loads(previous["metadata"]) if previous else {}
                edits.update({
                    field: value for field, value in metadata.items()
                    if not only_changes or current[field] != value
                })
                db.execute(
                    "INSERT INTO disk_edits(disk_id, metadata) VALUES (?, ?) "
                    "ON CONFLICT(disk_id) DO UPDATE SET metadata=excluded.metadata",
                    (disk_id, json.dumps(edits)),
                )
                apply_disk_edits(db, disk_id)
            if operation == "keep":
                continue
            existing = {
                row["name"].casefold(): row["name"]
                for row in db.execute("SELECT name FROM disk_tags WHERE disk_id = ?", (disk_id,))
            }
            if operation == "add":
                updated = {**tags, **existing}
            elif operation == "remove":
                updated = {key: value for key, value in existing.items() if key not in tags}
            else:
                updated = tags
            if len(updated) > 100:
                raise ValueError(f"Disc '{current['label']}' would exceed the 100-tag limit.")
            db.execute("DELETE FROM disk_tags WHERE disk_id = ?", (disk_id,))
            db.executemany(
                "INSERT INTO disk_tags(disk_id, name) VALUES (?, ?)",
                ((disk_id, tag) for tag in updated.values()),
            )
    return {"diskIds": disk_ids, "saved": True, "updated": len(disk_ids)}


def write_json(path: Path, value: object) -> None:
    ensure_private_data_dir()
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=DATA_DIR, delete=False
    ) as stream:
        json.dump(value, stream, ensure_ascii=False)
        stream.flush()
        os.fsync(stream.fileno())
        temporary_path = Path(stream.name)
    os.replace(temporary_path, path)


def set_scanning(active: bool, message: str = "") -> None:
    write_json(STATUS_PATH, {"scanning": active, "message": message[:240]})


def read_preferences() -> dict[str, str]:
    try:
        value = json.loads(PREFERENCES_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"mode": "docked"}
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Could not read preferences: {error}") from error
    mode = value.get("mode") if isinstance(value, dict) else None
    return {"mode": mode if mode in {"docked", "app"} else "docked"}


def set_mode(mode: str) -> dict[str, object]:
    if mode not in {"docked", "app"}:
        raise ValueError("Mode must be 'docked' or 'app'.")
    write_json(PREFERENCES_PATH, {"mode": mode})
    return {"mode": mode}


def mount_entries() -> list[dict[str, str]]:
    result = subprocess.run(
        ["findmnt", "--json", "--list", "--output", "SOURCE,TARGET,FSTYPE,LABEL,UUID"],
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    )
    document = json.loads(result.stdout)
    entries: list[dict[str, str]] = []
    seen: set[str] = set()
    for entry in document.get("filesystems", []):
        target = str(entry.get("target", ""))
        fstype = str(entry.get("fstype", "")).lower()
        if not target or target == "/" or fstype not in SUPPORTED_FILESYSTEMS:
            continue
        if target == "/run" or (target.startswith("/run/") and not target.startswith("/run/media/")):
            continue
        if any(target == prefix or target.startswith(prefix + "/") for prefix in EXCLUDED_MOUNT_PREFIXES):
            continue
        source = str(entry.get("source", ""))
        label = str(entry.get("label") or Path(target).name or source)
        uuid = str(entry.get("uuid", ""))
        key = volume_key(source, uuid)
        if key in seen:
            continue
        seen.add(key)
        entries.append({
            "id": key,
            "path": target,
            "source": source,
            "fstype": fstype,
            "label": label[:240],
            "uuid": uuid,
        })
    return entries[:100]


def volume_key(source: str, uuid: str = "") -> str:
    identity = uuid or source
    if not identity:
        return "volume:" + hashlib.sha256(source.encode("utf-8")).hexdigest()
    return "volume:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()


def mount_for_path(path: Path) -> dict[str, str]:
    result = subprocess.run(
        [
            "findmnt", "--json", "--list",
            "--output", "SOURCE,TARGET,FSTYPE,LABEL,UUID",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    )
    entries = json.loads(result.stdout).get("filesystems", [])
    matching = [
        entry for entry in entries
        if entry.get("target") and path.is_relative_to(Path(entry["target"]))
    ]
    if not matching:
        return {}
    entry = max(matching, key=lambda item: len(Path(item["target"]).parts))
    return {key: str(entry.get(key.lower()) or "") for key in ("SOURCE", "TARGET", "FSTYPE", "LABEL", "UUID")}


def scan_directory(path_text: str) -> dict[str, object]:
    original_path = Path(path_text).expanduser()
    if not original_path.is_dir():
        raise ValueError("Choose an existing, mounted directory to scan.")
    path = original_path.resolve(strict=True)
    if path == Path("/") or str(path) in {"/proc", "/sys", "/dev", "/run"}:
        raise ValueError("Scanning the system root and virtual system directories is not allowed.")

    mount = mount_for_path(path)
    mount_target = Path(mount["TARGET"]).resolve() if mount.get("TARGET") else None
    source = mount.get("SOURCE", "")
    uuid = mount.get("UUID", "")
    if mount_target == path and (source or uuid):
        disk_id = volume_key(source, uuid)
    else:
        disk_id = "folder:" + hashlib.sha256(str(path).encode("utf-8")).hexdigest()
    label = mount.get("LABEL") or path.name or str(path)
    errors: list[str] = []
    found: list[tuple[str, int]] = []
    total_bytes = 0
    set_scanning(True, str(path))
    try:
        for current, directories, filenames in os.walk(path, topdown=True, followlinks=False, onerror=lambda e: errors.append(str(e))):
            current_path = Path(current)
            depth = len(current_path.relative_to(path).parts)
            if depth >= 64:
                directories[:] = []
                errors.append(f"Maximum scan depth reached at {current_path}")
            else:
                directories[:] = sorted(
                    name for name in directories
                    if not (current_path / name).is_symlink()
                )
            for name in filenames:
                file_path = current_path / name
                try:
                    if file_path.is_symlink():
                        continue
                    stat = file_path.stat(follow_symlinks=False)
                    if not file_path.is_file():
                        continue
                    relative = file_path.relative_to(path).as_posix()
                    found.append((relative[:4096], stat.st_size))
                    total_bytes += stat.st_size
                except OSError as error:
                    if len(errors) < 20:
                        errors.append(f"{file_path}: {error}")
                if len(found) >= MAX_FILES:
                    errors.append(f"Stopped at the {MAX_FILES:,}-file safety limit.")
                    break
            if len(found) >= MAX_FILES:
                break

        with connect() as db:
            db.execute(
                """
                INSERT INTO disks(id, label, source, path, kind, scanned_at, file_count, size_bytes)
                VALUES (?, ?, ?, ?, 'data', datetime('now'), ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    label=excluded.label, source=excluded.source, path=excluded.path,
                    kind='data', scanned_at=excluded.scanned_at,
                    file_count=excluded.file_count, size_bytes=excluded.size_bytes
                """,
                (disk_id, label[:240], source, str(path), len(found), total_bytes),
            )
            db.execute("DELETE FROM files WHERE disk_id = ?", (disk_id,))
            db.executemany(
                "INSERT INTO files(disk_id, path, size_bytes) VALUES (?, ?, ?)",
                ((disk_id, relative, size) for relative, size in found),
            )
            edited = apply_disk_edits(db, disk_id)
        return {
            "diskId": disk_id,
            "label": edited["label"],
            "path": edited["path"],
            "files": len(found),
            "sizeBytes": total_bytes,
            "errors": errors[:20],
            "partial": bool(errors),
        }
    finally:
        set_scanning(False)


def read_audio_toc(device: str) -> tuple[list[dict[str, int]], int]:
    if not re.fullmatch(r"/dev/sr\d+", device):
        raise ValueError("Only optical drive devices such as /dev/sr0 are supported.")
    result = subprocess.run(
        ["cdparanoia", "-Q", "-d", device],
        capture_output=True,
        text=True,
        timeout=8,
        check=False,
    )
    output = result.stdout + "\n" + result.stderr
    tracks = [
        {
            "number": int(match.group(1)),
            "length": int(match.group(2)),
            # cdparanoia reports LBA; MusicBrainz uses absolute CD sectors.
            "offset": int(match.group(3)) + 150,
        }
        for match in TRACK_ROW.finditer(output)
    ]
    if result.returncode != 0 or not tracks:
        raise RuntimeError("No readable audio CD was found in the selected drive.")
    tracks.sort(key=lambda track: track["number"])
    leadout = tracks[-1]["offset"] + tracks[-1]["length"]
    return tracks, leadout


def musicbrainz_disc_id(tracks: list[dict[str, int]], leadout: int) -> str:
    first = tracks[0]["number"]
    last = tracks[-1]["number"]
    offsets = {track["number"]: track["offset"] for track in tracks}
    toc = f"{first:02X}{last:02X}{leadout:08X}"
    toc += "".join(f"{offsets.get(number, 0):08X}" for number in range(1, 100))
    digest = hashlib.sha1(toc.encode("ascii")).digest()
    return base64.b64encode(digest).decode("ascii").replace("/", "_").replace("+", ".").replace("=", "-")


def fetch_json(url: str) -> dict[str, object]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "OmaShelf/0.1 (personal local catalog)"},
    )
    with urllib.request.urlopen(request, timeout=8) as response:
        body = response.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise RuntimeError("MusicBrainz response exceeded the 1 MB safety limit.")
    value = json.loads(body)
    if not isinstance(value, dict):
        raise RuntimeError("MusicBrainz returned an unexpected response.")
    return value


def artist_name(value: object) -> str:
    if not isinstance(value, list):
        return ""
    names = []
    for credit in value[:8]:
        if isinstance(credit, dict):
            name = credit.get("name")
            if isinstance(name, str) and name:
                names.append(name[:240])
    return ", ".join(names)


def save_artwork(release_id: str, disc_id: str) -> str:
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", release_id):
        return ""
    url = f"https://coverartarchive.org/release/{release_id}/front-250"
    request = urllib.request.Request(url, headers={"User-Agent": "OmaShelf/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            final_url = urllib.parse.urlparse(response.geturl())
            if final_url.scheme != "https" or not (
                final_url.hostname == "coverartarchive.org"
                or (final_url.hostname or "").endswith(".archive.org")
                or final_url.hostname == "archive.org"
            ):
                raise RuntimeError("Artwork service redirected to an unexpected host.")
            image = response.read(MAX_ARTWORK_BYTES + 1)
            content_type = response.headers.get_content_type()
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return ""
        raise RuntimeError(f"Artwork lookup failed: HTTP {error.code}") from error
    if len(image) > MAX_ARTWORK_BYTES:
        raise RuntimeError("Artwork exceeded the 5 MB safety limit.")
    signatures = {
        "image/jpeg": image.startswith(b"\xff\xd8\xff"),
        "image/png": image.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/webp": image.startswith(b"RIFF") and image[8:12] == b"WEBP",
    }
    if not signatures.get(content_type, False):
        raise RuntimeError("Artwork service returned an unsupported image.")
    extension = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}[content_type]
    art_dir = DATA_DIR / "artwork"
    art_dir.mkdir(parents=True, exist_ok=True)
    art_path = art_dir / (hashlib.sha256(disc_id.encode("ascii")).hexdigest() + extension)
    art_path.write_bytes(image)
    return art_path.as_uri()


def identify_audio(device: str) -> dict[str, object]:
    tracks, leadout = read_audio_toc(device)
    disc_id = musicbrainz_disc_id(tracks, leadout)
    params = urllib.parse.urlencode({"inc": "artists+recordings", "fmt": "json"})
    url = f"https://musicbrainz.org/ws/2/discid/{urllib.parse.quote(disc_id)}?{params}"
    lookup_error = ""
    try:
        response = fetch_json(url)
    except (OSError, RuntimeError, urllib.error.URLError, json.JSONDecodeError) as error:
        response = {}
        lookup_error = f"Online identification failed; the disc was catalogued locally. {error}"
    releases = response.get("releases", [])
    release = releases[0] if isinstance(releases, list) and releases and isinstance(releases[0], dict) else {}
    if not release and not lookup_error:
        lookup_error = "MusicBrainz has no matching release for this CD. Its tracks were catalogued locally."
    release_id = str(release.get("id", ""))
    title = str(release.get("title", ""))[:240] or f"Audio CD ({disc_id[:8]})"
    artist = artist_name(release.get("artist-credit"))
    track_names: dict[int, tuple[str, str]] = {}
    disc_number = None
    disc_count = None
    media = release.get("media", [])
    if isinstance(media, list):
        for medium in media:
            if not isinstance(medium, dict):
                continue
            medium_discs = medium.get("discs", [])
            if not isinstance(medium_discs, list) or not any(
                isinstance(disc, dict) and disc.get("id") == disc_id
                for disc in medium_discs
            ):
                continue
            position = medium.get("position")
            count = release.get("medium-count", len(media))
            if (
                type(position) is int and type(count) is int
                and 1 <= position <= count <= 1000
            ):
                disc_number, disc_count = position, count
            medium_tracks = medium.get("tracks", [])
            if not isinstance(medium_tracks, list):
                continue
            for track in medium_tracks:
                if not isinstance(track, dict):
                    continue
                try:
                    number = int(track.get("position", track.get("number")))
                except (TypeError, ValueError):
                    continue
                recording = track.get("recording", {})
                recording = recording if isinstance(recording, dict) else {}
                track_title = str(recording.get("title") or track.get("title") or "")[:240]
                track_artist = artist_name(recording.get("artist-credit")) or artist
                track_names[number] = (track_title, track_artist)
            break

    artwork = ""
    if release_id:
        try:
            artwork = save_artwork(release_id, disc_id)
        except (OSError, RuntimeError, urllib.error.URLError) as error:
            lookup_error = f"Album artwork could not be downloaded: {error}"
    disk_id = "audio:" + disc_id
    track_rows = []
    for toc_track in tracks:
        number = toc_track["number"]
        track_title, track_artist = track_names.get(number, ("", artist))
        shown_title = track_title or f"Track {number:02d}"
        shown = f"Track {number:02d} - {shown_title}"
        if track_artist and track_artist != artist:
            shown += f" - {track_artist}"
        track_rows.append((disk_id, shown[:1000], 0))
    external_url = f"https://musicbrainz.org/release/{release_id}" if release_id else (
        "https://musicbrainz.org/search?query=" + urllib.parse.quote(f"disc:{disc_id}") + "&type=release"
    )
    with connect() as db:
        # Replace an entry made by the old relative-offset calculation.
        legacy_tracks = [{**track, "offset": track["offset"] - 150} for track in tracks]
        legacy_id = "audio:" + musicbrainz_disc_id(legacy_tracks, leadout - 150)
        db.execute(
            "DELETE FROM disks WHERE id = ? AND kind = 'audio' AND source = ?",
            (legacy_id, device),
        )
        db.execute(
            """
            INSERT INTO disks(id, label, source, path, kind, scanned_at, file_count, size_bytes, artist, artwork, external_url, disc_number, disc_count)
            VALUES (?, ?, ?, ?, 'audio', datetime('now'), ?, 0, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET label=excluded.label, source=excluded.source,
                path=excluded.path, kind='audio', scanned_at=excluded.scanned_at,
                file_count=excluded.file_count, artist=excluded.artist,
                artwork=excluded.artwork, external_url=excluded.external_url,
                disc_number=excluded.disc_number, disc_count=excluded.disc_count
            """,
            (disk_id, title, device, device, len(track_rows), artist, artwork, external_url,
             disc_number, disc_count),
        )
        db.execute("DELETE FROM files WHERE disk_id = ?", (disk_id,))
        db.executemany("INSERT INTO files(disk_id, path, size_bytes) VALUES (?, ?, ?)", track_rows)
        edited = apply_disk_edits(db, disk_id)
    return {
        "diskId": disk_id,
        "discId": disc_id,
        "title": edited["label"],
        "artist": edited["artist"],
        "discNumber": edited["disc_number"],
        "discCount": edited["disc_count"],
        "tracks": len(track_rows),
        "artwork": artwork,
        "externalUrl": external_url,
        "identified": bool(release_id),
        "lookupError": lookup_error,
    }


def optical_drives() -> list[dict[str, object]]:
    drives = []
    for device in sorted(Path("/dev").glob("sr[0-9]*"))[:8]:
        item: dict[str, object] = {"device": str(device), "present": False, "discId": "", "tracks": 0}
        try:
            tracks, leadout = read_audio_toc(str(device))
            disc_id = musicbrainz_disc_id(tracks, leadout)
            item.update({
                "present": True,
                "discId": disc_id,
                "tracks": len(tracks),
                "catalogued": ("audio:" + disc_id) in catalog_ids(),
            })
        except (RuntimeError, subprocess.TimeoutExpired, OSError):
            pass
        drives.append(item)
    return drives


def catalog_ids() -> set[str]:
    with connect() as db:
        return {str(row["id"]) for row in db.execute("SELECT id FROM disks")}


def overview() -> dict[str, object]:
    if not STATUS_PATH.exists():
        set_scanning(False)
    with connect() as db:
        disks = [
            dict(row) for row in db.execute(
                """
                SELECT id, label, source, path, kind, scanned_at, file_count,
                       size_bytes, artist, artwork, external_url, disc_number, disc_count
                FROM disks ORDER BY scanned_at DESC, label COLLATE NOCASE
                """
            )
        ]
        tags: dict[str, list[str]] = {}
        for row in db.execute("SELECT disk_id, name FROM disk_tags ORDER BY name COLLATE NOCASE"):
            tags.setdefault(row["disk_id"], []).append(row["name"])
        for disk in disks:
            disk["tags"] = tags.get(disk["id"], [])
        file_count = int(db.execute("SELECT COUNT(*) FROM files").fetchone()[0])
    mounted = mount_entries()
    ids = {disk["id"] for disk in disks}
    for item in mounted:
        item["catalogued"] = item["id"] in ids
    return {
        "disks": disks,
        "diskCount": len(disks),
        "fileCount": file_count,
        "mounted": mounted,
        "audioDrives": optical_drives(),
        "mode": read_preferences()["mode"],
    }


def escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def search(first: str, second: str, disk_id: str = "") -> dict[str, object]:
    return search_terms([first[:300], second[:300]], disk_id)


def search_terms(terms: list[str], disk_id: str = "") -> dict[str, object]:
    if any(not isinstance(term, str) or len(term) > 300 for term in terms):
        raise ValueError("Filter terms must be text of at most 300 characters.")
    terms = [term.strip() for term in terms if term.strip()]
    conditions = ["(? = '' OR disks.id = ?)"]
    parameters: list[object] = [disk_id, disk_id]
    for term in terms:
        conditions.append(
            "(files.path LIKE ? ESCAPE '\\' COLLATE NOCASE OR EXISTS "
            "(SELECT 1 FROM disk_tags WHERE disk_tags.disk_id = disks.id "
            "AND disk_tags.name LIKE ? ESCAPE '\\' COLLATE NOCASE))"
        )
        parameters.extend(["%" + escape_like(term) + "%"] * 2)
    parameters.append(MAX_SEARCH_RESULTS + 1)
    with connect() as db:
        rows = db.execute(
            f"""
            SELECT files.path, files.size_bytes, disks.id AS disk_id,
                   disks.label, disks.kind, disks.artwork, disks.external_url,
                   disks.disc_number, disks.disc_count
            FROM files JOIN disks ON disks.id = files.disk_id
            WHERE {" AND ".join(conditions)}
            ORDER BY disks.label COLLATE NOCASE, files.path COLLATE NOCASE
            LIMIT ?
            """,
            parameters,
        ).fetchall()
    return {
        "results": [dict(row) for row in rows[:MAX_SEARCH_RESULTS]],
        "truncated": len(rows) > MAX_SEARCH_RESULTS,
    }


def delete_disk(disk_id: str) -> dict[str, object]:
    result = delete_disks([disk_id])
    return {
        "diskId": disk_id,
        "label": result["labels"][0],
        "deleted": True,
    }


def delete_disks(disk_ids: list[str]) -> dict[str, object]:
    if not disk_ids or len(disk_ids) > 500:
        raise ValueError("Choose between 1 and 500 disks to remove.")
    if any(not disk_id or len(disk_id) > 256 for disk_id in disk_ids):
        raise ValueError("Choose valid disks from the library.")
    disk_ids = list(dict.fromkeys(disk_ids))
    placeholders = ",".join("?" for _ in disk_ids)
    with connect() as db:
        disks = db.execute(
            f"SELECT id, label FROM disks WHERE id IN ({placeholders})",
            disk_ids,
        ).fetchall()
        if len(disks) != len(disk_ids):
            raise ValueError("One or more selected disks are no longer in the library.")
        db.executemany("DELETE FROM disks WHERE id = ?", ((disk_id,) for disk_id in disk_ids))
    return {
        "diskIds": disk_ids,
        "labels": [str(disk["label"]) for disk in disks],
        "deleted": len(disk_ids),
    }


def library_xml(name: str, value: object) -> ET.Element:
    element = ET.Element(name)
    if isinstance(value, dict):
        element.set("type", "object")
        for key, child in value.items():
            element.append(library_xml(key, child))
    elif isinstance(value, list):
        element.set("type", "array")
        for child in value:
            element.append(library_xml("item", child))
    elif value is None:
        element.set("type", "null")
    elif type(value) is int:
        element.set("type", "integer")
        element.text = str(value)
    elif isinstance(value, str):
        if re.search(r"[^\x09\x0a\x0d\x20-\ud7ff\ue000-\ufffd\U00010000-\U0010ffff]", value):
            raise ValueError("This library contains text XML cannot represent. Export as JSON instead.")
        element.set("type", "string")
        element.text = value
    else:
        raise ValueError("Unsupported library value.")
    return element


def read_library_xml(element: ET.Element, depth: int = 0) -> object:
    if depth > 16 or set(element.attrib) != {"type"}:
        raise ValueError("Invalid OmaShelf XML structure.")
    kind = element.get("type")
    if kind == "object":
        if len({child.tag for child in element}) != len(element):
            raise ValueError("Duplicate fields in OmaShelf XML.")
        return {child.tag: read_library_xml(child, depth + 1) for child in element}
    if kind == "array":
        if any(child.tag != "item" for child in element):
            raise ValueError("Invalid array in OmaShelf XML.")
        return [read_library_xml(child, depth + 1) for child in element]
    if len(element):
        raise ValueError("Unexpected nested value in OmaShelf XML.")
    if kind == "null" and not element.text:
        return None
    if kind == "integer":
        return int(element.text or "")
    if kind == "string":
        return element.text or ""
    raise ValueError("Invalid value type in OmaShelf XML.")


def artwork_bytes(data: bytes, content_type: str) -> bytes:
    valid = {
        "image/jpeg": data.startswith(b"\xff\xd8\xff"),
        "image/png": data.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/webp": data.startswith(b"RIFF") and data[8:12] == b"WEBP",
    }
    if len(data) > MAX_ARTWORK_BYTES or not valid.get(content_type, False):
        raise ValueError("Library artwork must be a JPEG, PNG, or WebP of at most 5 MB.")
    return data


def export_cover(url: str) -> object:
    if not url:
        return None
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "file" or parsed.netloc:
        raise ValueError("Only artwork in OmaShelf's local cache can be exported.")
    path = Path(urllib.parse.unquote(parsed.path)).resolve()
    if not path.is_relative_to((DATA_DIR / "artwork").resolve()):
        raise ValueError("Artwork is outside OmaShelf's cache.")
    content_type = {".jpg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}.get(path.suffix.lower(), "")
    with path.open("rb") as stream:
        data = artwork_bytes(stream.read(MAX_ARTWORK_BYTES + 1), content_type)
    return {"type": content_type, "data": base64.b64encode(data).decode("ascii")}


def write_library_file(path: Path, payload: bytes) -> None:
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as stream:
            temporary_path = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def export_library(path_text: str) -> dict[str, object]:
    path = Path(path_text).expanduser().absolute()
    if path.suffix.lower() not in {".json", ".xml"}:
        raise ValueError("Choose a .json or .xml export filename.")
    if path.resolve() in {DB_PATH.resolve(), STATUS_PATH.resolve(), PREFERENCES_PATH.resolve()}:
        raise ValueError("Choose an export file outside OmaShelf's database and settings files.")
    with closing(connect()) as db, db:
        db.execute("BEGIN")
        disks = []
        for row in db.execute("SELECT * FROM disks ORDER BY id"):
            disk = {field: row[field] for field in LIBRARY_FIELDS}
            disk["tags"] = [tag["name"] for tag in db.execute(
                "SELECT name FROM disk_tags WHERE disk_id = ? ORDER BY name", (row["id"],)
            )]
            edits = db.execute("SELECT metadata FROM disk_edits WHERE disk_id = ?", (row["id"],)).fetchone()
            disk["edits"] = json.loads(edits["metadata"]) if edits else {}
            disk["cover"] = export_cover(row["artwork"])
            disk["files"] = [dict(file) for file in db.execute(
                "SELECT path, size_bytes FROM files WHERE disk_id = ? ORDER BY id", (row["id"],)
            )]
            disks.append(disk)
    document = {"format": "OmaShelf", "version": 1, "disks": disks}
    validate_library(document)
    if path.suffix.lower() == ".xml":
        root = library_xml("omashelf", document)
        ET.indent(root)
        payload = ET.tostring(root, encoding="utf-8", xml_declaration=True).replace(b"\r", b"&#13;")
    else:
        payload = json.dumps(document, ensure_ascii=True, indent=2).encode("utf-8")
    if len(payload) > MAX_LIBRARY_BYTES:
        raise ValueError("The export exceeds the 256 MB library-file limit.")
    write_library_file(path, payload)
    return {"path": str(path), "diskCount": len(disks), "fileCount": sum(len(disk["files"]) for disk in disks)}


def validate_library(document: object) -> list[dict[str, object]]:
    if (
        not isinstance(document, dict) or set(document) != {"format", "version", "disks"}
        or document["format"] != "OmaShelf" or type(document["version"]) is not int
        or document["version"] != 1
    ):
        raise ValueError("Choose a supported OmaShelf library export (version 1).")
    disks = document["disks"]
    if not isinstance(disks, list) or len(disks) > 10_000:
        raise ValueError("A library import can contain at most 10,000 discs.")
    seen = set()
    total_files = 0
    limits = {"id": 256, "label": 240, "source": 4096, "path": 4096, "kind": 10,
              "scanned_at": 32, "artist": EDIT_FIELDS["artist"], "external_url": 4096}
    for disk in disks:
        if not isinstance(disk, dict) or set(disk) != {*LIBRARY_FIELDS, "tags", "edits", "cover", "files"}:
            raise ValueError("An imported disc has missing or unsupported fields.")
        for field, limit in limits.items():
            value = disk[field]
            if not isinstance(value, str) or len(value) > limit or "\x00" in value:
                raise ValueError(f"Invalid imported disc field: {field}.")
            value.encode("utf-8")
        if not all(disk[field].strip() for field in ("id", "label", "path")) or disk["id"] in seen:
            raise ValueError("Imported discs need nonempty labels, locations, and unique IDs.")
        seen.add(disk["id"])
        if disk["kind"] not in {"data", "audio"}:
            raise ValueError("Imported disc type must be data or audio.")
        validate_edit_fields({field: disk[field] for field in (*EDIT_FIELDS, "disc_number", "disc_count")})
        if disk["kind"] != "audio" and disk["disc_number"] is not None:
            raise ValueError("Only imported audio CDs can have CD numbering.")
        edits = validate_edit_fields(disk["edits"])
        if any(disk[field] != value for field, value in edits.items()):
            raise ValueError("Saved edits do not match the imported disc metadata.")
        for tag in normalize_tags(disk["tags"]).values():
            if "\x00" in tag:
                raise ValueError("Invalid imported tag.")
            tag.encode("utf-8")
        if not re.fullmatch(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d", disk["scanned_at"]):
            raise ValueError("Invalid imported scan timestamp.")
        datetime.strptime(disk["scanned_at"], "%Y-%m-%d %H:%M:%S")
        if disk["external_url"]:
            url = urllib.parse.urlparse(disk["external_url"])
            if url.scheme != "https" or url.netloc != "musicbrainz.org":
                raise ValueError("Imported metadata links must use https://musicbrainz.org.")
        files = disk["files"]
        if not isinstance(files, list) or len(files) > MAX_FILES:
            raise ValueError("An imported disc exceeds the 200,000-file limit.")
        total_files += len(files)
        if total_files > 1_000_000:
            raise ValueError("A library import can contain at most 1,000,000 indexed files.")
        for field in ("file_count", "size_bytes"):
            if type(disk[field]) is not int or not 0 <= disk[field] <= 2**63 - 1:
                raise ValueError(f"Invalid imported {field}.")
        if disk["file_count"] != len(files):
            raise ValueError("An imported disc's file count does not match its file list.")
        for file in files:
            if not isinstance(file, dict) or set(file) != {"path", "size_bytes"}:
                raise ValueError("Invalid imported file entry.")
            if not isinstance(file["path"], str) or not 1 <= len(file["path"]) <= 4096 or "\x00" in file["path"]:
                raise ValueError("Invalid imported file path.")
            file["path"].encode("utf-8")
            if type(file["size_bytes"]) is not int or not 0 <= file["size_bytes"] <= 2**63 - 1:
                raise ValueError("Invalid imported file size.")
        cover = disk["cover"]
        if cover is not None:
            if (
                not isinstance(cover, dict) or set(cover) != {"type", "data"}
                or not isinstance(cover["type"], str) or not isinstance(cover["data"], str)
                or len(cover["data"]) > (MAX_ARTWORK_BYTES + 2) // 3 * 4
            ):
                raise ValueError("Invalid imported artwork.")
            try:
                artwork_bytes(base64.b64decode(cover["data"], validate=True), cover["type"])
            except binascii.Error as error:
                raise ValueError("Invalid base64 artwork in library.") from error
    return disks


def read_library(path_text: str) -> tuple[list[dict[str, object]], str]:
    path = Path(path_text).expanduser()
    if path.suffix.lower() not in {".json", ".xml"}:
        raise ValueError("Choose an OmaShelf .json or .xml library export.")
    with path.open("rb") as stream:
        payload = stream.read(MAX_LIBRARY_BYTES + 1)
    if len(payload) > MAX_LIBRARY_BYTES:
        raise ValueError("The import exceeds the 256 MB library-file limit.")
    try:
        text = payload.decode("utf-8-sig")
        if path.suffix.lower() == ".xml":
            if re.search(r"<!\s*(DOCTYPE|ENTITY)\b", text, re.IGNORECASE):
                raise ValueError("XML document types and entities are not supported.")
            root = ET.fromstring(text)
            if root.tag != "omashelf":
                raise ValueError("Choose an OmaShelf XML library export.")
            document = read_library_xml(root)
        else:
            document = json.loads(text)
        disks = validate_library(document)
    except (UnicodeError, ET.ParseError, json.JSONDecodeError, RecursionError) as error:
        raise ValueError(f"Could not read the library export: {error}") from error
    return disks, hashlib.sha256(payload).hexdigest()


def inspect_import(path_text: str) -> dict[str, object]:
    disks, fingerprint = read_library(path_text)
    with closing(connect()) as db:
        ids = {row["id"] for row in db.execute("SELECT id FROM disks")}
    return {
        "path": str(Path(path_text).expanduser().absolute()), "fingerprint": fingerprint,
        "diskCount": len(disks), "fileCount": sum(len(disk["files"]) for disk in disks),
        "matchingCount": sum(disk["id"] in ids for disk in disks), "existingCount": len(ids),
    }


def import_library(path_text: str, mode: str, conflicts: str, fingerprint: str) -> dict[str, object]:
    if mode not in {"merge", "replace"} or conflicts not in {"keep", "overwrite"}:
        raise ValueError("Choose merge or replace and a matching-disc policy.")
    disks, actual_fingerprint = read_library(path_text)
    if actual_fingerprint != fingerprint:
        raise ValueError("The import file changed. Select it again and review the new preview.")
    added = updated = skipped = 0
    with closing(connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        existing = {row["id"] for row in db.execute("SELECT id FROM disks")}
        if mode == "replace":
            db.execute("DELETE FROM disks")
        for disk in disks:
            disk_id = disk["id"]
            matching = disk_id in existing
            if mode == "merge" and matching and conflicts == "keep":
                skipped += 1
                continue
            artwork = ""
            if disk["cover"] is not None:
                cover = disk["cover"]
                data = base64.b64decode(cover["data"], validate=True)
                extension = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}[cover["type"]]
                art_dir = DATA_DIR / "artwork"
                art_dir.mkdir(parents=True, exist_ok=True)
                art_path = art_dir / (hashlib.sha256(data).hexdigest() + extension)
                write_library_file(art_path, data)
                artwork = art_path.as_uri()
            db.execute("DELETE FROM disks WHERE id = ?", (disk_id,))
            db.execute(
                "INSERT INTO disks(" + ",".join(LIBRARY_FIELDS) + ",artwork) VALUES ("
                + ",".join("?" for _ in range(len(LIBRARY_FIELDS) + 1)) + ")",
                [disk[field] for field in LIBRARY_FIELDS] + [artwork],
            )
            db.executemany("INSERT INTO files(disk_id, path, size_bytes) VALUES (?, ?, ?)",
                           ((disk_id, file["path"], file["size_bytes"]) for file in disk["files"]))
            db.executemany("INSERT INTO disk_tags(disk_id, name) VALUES (?, ?)",
                           ((disk_id, tag) for tag in normalize_tags(disk["tags"]).values()))
            if disk["edits"]:
                db.execute("INSERT INTO disk_edits(disk_id, metadata) VALUES (?, ?)",
                           (disk_id, json.dumps(disk["edits"])))
            if mode == "merge" and matching:
                updated += 1
            else:
                added += 1
    return {"added": added, "updated": updated, "skipped": skipped, "mode": mode}


def dispatch(arguments: list[str]) -> dict[str, object]:
    if not arguments or arguments[0] == "overview":
        return overview()
    command = arguments[0]
    if command == "scan" and len(arguments) == 2:
        return scan_directory(arguments[1])
    if command == "search" and len(arguments) in {3, 4}:
        disk_id = arguments[3] if len(arguments) == 4 else ""
        return search(arguments[1], arguments[2], disk_id)
    if command == "search-terms" and len(arguments) >= 2:
        return search_terms(arguments[2:], arguments[1])
    if command == "edit-disk" and len(arguments) == 3:
        return edit_disk(arguments[1], json.loads(arguments[2]))
    if command == "edit-disks" and len(arguments) == 3:
        return edit_disks(json.loads(arguments[1]), json.loads(arguments[2]))
    if command == "export-library" and len(arguments) == 2:
        return export_library(arguments[1])
    if command == "inspect-import" and len(arguments) == 2:
        return inspect_import(arguments[1])
    if command == "import-library" and len(arguments) == 5:
        return import_library(*arguments[1:])
    if command == "delete-disk" and len(arguments) == 2:
        return delete_disk(arguments[1])
    if command == "delete-disks" and 2 <= len(arguments) <= 501:
        return delete_disks(arguments[1:])
    if command == "identify-audio" and len(arguments) == 2:
        set_scanning(True, "Identifying audio CD")
        try:
            return identify_audio(arguments[1])
        finally:
            set_scanning(False)
    if command == "set-mode" and len(arguments) == 2:
        return set_mode(arguments[1])
    if command == "mode":
        return read_preferences()
    raise ValueError("Unknown OmaShelf command.")


def main() -> int:
    try:
        os.umask(0o077)
        ensure_private_data_dir()
        arguments = sys.argv[1:]
        if arguments == ["--stdin"]:
            request = sys.stdin.buffer.readline(MAX_REQUEST_BYTES + 1)
            if len(request) > MAX_REQUEST_BYTES or not request.endswith(b"\n"):
                raise ValueError("Invalid or oversized OmaShelf request.")
            arguments = json.loads(request)
            if not isinstance(arguments, list) or not arguments or any(
                not isinstance(argument, str) for argument in arguments
            ):
                raise ValueError("Invalid OmaShelf request.")
        print(json.dumps({"ok": True, **dispatch(arguments)}, ensure_ascii=False))
        return 0
    except (
        OSError, ValueError, RuntimeError, sqlite3.Error, subprocess.SubprocessError,
        urllib.error.URLError, json.JSONDecodeError,
    ) as error:
        message = str(error)
        try:
            set_scanning(False)
        except OSError as status_error:
            message += f" Could not reset scan status: {status_error}"
        print(json.dumps({"ok": False, "error": message[:1000]}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
