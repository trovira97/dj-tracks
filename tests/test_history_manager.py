"""Unit tests for utils.history_manager."""
from __future__ import annotations

import json

import pytest


@pytest.fixture
def tmp_history(tmp_path, monkeypatch):
    """Redirect HISTORY_PATH to a temp file before importing the module."""
    fake = tmp_path / "history.json"
    import utils.history_manager as hm_mod
    monkeypatch.setattr(hm_mod, "HISTORY_PATH", fake)
    return fake


class TestHistoryRecord:
    def test_to_from_dict_roundtrip(self):
        from utils.history_manager import DownloadRecord
        rec = DownloadRecord(
            title="T", artist="A", album="Alb",
            platform="spotify", quality="MP3 320k", status="done",
            path="/x/y.mp3", duration_ms=180_000,
        )
        d = rec.to_dict()
        rec2 = DownloadRecord.from_dict(d)
        assert rec2.title == rec.title
        assert rec2.artist == rec.artist
        assert rec2.id == rec.id
        assert rec2.timestamp == rec.timestamp

    def test_date_str_from_timestamp(self):
        from utils.history_manager import DownloadRecord
        rec = DownloadRecord("T", "A", "", "spotify", "q", "done",
                             timestamp="2025-01-15T10:30:00")
        assert rec.date_str == "2025-01-15"


class TestHistoryManager:
    def _add_record(self, hm, title="X", status="done", platform="spotify"):
        from utils.history_manager import DownloadRecord
        rec = DownloadRecord(title, "A", "", platform, "q", status)
        with hm._lock:
            hm._records.insert(0, rec)
        return rec

    def test_filter_by_query(self, tmp_history):
        from utils.history_manager import HistoryManager
        hm = HistoryManager()
        self._add_record(hm, title="Hello World")
        self._add_record(hm, title="Bye")
        results, total = hm.filter(query="hello")
        assert total == 1
        assert results[0].title == "Hello World"

    def test_filter_by_status(self, tmp_history):
        from utils.history_manager import HistoryManager
        hm = HistoryManager()
        self._add_record(hm, status="done")
        self._add_record(hm, status="error")
        results, total = hm.filter(status="error")
        assert total == 1

    def test_filter_by_platform(self, tmp_history):
        from utils.history_manager import HistoryManager
        hm = HistoryManager()
        self._add_record(hm, platform="spotify")
        self._add_record(hm, platform="soundcloud")
        results, total = hm.filter(platform="soundcloud")
        assert total == 1

    def test_stats(self, tmp_history):
        from utils.history_manager import HistoryManager
        hm = HistoryManager()
        self._add_record(hm, status="done")
        self._add_record(hm, status="done")
        self._add_record(hm, status="error")
        stats = hm.stats()
        assert stats["total"] == 3
        assert stats["done"] == 2
        assert stats["errors"] == 1
        assert stats["success_pct"] == 67

    def test_recent_returns_newest_first(self, tmp_history):
        from utils.history_manager import HistoryManager
        hm = HistoryManager()
        self._add_record(hm, title="First")
        self._add_record(hm, title="Second")
        self._add_record(hm, title="Third")
        recent = hm.recent(2)
        assert len(recent) == 2
        assert recent[0].title == "Third"     # most recent insertion is on top

    def test_export_json(self, tmp_history, tmp_path):
        from utils.history_manager import HistoryManager
        hm = HistoryManager()
        self._add_record(hm, title="Exported")
        out = tmp_path / "export.json"
        count = hm.export_json(out)
        assert count == 1
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["exports"] == 1
        assert data["downloads"][0]["title"] == "Exported"

    def test_export_csv(self, tmp_history, tmp_path):
        from utils.history_manager import HistoryManager
        hm = HistoryManager()
        self._add_record(hm, title="CsvSong")
        out = tmp_path / "out.csv"
        count = hm.export_csv(out)
        assert count == 1
        assert "CsvSong" in out.read_text(encoding="utf-8")

    def test_clear(self, tmp_history):
        from utils.history_manager import HistoryManager
        hm = HistoryManager()
        self._add_record(hm)
        hm.clear()
        assert hm.all() == []

    def test_delete_by_id(self, tmp_history):
        from utils.history_manager import HistoryManager
        hm = HistoryManager()
        r1 = self._add_record(hm, title="Keep")
        r2 = self._add_record(hm, title="Delete me")
        assert hm.delete(r2.id) is True
        remaining = hm.all()
        assert len(remaining) == 1
        assert remaining[0].id == r1.id

    def test_delete_missing_returns_false(self, tmp_history):
        from utils.history_manager import HistoryManager
        hm = HistoryManager()
        self._add_record(hm)
        assert hm.delete("nonexistent-id") is False
        assert len(hm.all()) == 1
