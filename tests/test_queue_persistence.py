"""Unit tests for core.queue_persistence."""
from __future__ import annotations

import pytest

from downloader.audio_downloader import DownloadStatus, DownloadTask
from downloader.quality_manager import DEFAULT_PROFILE
from providers import TrackInfo


@pytest.fixture
def tmp_queue(tmp_path, monkeypatch):
    """Redirect QUEUE_PATH to a temp file."""
    fake = tmp_path / "queue.json"
    import core.queue_persistence as qp
    monkeypatch.setattr(qp, "QUEUE_PATH", fake)
    return fake


def _make_task(title="T", artist="A", status=DownloadStatus.PENDING):
    return DownloadTask(
        track=TrackInfo(title, [artist], platform="spotify",
                         source_url="https://spotify.com/track/abc"),
        profile=DEFAULT_PROFILE,
        output_dir="/tmp/downloads",
        status=status,
    )


class TestSaveAndLoad:
    def test_roundtrip_preserves_track_data(self, tmp_queue):
        from core.queue_persistence import load_queue, save_queue
        tasks = [_make_task("Song 1", "Artist 1"), _make_task("Song 2", "Artist 2")]
        assert save_queue(tasks) == 2

        loaded = load_queue()
        assert len(loaded) == 2
        assert loaded[0].track.title == "Song 1"
        assert loaded[1].track.title == "Song 2"
        # Restored tasks are always PENDING regardless of previous state.
        assert all(t.status == DownloadStatus.PENDING for t in loaded)

    def test_save_filters_out_terminal_tasks(self, tmp_queue):
        from core.queue_persistence import load_queue, save_queue
        tasks = [
            _make_task("Pending", status=DownloadStatus.PENDING),
            _make_task("Done",    status=DownloadStatus.DONE),
            _make_task("Error",   status=DownloadStatus.ERROR),
            _make_task("Cancel",  status=DownloadStatus.CANCELLED),
        ]
        assert save_queue(tasks) == 1
        loaded = load_queue()
        assert len(loaded) == 1
        assert loaded[0].track.title == "Pending"

    def test_load_missing_file_returns_empty(self, tmp_queue):
        from core.queue_persistence import load_queue
        assert load_queue() == []

    def test_demotes_downloading_to_pending(self, tmp_queue):
        from core.queue_persistence import load_queue, save_queue
        task = _make_task("Mid-download", status=DownloadStatus.DOWNLOADING)
        save_queue([task])
        loaded = load_queue()
        assert len(loaded) == 1
        assert loaded[0].status == DownloadStatus.PENDING


class TestClearQueue:
    def test_clear_removes_file(self, tmp_queue):
        from core.queue_persistence import clear_queue, save_queue
        save_queue([_make_task()])
        assert tmp_queue.exists()
        clear_queue()
        assert not tmp_queue.exists()

    def test_clear_when_missing_is_no_op(self, tmp_queue):
        from core.queue_persistence import clear_queue
        clear_queue()   # must not raise
