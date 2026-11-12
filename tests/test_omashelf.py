import importlib.util
import json
import copy
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).parents[1] / "bin" / "omashelf.py"
SPEC = importlib.util.spec_from_file_location("omashelf", SCRIPT)
omashelf = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(omashelf)


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.data_dir = Path(self.temporary.name) / "data"
        self.media_dir = Path(self.temporary.name) / "disc"
        self.media_dir.mkdir()
        (self.media_dir / "A song [live].mp3").write_bytes(b"audio")
        (self.media_dir / "100% complete.txt").write_text("catalog me", encoding="utf-8")
        self.data_patch = patch.multiple(
            omashelf,
            DATA_DIR=self.data_dir,
            DB_PATH=self.data_dir / "catalog.sqlite3",
            STATUS_PATH=self.data_dir / "status.json",
            PREFERENCES_PATH=self.data_dir / "preferences.json",
        )
        self.data_patch.start()
        self.addCleanup(self.data_patch.stop)

    def test_scanning_and_two_independent_literal_search_filters(self):
        with patch.object(omashelf, "mount_for_path", return_value={}):
            result = omashelf.scan_directory(str(self.media_dir))
        self.assertEqual(result["files"], 2)
        self.assertTrue(omashelf.search("song", "live")["results"])
        self.assertEqual(omashelf.search("song", "missing")["results"], [])
        self.assertEqual(len(omashelf.search("100%", "complete")["results"]), 1)
        self.assertEqual(omashelf.search("_", "")["results"], [])
        self.assertEqual(len(omashelf.search("", "", result["diskId"])["results"]), 2)

    def test_scan_limit_stops_before_visiting_sibling_directories_and_allows_backups(self):
        media = self.media_dir / "limited"
        for name in ("a", "b", "c"):
            directory = media / name
            directory.mkdir(parents=True)
            for index in range(3):
                (directory / f"example-{index}.txt").write_bytes(b"fixture")
        with (
            patch.object(omashelf, "MAX_FILES", 2),
            patch.object(omashelf, "mount_for_path", return_value={}),
        ):
            result = omashelf.scan_directory(str(media))
            self.assertEqual(result["files"], 2)
            self.assertTrue(result["partial"])
            self.assertEqual(len(result["errors"]), 1)
            self.assertIn("safety limit", result["errors"][0])
            path = Path(self.temporary.name) / "limited.json"
            self.assertEqual(omashelf.export_library(str(path))["fileCount"], 2)
            disks, _ = omashelf.read_library(str(path))
            self.assertEqual(len(disks[0]["files"]), 2)
            self.assertTrue(all(file["path"].startswith("a/") for file in disks[0]["files"]))

    def test_overview_exposes_the_entire_library_beyond_500_discs(self):
        ids = {f"fixture:{index}" for index in range(501)}
        with omashelf.connect() as db:
            db.executemany(
                "INSERT INTO disks(id, label, path, kind, scanned_at) "
                "VALUES (?, ?, 'Shelf A', 'data', datetime('now'))",
                [(disk_id, f"Fictional disc {index:03d}") for index, disk_id in enumerate(sorted(ids))],
            )
        with (
            patch.object(omashelf, "mount_entries", return_value=[]),
            patch.object(omashelf, "optical_drives", return_value=[]),
        ):
            overview = omashelf.overview()
        self.assertEqual(overview["diskCount"], 501)
        self.assertEqual({disk["id"] for disk in overview["disks"]}, ids)

    def test_term_filters_match_all_terms_and_can_be_removed(self):
        (self.media_dir / "A song [studio].mp3").write_bytes(b"audio")
        with patch.object(omashelf, "mount_for_path", return_value={}):
            disk = omashelf.scan_directory(str(self.media_dir))
        terms = ["SONG", "[live]", ".mp3"]
        rows = omashelf.dispatch(["search-terms", disk["diskId"], *terms])["results"]
        self.assertEqual([row["path"] for row in rows], ["A song [live].mp3"])
        self.assertEqual(omashelf.search_terms(terms + ["missing"])["results"], [])
        self.assertEqual(len(omashelf.search_terms(["song", ".mp3"])["results"]), 2)
        self.assertEqual(len(omashelf.search_terms([])["results"]), 3)
        self.assertEqual(omashelf.search_terms(["song"], "other-disk")["results"], [])
        self.assertEqual(len(omashelf.search_terms(["100%", "complete"])["results"]), 1)
        self.assertEqual(omashelf.search_terms(["_"])["results"], [])
        self.assertEqual(omashelf.search_terms(["' OR 1=1 --"])["results"], [])
        self.assertEqual(omashelf.search_terms(["<img src=x>"])["results"], [])
        with self.assertRaises(ValueError):
            omashelf.search_terms(["x" * 301])

    def test_musicbrainz_disc_id_is_stable_and_uses_supported_alphabet(self):
        toc = [
            {"number": 1, "length": 15213, "offset": 150},
            {"number": 2, "length": 16801, "offset": 15363},
            {"number": 3, "length": 14278, "offset": 32314},
            {"number": 4, "length": 16772, "offset": 46592},
            {"number": 5, "length": 17075, "offset": 63414},
            {"number": 6, "length": 14973, "offset": 80489},
        ]
        first = omashelf.musicbrainz_disc_id(toc, 95462)
        self.assertEqual(first, omashelf.musicbrainz_disc_id(toc, 95462))
        self.assertEqual(first, "49HHV7Eb8UKF3aQiNmu1GR8vKTY-")
        self.assertRegex(first, r"^[A-Za-z0-9._-]{28}$")

    def edit_values(self, disk_id, **changes):
        with omashelf.connect() as db:
            row = db.execute("SELECT * FROM disks WHERE id = ?", (disk_id,)).fetchone()
        values = {field: row[field] for field in ("label", "artist", "path", "disc_number", "disc_count")}
        return {**values, "tags": [], **changes}

    def test_editing_and_tag_filters_persist_across_rescanning(self):
        with patch.object(omashelf, "mount_for_path", return_value={}):
            disk_id = omashelf.scan_directory(str(self.media_dir))["diskId"]
        values = self.edit_values(
            disk_id, label="Custom label", artist="Creator", path="Shelf A",
            tags=[" Game ", "game", "ProjectX", "100%", "<img src=x>"],
        )
        self.assertTrue(omashelf.dispatch(["edit-disk", disk_id, json.dumps(values)])["saved"])
        self.assertEqual(len(omashelf.search_terms(["GAME", "projectx", "song"])["results"]), 1)
        self.assertEqual(len(omashelf.search_terms(["100%"])["results"]), 2)
        self.assertEqual(omashelf.search_terms(["100_"])["results"], [])
        self.assertEqual(len(omashelf.search_terms(["<img src=x>"])["results"]), 2)
        self.assertEqual(omashelf.search_terms(["Game"], "other-disc")["results"], [])
        with patch.object(omashelf, "mount_for_path", return_value={}):
            rescanned = omashelf.scan_directory(str(self.media_dir))
        self.assertEqual((rescanned["label"], rescanned["path"]), ("Custom label", "Shelf A"))
        with (
            patch.object(omashelf, "mount_entries", return_value=[]),
            patch.object(omashelf, "optical_drives", return_value=[]),
        ):
            disk = omashelf.overview()["disks"][0]
        self.assertEqual(disk["artist"], "Creator")
        self.assertEqual(set(disk["tags"]), {"Game", "ProjectX", "100%", "<img src=x>"})
        omashelf.edit_disk(disk_id, self.edit_values(disk_id, tags=["Data"]))
        self.assertEqual(omashelf.search_terms(["Game"])["results"], [])
        self.assertEqual(len(omashelf.search_terms(["Data", "song"])["results"]), 1)
        omashelf.delete_disk(disk_id)
        with omashelf.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM disk_tags").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM disk_edits").fetchone()[0], 0)

    def test_audio_edits_survive_reidentification(self):
        tracks = [{"number": 1, "length": 1000, "offset": 150}]
        with (
            patch.object(omashelf, "read_audio_toc", return_value=(tracks, 1150)),
            patch.object(omashelf, "fetch_json", return_value={"releases": []}),
        ):
            disk_id = omashelf.identify_audio("/dev/sr0")["diskId"]
            omashelf.edit_disk(disk_id, self.edit_values(
                disk_id, label="My album", artist="My artist", path="CD wallet",
                disc_number=2, disc_count=3, tags=["Game"],
            ))
            result = omashelf.identify_audio("/dev/sr0")
        self.assertEqual((result["title"], result["artist"]), ("My album", "My artist"))
        self.assertEqual((result["discNumber"], result["discCount"]), (2, 3))
        self.assertEqual(len(omashelf.search_terms(["Game", "Track"])["results"]), 1)
        with omashelf.connect() as db:
            row = db.execute("SELECT path FROM disks WHERE id = ?", (disk_id,)).fetchone()
        self.assertEqual(row["path"], "CD wallet")

    def test_long_musicbrainz_credits_survive_editing_and_json_xml_backups(self):
        tracks = [{"number": 1, "length": 1000, "offset": 150}]
        credits = [{"name": f"Fictional performer {index} " + "\U0001f3b5" * 216} for index in range(8)]
        artist = ", ".join(credit["name"] for credit in credits)
        self.assertGreater(len(artist), 240)
        response = {"releases": [{"title": "Ensemble album", "artist-credit": credits}]}
        with (
            patch.object(omashelf, "read_audio_toc", return_value=(tracks, 1150)),
            patch.object(omashelf, "fetch_json", return_value=response),
        ):
            result = omashelf.identify_audio("/dev/sr0")
        self.assertEqual(result["artist"], artist)
        disk_id = result["diskId"]
        omashelf.edit_disk(disk_id, self.edit_values(disk_id, label="Edited ensemble album"))
        for suffix in ("json", "xml"):
            with self.subTest(format=suffix):
                path = Path(self.temporary.name) / f"ensemble.{suffix}"
                omashelf.export_library(str(path))
                disks, _ = omashelf.read_library(str(path))
                self.assertEqual(disks[0]["artist"], artist)
                self.assertEqual(disks[0]["edits"]["label"], "Edited ensemble album")
                preview = omashelf.inspect_import(str(path))
                omashelf.import_library(str(path), "replace", "keep", preview["fingerprint"])
                with omashelf.connect() as db:
                    row = db.execute("SELECT artist FROM disks WHERE id = ?", (disk_id,)).fetchone()
                self.assertEqual(row["artist"], artist)

    def test_invalid_edits_leave_catalog_unchanged(self):
        with patch.object(omashelf, "mount_for_path", return_value={}):
            disk_id = omashelf.scan_directory(str(self.media_dir))["diskId"]
        for changes in (
            {"label": ""}, {"path": " "}, {"label": "x" * 241}, {"artist": "x" * 4097},
            {"disc_number": 2, "disc_count": 1}, {"disc_number": 1},
            {"disc_number": 1, "disc_count": 2},
            {"disc_number": True, "disc_count": 2},
            {"tags": [""]}, {"tags": "Game"}, {"tags": [42]}, {"unknown": "value"},
        ):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    omashelf.edit_disk(disk_id, self.edit_values(disk_id, **changes))
        with self.assertRaises(ValueError):
            omashelf.edit_disk("missing", self.edit_values(disk_id))
        with omashelf.connect() as db:
            self.assertEqual(db.execute("SELECT label FROM disks").fetchone()[0], self.media_dir.name)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM disk_edits").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM disk_tags").fetchone()[0], 0)

    def test_cdparanoia_offsets_include_the_musicbrainz_lead_in(self):
        output = (
            "  1. 15213 [03:22.63] 0 [00:00.00] no no 2\n"
            "  2. 16801 [03:44.01] 15213 [03:22.63] no no 2\n"
            "TOTAL 32014 [07:06.64] (audio only)\n"
        )
        result = subprocess.CompletedProcess([], 0, stdout="", stderr=output)
        with patch.object(omashelf.subprocess, "run", return_value=result):
            tracks, leadout = omashelf.read_audio_toc("/dev/sr0")
        self.assertEqual([track["offset"] for track in tracks], [150, 15363])
        self.assertEqual(leadout, 32164)

    def test_identification_uses_the_matching_disc_on_a_multidisc_release(self):
        tracks = [{"number": 1, "length": 1000, "offset": 150}]
        leadout = 1150
        disc_id = omashelf.musicbrainz_disc_id(tracks, leadout)
        legacy_id = "audio:" + omashelf.musicbrainz_disc_id(
            [{"number": 1, "length": 1000, "offset": 0}], 1000
        )
        with omashelf.connect() as db:
            db.execute(
                "INSERT INTO disks(id, label, source, path, kind, scanned_at) "
                "VALUES (?, 'Audio CD', '/dev/sr0', '/dev/sr0', 'audio', datetime('now'))",
                (legacy_id,),
            )
            db.execute(
                "INSERT INTO files(disk_id, path) VALUES (?, 'Track 01')", (legacy_id,)
            )
        response = {"releases": [{
            "id": "4610a9f6-f6d3-43bd-a83e-554e37d24d4e",
            "title": "Original soundtrack",
            "artist-credit": [{"name": "Composer"}],
            "media": [
                {"position": 1, "discs": [{"id": "other-disc"}], "tracks": [
                    {"position": 1, "recording": {"title": "Wrong disc track"}}
                ]},
                {"position": 2, "discs": [{"id": disc_id}], "tracks": [
                    {"position": 1, "recording": {"title": "Correct disc track"}}
                ]},
            ],
        }]}
        with (
            patch.object(omashelf, "read_audio_toc", return_value=(tracks, leadout)),
            patch.object(omashelf, "fetch_json", return_value=response),
            patch.object(omashelf, "save_artwork", return_value="file:///artwork.jpg"),
        ):
            result = omashelf.identify_audio("/dev/sr0")
        self.assertTrue(result["identified"])
        self.assertEqual(result["title"], "Original soundtrack")
        self.assertEqual(result["artist"], "Composer")
        self.assertEqual(result["artwork"], "file:///artwork.jpg")
        self.assertEqual((result["discNumber"], result["discCount"]), (2, 2))
        with (
            patch.object(omashelf, "mount_entries", return_value=[]),
            patch.object(omashelf, "optical_drives", return_value=[]),
        ):
            disk = omashelf.overview()["disks"][0]
        self.assertEqual((disk["disc_number"], disk["disc_count"]), (2, 2))
        self.assertNotIn(legacy_id, omashelf.catalog_ids())
        rows = omashelf.search("", "")["results"]
        self.assertEqual(len(rows), 1)
        self.assertIn("Correct disc track", rows[0]["path"])
        self.assertEqual((rows[0]["disc_number"], rows[0]["disc_count"]), (2, 2))

    def test_disc_numbering_handles_single_disc_and_missing_or_invalid_metadata(self):
        tracks = [{"number": 1, "length": 1000, "offset": 150}]
        disc_id = omashelf.musicbrainz_disc_id(tracks, 1150)
        for position, count, expected in (
            (1, 1, (1, 1)),
            (3, 3, (3, 3)),
            (None, 2, (None, None)),
            (0, 2, (None, None)),
            (3, 2, (None, None)),
            ("2", 2, (None, None)),
        ):
            with self.subTest(position=position, count=count):
                response = {"releases": [{
                    "id": "4610a9f6-f6d3-43bd-a83e-554e37d24d4e",
                    "title": "Album",
                    "medium-count": count,
                    "media": [{"position": position, "discs": [{"id": disc_id}]}],
                }]}
                with (
                    patch.object(omashelf, "read_audio_toc", return_value=(tracks, 1150)),
                    patch.object(omashelf, "fetch_json", return_value=response),
                    patch.object(omashelf, "save_artwork", return_value=""),
                ):
                    result = omashelf.identify_audio("/dev/sr0")
                self.assertEqual((result["discNumber"], result["discCount"]), expected)
                row = omashelf.search("", "")["results"][0]
                self.assertEqual((row["disc_number"], row["disc_count"]), expected)

    def test_existing_catalog_is_migrated_without_losing_disks(self):
        self.data_dir.mkdir()
        with omashelf.sqlite3.connect(omashelf.DB_PATH) as db:
            db.execute("""
                CREATE TABLE disks (
                    id TEXT PRIMARY KEY, label TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT '', path TEXT NOT NULL,
                    kind TEXT NOT NULL, scanned_at TEXT NOT NULL,
                    file_count INTEGER NOT NULL DEFAULT 0,
                    size_bytes INTEGER NOT NULL DEFAULT 0,
                    artist TEXT NOT NULL DEFAULT '', artwork TEXT NOT NULL DEFAULT '',
                    external_url TEXT NOT NULL DEFAULT ''
                )
            """)
            db.execute(
                "INSERT INTO disks(id, label, path, kind, scanned_at) "
                "VALUES ('old-disc', 'Existing album', '/dev/sr0', 'audio', datetime('now'))"
            )
        with omashelf.connect() as db:
            disk = db.execute("SELECT * FROM disks").fetchone()
            self.assertEqual(disk["label"], "Existing album")
            self.assertIsNone(disk["disc_number"])
            self.assertIsNone(disk["disc_count"])
        with omashelf.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM disks").fetchone()[0], 1)

    def test_unmatched_cd_reports_why_metadata_is_missing(self):
        tracks = [{"number": 1, "length": 1000, "offset": 150}]
        with (
            patch.object(omashelf, "read_audio_toc", return_value=(tracks, 1150)),
            patch.object(omashelf, "fetch_json", return_value={"releases": []}),
        ):
            result = omashelf.identify_audio("/dev/sr0")
        self.assertFalse(result["identified"])
        self.assertIsNone(result["discNumber"])
        self.assertIsNone(result["discCount"])
        self.assertIn("no matching release", result["lookupError"])
        self.assertEqual(len(omashelf.search("", "")["results"]), 1)

    def test_mode_is_validated_and_persisted(self):
        self.assertEqual(omashelf.set_mode("app"), {"mode": "app"})
        self.assertEqual(omashelf.read_preferences(), {"mode": "app"})
        with self.assertRaises(ValueError):
            omashelf.set_mode("unexpected")

    def test_deleting_a_disk_removes_its_indexed_files(self):
        with patch.object(omashelf, "mount_for_path", return_value={}):
            scanned = omashelf.scan_directory(str(self.media_dir))
        deleted = omashelf.delete_disk(scanned["diskId"])
        self.assertTrue(deleted["deleted"])
        self.assertEqual(omashelf.search("", "")["results"], [])
        with self.assertRaises(ValueError):
            omashelf.delete_disk(scanned["diskId"])

    def test_bulk_edits_preserve_unchecked_fields_and_support_all_tag_operations(self):
        second_dir = Path(self.temporary.name) / "second"
        second_dir.mkdir()
        (second_dir / "second.txt").write_text("second", encoding="utf-8")
        with patch.object(omashelf, "mount_for_path", return_value={}):
            ids = [
                omashelf.scan_directory(str(self.media_dir))["diskId"],
                omashelf.scan_directory(str(second_dir))["diskId"],
            ]
        for disk_id, tag in zip(ids, ("Game", "Data")):
            omashelf.edit_disk(disk_id, self.edit_values(disk_id, artist="Creator", tags=[tag]))
        changes = {"fields": {"path": "Shelf B", "artist": ""}, "tagOperation": "keep", "tags": []}
        result = omashelf.dispatch(["edit-disks", json.dumps(ids), json.dumps(changes)])
        self.assertEqual(result["updated"], 2)
        with omashelf.connect() as db:
            rows = {row["id"]: dict(row) for row in db.execute("SELECT * FROM disks")}
        self.assertEqual([rows[disk_id]["label"] for disk_id in ids], ["disc", "second"])
        self.assertTrue(all(rows[disk_id]["artist"] == "" for disk_id in ids))
        self.assertTrue(all(rows[disk_id]["path"] == "Shelf B" for disk_id in ids))
        self.assertEqual(len(omashelf.search_terms(["Game"])["results"]), 2)
        with patch.object(omashelf, "mount_for_path", return_value={}):
            self.assertEqual(omashelf.scan_directory(str(self.media_dir))["path"], "Shelf B")

        def tags_for(disk_id):
            with omashelf.connect() as db:
                return {row["name"] for row in db.execute(
                    "SELECT name FROM disk_tags WHERE disk_id = ?", (disk_id,)
                )}

        omashelf.edit_disks(ids, {"fields": {}, "tagOperation": "add", "tags": ["game", "ProjectX"]})
        self.assertEqual(tags_for(ids[0]), {"Game", "ProjectX"})
        self.assertEqual(tags_for(ids[1]), {"Data", "game", "ProjectX"})
        omashelf.edit_disks(ids, {"fields": {}, "tagOperation": "remove", "tags": ["GAME"]})
        self.assertEqual(tags_for(ids[0]), {"ProjectX"})
        self.assertEqual(tags_for(ids[1]), {"Data", "ProjectX"})
        omashelf.edit_disks(ids, {"fields": {}, "tagOperation": "replace", "tags": ["New"]})
        self.assertTrue(all(tags_for(disk_id) == {"New"} for disk_id in ids))
        omashelf.edit_disks(ids, {"fields": {}, "tagOperation": "replace", "tags": []})
        self.assertTrue(all(tags_for(disk_id) == set() for disk_id in ids))

    def test_bulk_edit_failures_roll_back_fields_and_tags(self):
        with omashelf.connect() as db:
            db.executemany(
                "INSERT INTO disks(id, label, path, kind, scanned_at) "
                "VALUES (?, ?, 'Original location', 'data', datetime('now'))",
                [("a", "First"), ("z", "Second")],
            )
            db.executemany(
                "INSERT INTO disk_tags(disk_id, name) VALUES ('z', ?)",
                [(f"tag-{number}",) for number in range(100)],
            )
        changes = {"fields": {"label": "Changed"}, "tagOperation": "add", "tags": ["New"]}
        with self.assertRaisesRegex(ValueError, "100-tag"):
            omashelf.edit_disks(["a", "z"], changes)
        with self.assertRaisesRegex(ValueError, "no longer"):
            omashelf.edit_disks(["a", "missing"], changes)
        with self.assertRaises(ValueError):
            omashelf.edit_disks(["a"], {"fields": {}, "tagOperation": "keep", "tags": []})
        with omashelf.connect() as db:
            self.assertEqual([row["label"] for row in db.execute("SELECT label FROM disks ORDER BY id")],
                             ["First", "Second"])
            self.assertEqual(db.execute("SELECT COUNT(*) FROM disk_edits").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM disk_tags WHERE disk_id = 'a'").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM disk_tags WHERE disk_id = 'z'").fetchone()[0], 100)

    def test_bulk_audio_numbering_validates_the_entire_selection(self):
        with omashelf.connect() as db:
            db.executemany(
                "INSERT INTO disks(id, label, path, kind, scanned_at) "
                "VALUES (?, 'Album', '/dev/sr0', ?, datetime('now'))",
                [("audio:one", "audio"), ("audio:two", "audio"), ("data:one", "data")],
            )
        changes = {"fields": {"disc_number": 2, "disc_count": 3}, "tagOperation": "keep", "tags": []}
        with self.assertRaisesRegex(ValueError, "only available for audio"):
            omashelf.edit_disks(["audio:one", "data:one"], changes)
        omashelf.edit_disks(["audio:one", "audio:two"], changes)
        with omashelf.connect() as db:
            self.assertEqual([tuple(row) for row in db.execute(
                "SELECT disc_number, disc_count FROM disks WHERE kind = 'audio'"
            )], [(2, 3), (2, 3)])
        changes["fields"] = {"disc_number": 4, "disc_count": 3}
        with self.assertRaises(ValueError):
            omashelf.edit_disks(["audio:one", "audio:two"], changes)
        omashelf.edit_disks(["audio:one", "audio:two"], {
            "fields": {"artist": ""}, "tagOperation": "keep", "tags": [],
        })
        with omashelf.connect() as db:
            db.execute("UPDATE disks SET artist = 'Online artist' WHERE kind = 'audio'")
            for disk_id in ("audio:one", "audio:two"):
                self.assertEqual(omashelf.apply_disk_edits(db, disk_id)["artist"], "")

    def test_json_and_xml_round_trips_preserve_files_tags_edits_and_artwork(self):
        (self.media_dir / "line\rbreak.txt").write_bytes(b"fixture")
        with patch.object(omashelf, "mount_for_path", return_value={}):
            disk_id = omashelf.scan_directory(str(self.media_dir))["diskId"]
        label = "Project <one> & café"
        omashelf.edit_disk(disk_id, self.edit_values(
            disk_id, label=label, path="Shelf A", artist="Creator", tags=["Game", "<img src=x>"],
        ))
        cover = self.data_dir / "artwork" / "cover.png"
        cover.parent.mkdir()
        cover.write_bytes(b"\x89PNG\r\n\x1a\nartwork-fixture")
        with omashelf.connect() as db:
            db.execute("UPDATE disks SET artwork = ? WHERE id = ?", (cover.as_uri(), disk_id))
            db.execute(
                "INSERT INTO disks(id, label, source, path, kind, scanned_at, disc_number, disc_count) "
                "VALUES ('audio:fixture', 'Album', '/dev/sr0', '/dev/sr0', 'audio', datetime('now'), 2, 3)"
            )
        for suffix in ("json", "xml"):
            with self.subTest(format=suffix):
                path = Path(self.temporary.name) / f"library.{suffix}"
                result = omashelf.dispatch(["export-library", str(path)])
                self.assertEqual((result["diskCount"], result["fileCount"]), (2, 3))
                exported, _ = omashelf.read_library(str(path))
                data_disc = next(disk for disk in exported if disk["id"] == disk_id)
                self.assertIn("line\rbreak.txt", [file["path"] for file in data_disc["files"]])
                self.assertNotIn("catalog me", path.read_text(encoding="utf-8"))
                omashelf.delete_disks([disk_id, "audio:fixture"])
                preview = omashelf.inspect_import(str(path))
                self.assertEqual(preview["matchingCount"], 0)
                result = omashelf.dispatch([
                    "import-library", str(path), "replace", "keep", preview["fingerprint"],
                ])
                self.assertEqual(result["added"], 2)
                self.assertEqual(omashelf.search_terms(["Game", "song"])["results"][0]["label"], label)
                with omashelf.connect() as db:
                    row = db.execute("SELECT * FROM disks WHERE id = ?", (disk_id,)).fetchone()
                    self.assertEqual((row["artist"], row["path"]), ("Creator", "Shelf A"))
                    self.assertEqual(Path(omashelf.urllib.parse.unquote(
                        omashelf.urllib.parse.urlparse(row["artwork"]).path
                    )).read_bytes(), cover.read_bytes())
                    audio = db.execute("SELECT disc_number, disc_count FROM disks WHERE id = 'audio:fixture'").fetchone()
                    self.assertEqual(tuple(audio), (2, 3))
                with patch.object(omashelf, "mount_for_path", return_value={}):
                    self.assertEqual(omashelf.scan_directory(str(self.media_dir))["label"], label)
                self.assertEqual(next(disk for disk in exported if disk["id"] == disk_id)["edits"]["label"], label)

    def test_import_merge_keeps_or_replaces_matches_and_replace_removes_other_discs(self):
        with patch.object(omashelf, "mount_for_path", return_value={}):
            disk_id = omashelf.scan_directory(str(self.media_dir))["diskId"]
        path = Path(self.temporary.name) / "merge.json"
        omashelf.export_library(str(path))
        omashelf.edit_disk(disk_id, self.edit_values(disk_id, label="Newer local label", tags=["Local"]))
        with omashelf.connect() as db:
            db.execute(
                "INSERT INTO disks(id, label, path, kind, scanned_at) "
                "VALUES ('unrelated', 'Keep me', 'Shelf', 'data', datetime('now'))"
            )
        preview = omashelf.inspect_import(str(path))
        self.assertEqual((preview["matchingCount"], preview["existingCount"]), (1, 2))
        result = omashelf.import_library(str(path), "merge", "keep", preview["fingerprint"])
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(omashelf.search_terms(["Local"])["results"][0]["label"], "Newer local label")
        result = omashelf.import_library(str(path), "merge", "overwrite", preview["fingerprint"])
        self.assertEqual(result["updated"], 1)
        self.assertEqual(omashelf.search_terms(["Local"])["results"], [])
        self.assertIn("unrelated", omashelf.catalog_ids())
        omashelf.import_library(str(path), "replace", "keep", preview["fingerprint"])
        self.assertEqual(omashelf.catalog_ids(), {disk_id})
        with omashelf.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM disk_edits").fetchone()[0], 0)

    def test_invalid_or_changed_imports_cannot_replace_the_current_library(self):
        with patch.object(omashelf, "mount_for_path", return_value={}):
            disk_id = omashelf.scan_directory(str(self.media_dir))["diskId"]
        path = Path(self.temporary.name) / "invalid.json"
        omashelf.export_library(str(path))
        document = json.loads(path.read_text(encoding="utf-8"))
        fingerprint = omashelf.inspect_import(str(path))["fingerprint"]
        path.write_text(json.dumps({**document, "disks": []}), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "changed"):
            omashelf.import_library(str(path), "replace", "keep", fingerprint)
        invalid_documents = []
        for changes in (
            {"file_count": 99}, {"disc_number": 2, "disc_count": 1},
            {"file_count": 1, "files": [{"path": "bad", "size_bytes": -1}]},
            {"external_url": "https://example.invalid/tracker"},
            {"cover": {"type": "image/png", "data": "not-base64"}},
            {"cover": {"type": "image/png", "data": "bm90LWFuLWltYWdl"}},
            {"edits": {"path": "Mismatched location"}}, {"scanned_at": "2026-99-99 00:00:00"},
        ):
            changed = copy.deepcopy(document)
            changed["disks"][0].update(changes)
            invalid_documents.append(changed)
        invalid_documents.append({**document, "version": 999})
        invalid_documents.append({**document, "disks": document["disks"] * 2})
        for invalid in invalid_documents:
            with self.subTest(document=invalid):
                path.write_text(json.dumps(invalid), encoding="utf-8")
                with self.assertRaises(ValueError):
                    omashelf.import_library(str(path), "replace", "keep", fingerprint)
                self.assertEqual(omashelf.catalog_ids(), {disk_id})
                self.assertEqual(len(omashelf.search_terms([])["results"]), 2)

    def test_import_failure_after_deletion_rolls_back_the_database(self):
        with patch.object(omashelf, "mount_for_path", return_value={}):
            disk_id = omashelf.scan_directory(str(self.media_dir))["diskId"]
        path = Path(self.temporary.name) / "rollback.json"
        omashelf.export_library(str(path))
        document = json.loads(path.read_text(encoding="utf-8"))
        document["disks"][0]["cover"] = {
            "type": "image/png",
            "data": omashelf.base64.b64encode(b"\x89PNG\r\n\x1a\nfixture").decode("ascii"),
        }
        path.write_text(json.dumps(document), encoding="utf-8")
        preview = omashelf.inspect_import(str(path))
        with patch.object(omashelf, "write_library_file", side_effect=OSError("Disk full")):
            with self.assertRaisesRegex(OSError, "Disk full"):
                omashelf.import_library(str(path), "replace", "keep", preview["fingerprint"])
        self.assertEqual(omashelf.catalog_ids(), {disk_id})
        self.assertEqual(len(omashelf.search_terms([])["results"]), 2)

    def test_xml_entities_and_oversized_imports_are_rejected(self):
        path = Path(self.temporary.name) / "bad.xml"
        path.write_text('<!DOCTYPE omashelf [<!ENTITY x "test">]><omashelf>&x;</omashelf>', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "entities"):
            omashelf.read_library(str(path))
        with patch.object(omashelf, "MAX_LIBRARY_BYTES", 8):
            with self.assertRaisesRegex(ValueError, "256 MB"):
                omashelf.read_library(str(path))
        path.write_text("<omashelf", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Could not read"):
            omashelf.read_library(str(path))

    def test_export_failure_preserves_existing_destination_and_protects_settings(self):
        path = Path(self.temporary.name) / "existing.json"
        path.write_bytes(b"keep this file")
        with patch.object(omashelf, "mount_for_path", return_value={}):
            disk_id = omashelf.scan_directory(str(self.media_dir))["diskId"]
        with omashelf.connect() as db:
            db.execute("UPDATE disks SET artwork = 'file:///outside-cache.png' WHERE id = ?", (disk_id,))
        with self.assertRaisesRegex(ValueError, "outside"):
            omashelf.export_library(str(path))
        self.assertEqual(path.read_bytes(), b"keep this file")
        with self.assertRaises(ValueError):
            omashelf.export_library(str(omashelf.PREFERENCES_PATH))
        with self.assertRaises(ValueError):
            omashelf.export_library(str(Path(self.temporary.name) / "library.txt"))
        with omashelf.connect() as db:
            db.execute("UPDATE disks SET artwork = '' WHERE id = ?", (disk_id,))
        original_files = set(path.parent.iterdir())
        with patch.object(omashelf.os, "replace", side_effect=OSError("Write failed")):
            with self.assertRaisesRegex(OSError, "Write failed"):
                omashelf.export_library(str(path))
        self.assertEqual(path.read_bytes(), b"keep this file")
        self.assertEqual(set(path.parent.iterdir()), original_files)

    def test_empty_json_and_xml_libraries_can_be_exported_and_restored(self):
        for suffix in ("json", "xml"):
            with self.subTest(format=suffix):
                path = Path(self.temporary.name) / f"empty.{suffix}"
                self.assertEqual(omashelf.export_library(str(path))["diskCount"], 0)
                with patch.object(omashelf, "mount_for_path", return_value={}):
                    omashelf.scan_directory(str(self.media_dir))
                preview = omashelf.inspect_import(str(path))
                self.assertEqual(preview["diskCount"], 0)
                self.assertEqual(preview["existingCount"], 1)
                result = omashelf.import_library(str(path), "replace", "keep", preview["fingerprint"])
                self.assertEqual(result["added"], 0)
                self.assertEqual(omashelf.catalog_ids(), set())

    def test_bulk_delete_removes_selected_disks_and_rejects_missing_ids(self):
        second_media_dir = Path(self.temporary.name) / "second-disc"
        second_media_dir.mkdir()
        (second_media_dir / "second.txt").write_text("second", encoding="utf-8")
        with patch.object(omashelf, "mount_for_path", return_value={}):
            first = omashelf.scan_directory(str(self.media_dir))
            second = omashelf.scan_directory(str(second_media_dir))

        deleted = omashelf.delete_disks([first["diskId"], second["diskId"]])
        self.assertEqual(deleted["deleted"], 2)
        self.assertEqual(len(deleted["diskIds"]), 2)
        self.assertEqual(omashelf.search("", "")["results"], [])
        with self.assertRaises(ValueError):
            omashelf.delete_disks([first["diskId"]])


if __name__ == "__main__":
    unittest.main()
