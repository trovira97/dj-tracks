"""
dj_metadata.py — DJ-grade metadata enrichment for SpotRR.

Adds real BPM, musical key + Camelot code, and genre to downloaded tracks.

Data sources (in order):
  1. GetSongBPM API   — real, curated BPM/key/camelot/genre (needs a free API key).
  2. librosa (local)  — audio analysis fallback for tracks not in the database.

Nothing here touches the UI; spotrr.py calls enrich_files() after a download.

GetSongBPM attribution: a link back to https://getsongbpm.com is required by
their API terms when using this data.
"""

from __future__ import annotations

import os
import re
import time
import urllib.parse
from typing import Callable, Iterable, Optional

# ── Camelot wheel: (key name, mode) -> Camelot code ─────────────────────────────
# mode: 1 = major, 0 = minor
_CAMELOT = {
    ("B", 1): "1B",  ("G#m", 0): "1A",
    ("F#", 1): "2B", ("D#m", 0): "2A",
    ("C#", 1): "3B", ("A#m", 0): "3A",
    ("G#", 1): "4B", ("Fm", 0): "4A",
    ("D#", 1): "5B", ("Cm", 0): "5A",
    ("A#", 1): "6B", ("Gm", 0): "6A",
    ("F", 1): "7B",  ("Dm", 0): "7A",
    ("C", 1): "8B",  ("Am", 0): "8A",
    ("G", 1): "9B",  ("Em", 0): "9A",
    ("D", 1): "10B", ("Bm", 0): "10A",
    ("A", 1): "11B", ("F#m", 0): "11A",
    ("E", 1): "12B", ("C#m", 0): "12A",
}

# Enharmonic normalisation: flats -> sharps used in the table above.
_ENHARMONIC = {
    "Db": "C#", "Eb": "D#", "Gb": "F#", "Ab": "G#", "Bb": "A#",
    "Cb": "B", "Fb": "E", "E#": "F", "B#": "C",
}

_PITCH_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def _normalise_key(key_of: str, mode: Optional[str]) -> tuple[str, int]:
    """Turn a textual key like 'Db', 'F#m', 'A minor' into (root, mode_int).

    root is the bare note name in sharp notation (no 'm').
    mode_int: 1 = major, 0 = minor.
    """
    if not key_of:
        return ("", 1)
    s = key_of.strip()
    low = s.lower()

    # Determine mode.
    if mode is not None:
        ms = str(mode).lower()
        is_major = 0 if (ms.startswith("min") or ms == "0") else 1
    else:
        # Infer from the string: a trailing 'm' (not 'maj') or 'min' => minor.
        if "min" in low or (low.endswith("m") and not low.endswith("maj")):
            is_major = 0
        else:
            is_major = 1

    # Strip mode words/suffix to isolate the root note.
    root = re.sub(r"\s*(maj(or)?|min(or)?|m)\s*$", "", s, flags=re.IGNORECASE).strip()
    root = root.replace("♯", "#").replace("♭", "b")
    if root:
        root = root[0].upper() + root[1:]
    root = _ENHARMONIC.get(root, root)
    return (root, is_major)


def key_to_camelot(key_of: str, mode: Optional[str] = None) -> tuple[str, str]:
    """Return (musical_key, camelot). musical_key like 'Am' / 'F#'. camelot like '8A'."""
    root, is_major = _normalise_key(key_of, mode)
    if not root:
        return ("", "")
    musical = root + ("" if is_major else "m")
    camelot = _CAMELOT.get((musical, is_major), "")
    return (musical, camelot)


# ── GetSongBPM lookup ───────────────────────────────────────────────────────────
_API_BASE = "https://api.getsongbpm.com"


def _fuzzy(a: str, b: str) -> float:
    try:
        from rapidfuzz import fuzz
        return fuzz.token_set_ratio(a or "", b or "")
    except Exception:
        a, b = (a or "").lower(), (b or "").lower()
        return 100.0 if a and a in b or b in a else 0.0


def lookup_getsongbpm(artist: str, title: str, api_key: str,
                      session=None) -> Optional[dict]:
    """Query GetSongBPM for a single track. Returns dict with bpm/key/camelot/genre
    or None when nothing usable is found."""
    if not api_key or not (artist or title):
        return None
    import requests
    sess = session or requests

    lookup = f"song:{title} artist:{artist}".strip()
    params = {"api_key": api_key, "type": "both",
              "lookup": lookup, "limit": 10}
    url = f"{_API_BASE}/search/?" + urllib.parse.urlencode(params)
    try:
        r = sess.get(url, timeout=12,
                     headers={"X-API-KEY": api_key,
                              "User-Agent": "SpotRR/1.0 (+https://getsongbpm.com)"})
        if r.status_code != 200:
            return None
        data = r.json()
    except Exception:
        return None

    results = data.get("search") if isinstance(data, dict) else data
    if not isinstance(results, list) or not results:
        return None

    # Pick the best title+artist match.
    best, best_score = None, -1.0
    for item in results:
        if not isinstance(item, dict):
            continue
        it_title = item.get("song_title") or item.get("title") or ""
        art = item.get("artist") or {}
        it_artist = art.get("name", "") if isinstance(art, dict) else ""
        score = _fuzzy(title, it_title) * 0.6 + _fuzzy(artist, it_artist) * 0.4
        if score > best_score:
            best, best_score = item, score

    if not best or best_score < 55:
        return None

    tempo = best.get("tempo")
    try:
        bpm = int(round(float(tempo))) if tempo not in (None, "", "0") else None
    except (TypeError, ValueError):
        bpm = None

    key_of = best.get("key_of") or ""
    camelot = best.get("camelot") or ""
    if key_of and not camelot:
        _, camelot = key_to_camelot(key_of)
    musical, camelot2 = key_to_camelot(key_of) if key_of else ("", "")
    musical = musical or key_of
    camelot = camelot or camelot2

    art = best.get("artist") or {}
    genres = art.get("genres") if isinstance(art, dict) else None
    genre = genres[0] if isinstance(genres, list) and genres else ""

    if bpm is None and not musical:
        return None
    return {"bpm": bpm, "key": musical, "camelot": camelot,
            "genre": genre, "source": "getsongbpm"}


# ── librosa local analysis (fallback) ───────────────────────────────────────────
# Krumhansl-Schmuckler key profiles.
_MAJ_PROFILE = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
_MIN_PROFILE = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]


def _spectral_cutoff_khz(y, sr) -> Optional[float]:
    """Highest frequency (kHz) where real signal is present, by detecting the
    encoder's low-pass edge.

    Lossy encoders brick-wall the top of the spectrum: a cutoff well below
    ~20 kHz means the source was a low-bitrate file, even after spotdl
    re-encoded it up to the requested bitrate.  We find the highest bin whose
    energy is within ~55 dB of the spectral peak (above that is just the
    noise floor / quantisation).
    """
    try:
        import numpy as np
        import librosa
        S = np.abs(librosa.stft(y, n_fft=4096)).mean(axis=1)
        if S.size == 0 or S.max() <= 0:
            return None
        freqs = librosa.fft_frequencies(sr=sr, n_fft=4096)
        db = 20.0 * np.log10(S / S.max() + 1e-12)
        above = np.where(db > -55.0)[0]
        if len(above) == 0:
            return None
        return float(freqs[above[-1]]) / 1000.0
    except Exception:
        return None


def cutoff_to_bitrate(khz: Optional[float]) -> Optional[int]:
    """Map a low-pass-edge frequency to an approximate source bitrate (kbps).

    Approximate by design: encoders vary, so this is a conservative flag for
    clearly low-quality sources rather than a precise bitrate meter.
    """
    if khz is None:
        return None
    if khz >= 19.5:
        return 320
    if khz >= 18.0:
        return 256
    if khz >= 16.5:
        return 192
    if khz >= 15.0:
        return 128
    if khz >= 12.0:
        return 96
    return 64


def analyze_local(filepath: str, with_quality: bool = False,
                  need_keybpm: bool = True) -> Optional[dict]:
    """Analyse an audio file with librosa.

    Returns a dict that may contain: bpm, key, camelot (when need_keybpm), and
    cutoff_khz / est_bitrate (when with_quality).  Returns None if librosa is
    unavailable or the file can't be read.
    """
    try:
        import numpy as np
        import librosa
    except Exception:
        return None
    try:
        # Full sample rate so the quality cutoff is meaningful (up to ~22 kHz).
        y, sr = librosa.load(filepath, mono=True, sr=44100, duration=180)
        if y is None or len(y) < sr // 2:
            return None

        out: dict = {"source": "librosa"}

        if need_keybpm:
            y22 = librosa.resample(y, orig_sr=sr, target_sr=22050)
            tempo = librosa.beat.beat_track(y=y22, sr=22050)[0]
            tempo = float(np.atleast_1d(tempo)[0])
            out["bpm"] = int(round(tempo)) if tempo else None
            chroma = librosa.feature.chroma_cqt(y=y22, sr=22050)
            chroma_mean = chroma.mean(axis=1)
            maj = np.array(_MAJ_PROFILE)
            minp = np.array(_MIN_PROFILE)
            best_corr, best_root, best_mode = -2.0, 0, 1
            for i in range(12):
                rot = np.roll(chroma_mean, -i)
                cmaj = float(np.corrcoef(rot, maj)[0, 1])
                cmin = float(np.corrcoef(rot, minp)[0, 1])
                if cmaj > best_corr:
                    best_corr, best_root, best_mode = cmaj, i, 1
                if cmin > best_corr:
                    best_corr, best_root, best_mode = cmin, i, 0
            musical, camelot = key_to_camelot(
                _PITCH_NAMES[best_root], "major" if best_mode else "minor")
            out["key"] = musical
            out["camelot"] = camelot

        if with_quality:
            khz = _spectral_cutoff_khz(y, sr)
            out["cutoff_khz"] = khz
            out["est_bitrate"] = cutoff_to_bitrate(khz)

        return out
    except Exception:
        return None


# ── Cover art embedding ─────────────────────────────────────────────────────────
def upscale_cover_url(url: str) -> str:
    """Bump known thumbnail URLs to a higher resolution (e.g. SoundCloud)."""
    if not url:
        return url
    # SoundCloud serves -large.jpg (100px); -t500x500 is the big version.
    for small in ("-large.", "-t67x67.", "-t120x120.", "-small.", "-tiny."):
        if small in url:
            return url.replace(small, "-t500x500.")
    return url


def _has_embedded_cover(filepath: str, ext: str) -> bool:
    try:
        if ext == "mp3":
            from mutagen.id3 import ID3, ID3NoHeaderError
            try:
                tags = ID3(filepath)
            except ID3NoHeaderError:
                return False
            return bool(tags.getall("APIC"))
        if ext == "flac":
            from mutagen.flac import FLAC
            return bool(FLAC(filepath).pictures)
    except Exception:
        return False
    return False


def embed_cover(filepath: str, fmt: str, cover_url: str,
                only_if_missing: bool = True) -> bool:
    """Download cover_url at full resolution and embed it. Returns True on success."""
    if not cover_url:
        return False
    ext = (fmt or os.path.splitext(filepath)[1].lstrip(".")).lower()
    if only_if_missing and _has_embedded_cover(filepath, ext):
        return False
    try:
        import requests
        url = upscale_cover_url(cover_url)
        r = requests.get(url, timeout=15,
                         headers={"User-Agent": "SpotRR/1.0"})
        if r.status_code != 200 or not r.content:
            return False
        data = r.content
        mime = r.headers.get("Content-Type", "image/jpeg").split(";")[0]
        if "png" in mime:
            mime = "image/png"
        elif "jpeg" not in mime and "jpg" not in mime:
            mime = "image/jpeg"

        if ext == "mp3":
            from mutagen.id3 import ID3, APIC, ID3NoHeaderError
            try:
                tags = ID3(filepath)
            except ID3NoHeaderError:
                tags = ID3()
            tags.delall("APIC")
            tags.add(APIC(encoding=3, mime=mime, type=3, desc="Cover", data=data))
            tags.save(filepath, v2_version=3)
            return True
        if ext == "flac":
            from mutagen.flac import FLAC, Picture
            audio = FLAC(filepath)
            pic = Picture()
            pic.type = 3
            pic.mime = mime
            pic.data = data
            audio.clear_pictures()
            audio.add_picture(pic)
            audio.save()
            return True
    except Exception:
        return False
    return False


# ── Acoustic fingerprint (ffmpeg Chromaprint) ───────────────────────────────────
def chromaprint_available(ffmpeg: str = "ffmpeg") -> bool:
    """True if this ffmpeg build supports the Chromaprint muxer."""
    import subprocess
    try:
        flags = {}
        if os.name == "nt":
            flags["creationflags"] = 0x08000000
        p = subprocess.run([ffmpeg or "ffmpeg", "-hide_banner", "-muxers"],
                           capture_output=True, text=True, timeout=20, **flags)
        return "chromaprint" in (p.stdout or "")
    except Exception:
        return False


def chromaprint_fingerprint(filepath: str, ffmpeg: str = "ffmpeg") -> Optional[list]:
    """Compute a Chromaprint acoustic fingerprint as a list of 32-bit ints.

    Robust to format/bitrate: the same recording yields near-identical
    fingerprints regardless of how it was encoded.
    """
    import subprocess
    import struct
    try:
        flags = {}
        if os.name == "nt":
            flags["creationflags"] = 0x08000000
        p = subprocess.run(
            [ffmpeg or "ffmpeg", "-i", filepath, "-t", "120",
             "-f", "chromaprint", "-fp_format", "raw", "-"],
            capture_output=True, timeout=120, **flags)
        raw = p.stdout or b""
        n = len(raw) // 4
        if n == 0:
            return None
        return list(struct.unpack(f"<{n}I", raw[:n * 4]))
    except Exception:
        return None


def fp_similarity(a: Optional[list], b: Optional[list]) -> float:
    """Bit-similarity (0..1) between two Chromaprint fingerprints."""
    if not a or not b:
        return 0.0
    n = min(len(a), len(b))
    if n == 0:
        return 0.0
    match = 0
    for x, y in zip(a[:n], b[:n]):
        match += 32 - bin(x ^ y).count("1")
    return match / (n * 32)


# ── Loudness / ReplayGain (ffmpeg ebur128) ──────────────────────────────────────
def measure_loudness(filepath: str, ffmpeg: str = "ffmpeg") -> Optional[dict]:
    """Measure integrated loudness (LUFS) and true peak (dBFS) with ffmpeg."""
    import subprocess
    try:
        flags = {}
        if os.name == "nt":
            flags["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
        p = subprocess.run(
            [ffmpeg or "ffmpeg", "-nostats", "-i", filepath,
             "-af", "ebur128=peak=true", "-f", "null", "-"],
            capture_output=True, text=True, timeout=180, **flags)
        err = p.stderr or ""
        lufs = re.findall(r"I:\s*(-?\d+\.?\d*)\s*LUFS", err)
        peak = re.findall(r"Peak:\s*(-?\d+\.?\d*)\s*dBFS", err)
        if not lufs:
            return None
        return {"lufs": float(lufs[-1]),
                "peak_dbfs": float(peak[-1]) if peak else 0.0}
    except Exception:
        return None


def replaygain_values(lufs: float, peak_dbfs: float,
                      reference: float = -18.0) -> tuple[str, str]:
    """ReplayGain track gain + peak strings from a loudness measurement.

    reference -18 LUFS ≈ the 89 dB ReplayGain reference level.
    """
    gain = reference - lufs
    try:
        peak_lin = 10 ** (peak_dbfs / 20.0)
    except Exception:
        peak_lin = 1.0
    return f"{gain:+.2f} dB", f"{peak_lin:.6f}"


# ── Tag writing (mutagen) ───────────────────────────────────────────────────────
def write_tags(filepath: str, fmt: str, info: dict) -> bool:
    """Write BPM / key / camelot / genre / extra sorting tags / ReplayGain into
    the file's tags. Cross-platform."""
    bpm = info.get("bpm")
    key = info.get("key") or ""
    camelot = info.get("camelot") or ""
    genre = info.get("genre") or ""
    year = str(info.get("year") or "").strip()
    publisher = (info.get("publisher") or "").strip()
    track_no = info.get("track_number")
    track_tot = info.get("tracks_count")
    rg_gain = info.get("rg_gain") or ""
    rg_peak = info.get("rg_peak") or ""
    trck = ""
    if track_no:
        trck = f"{int(track_no)}/{int(track_tot)}" if track_tot else str(int(track_no))
    ext = (fmt or os.path.splitext(filepath)[1].lstrip(".")).lower()
    comment = f"{camelot} - {key}".strip(" -") if (camelot or key) else ""

    try:
        if ext == "mp3":
            from mutagen.id3 import (ID3, TBPM, TKEY, TCON, COMM, TXXX,
                                     TDRC, TPUB, TRCK, ID3NoHeaderError)
            try:
                tags = ID3(filepath)
            except ID3NoHeaderError:
                tags = ID3()
            if bpm:
                tags.setall("TBPM", [TBPM(encoding=3, text=str(bpm))])
            if key:
                tags.setall("TKEY", [TKEY(encoding=3, text=key)])
            if genre:
                tags.setall("TCON", [TCON(encoding=3, text=genre)])
            if camelot:
                # Serato/rekordbox-friendly: Camelot in a custom field + comment.
                tags.setall("TXXX:INITIALKEY", [TXXX(encoding=3, desc="INITIALKEY", text=camelot)])
            if comment:
                tags.setall("COMM", [COMM(encoding=3, lang="eng", desc="", text=comment)])
            if year and not tags.getall("TDRC"):
                tags.setall("TDRC", [TDRC(encoding=3, text=year)])
            if publisher and not tags.getall("TPUB"):
                tags.setall("TPUB", [TPUB(encoding=3, text=publisher)])
            if trck and not tags.getall("TRCK"):
                tags.setall("TRCK", [TRCK(encoding=3, text=trck)])
            if rg_gain:
                tags.setall("TXXX:REPLAYGAIN_TRACK_GAIN",
                            [TXXX(encoding=3, desc="REPLAYGAIN_TRACK_GAIN", text=rg_gain)])
            if rg_peak:
                tags.setall("TXXX:REPLAYGAIN_TRACK_PEAK",
                            [TXXX(encoding=3, desc="REPLAYGAIN_TRACK_PEAK", text=rg_peak)])
            tags.save(filepath, v2_version=3)
            return True

        if ext == "flac":
            from mutagen.flac import FLAC
            audio = FLAC(filepath)
            if bpm:
                audio["BPM"] = str(bpm)
            if key:
                audio["KEY"] = key
                audio["INITIALKEY"] = camelot or key
            if camelot:
                audio["CAMELOT"] = camelot
            if genre:
                audio["GENRE"] = genre
            if comment:
                audio["COMMENT"] = comment
            if year and "date" not in audio:
                audio["DATE"] = year
            if publisher and "organization" not in audio:
                audio["ORGANIZATION"] = publisher
                audio["LABEL"] = publisher
            if track_no and "tracknumber" not in audio:
                audio["TRACKNUMBER"] = str(int(track_no))
                if track_tot:
                    audio["TRACKTOTAL"] = str(int(track_tot))
            if rg_gain:
                audio["REPLAYGAIN_TRACK_GAIN"] = rg_gain
            if rg_peak:
                audio["REPLAYGAIN_TRACK_PEAK"] = rg_peak
            audio.save()
            return True

        if ext in ("wav", "wave"):
            from mutagen.wave import WAVE
            from mutagen.id3 import TBPM, TKEY, TCON, COMM, TXXX
            audio = WAVE(filepath)
            if audio.tags is None:
                audio.add_tags()
            t = audio.tags
            if bpm:
                t.setall("TBPM", [TBPM(encoding=3, text=str(bpm))])
            if key:
                t.setall("TKEY", [TKEY(encoding=3, text=key)])
            if genre:
                t.setall("TCON", [TCON(encoding=3, text=genre)])
            if camelot:
                t.setall("TXXX:INITIALKEY", [TXXX(encoding=3, desc="INITIALKEY", text=camelot)])
            if comment:
                t.setall("COMM", [COMM(encoding=3, lang="eng", desc="", text=comment)])
            audio.save()
            return True
    except Exception:
        return False
    return False


# ── Orchestrator ────────────────────────────────────────────────────────────────
_QUALITY_KBPS = {"128k": 128, "192k": 192, "256k": 256, "320k": 320}


def _dj_rename(filepath: str, info: dict) -> Optional[str]:
    """Rename a file to 'Original Name [BPM - Camelot].ext'. Returns new path."""
    bpm = info.get("bpm")
    cam = info.get("camelot") or info.get("key") or ""
    parts = []
    if bpm:
        parts.append(str(bpm))
    if cam:
        parts.append(cam)
    if not parts:
        return None
    suffix = " [" + " - ".join(parts) + "]"
    folder = os.path.dirname(filepath)
    base, ext = os.path.splitext(os.path.basename(filepath))
    # Don't double-append if already tagged (re-runs).
    base = re.sub(r"\s*\[[0-9]{2,3}(\s*-\s*\d{1,2}[AB])?\]$", "", base)
    base = re.sub(r"\s*\[\d{1,2}[AB]\]$", "", base)
    new_name = base + suffix + ext
    new_path = os.path.join(folder, new_name)
    if os.path.abspath(new_path) == os.path.abspath(filepath):
        return None
    try:
        if os.path.exists(new_path):
            return None  # avoid clobbering an existing file
        os.rename(filepath, new_path)
        return new_path
    except Exception:
        return None


def enrich_files(entries: Iterable[dict], fmt: str, api_key: str = "",
                 use_local_fallback: bool = True,
                 requested_quality: str = "",
                 check_quality: bool = True,
                 embed_covers: bool = True,
                 dj_filename: bool = False,
                 replaygain: bool = False,
                 ffmpeg: str = "ffmpeg",
                 log: Optional[Callable[[str, str], None]] = None,
                 progress: Optional[Callable[[int, int], None]] = None,
                 stop_check: Optional[Callable[[], bool]] = None) -> dict:
    """Enrich downloaded files with BPM/key/camelot/genre + extra sorting tags,
    embed full-res cover art, write ReplayGain, and flag tracks whose real audio
    quality is below what was requested.

    entries: dicts with keys: path, artist, title (genre, cover_url, year,
    publisher, track_number, tracks_count optional).
    Returns summary counts.
    """
    def _log(msg, kind="info"):
        if log:
            try:
                log(msg, kind)
            except Exception:
                pass

    items = [e for e in entries if e.get("path") and os.path.exists(e["path"])]
    total = len(items)
    done = tagged = from_db = from_local = covers = lowq = renamed = gained = 0
    renames: dict = {}

    if not total:
        return {"total": 0, "tagged": 0, "db": 0, "local": 0, "covers": 0,
                "lowq": 0, "renamed": 0, "gained": 0, "renames": {}}

    fmt_l = (fmt or "").lower()
    lossless = fmt_l in ("flac", "wav", "wave")
    want_kbps = _QUALITY_KBPS.get((requested_quality or "").lower())
    # Quality check only makes sense for lossy targets with a known target.
    do_quality = bool(check_quality and want_kbps and not lossless)

    session = None
    if api_key:
        try:
            import requests
            session = requests.Session()
        except Exception:
            session = None

    for e in items:
        if stop_check and not stop_check():
            break
        done += 1
        if progress:
            try:
                progress(done, total)
            except Exception:
                pass

        title = e.get("title", "?")

        # 1. Real BPM/key/genre from the database first.
        info = None
        if api_key:
            info = lookup_getsongbpm(e.get("artist", ""), title, api_key, session)
            if info:
                from_db += 1
            time.sleep(0.2)  # be gentle with the API rate limit

        # 2. One librosa pass for whatever is still missing (key/bpm) + quality.
        need_kb = (info is None) and use_local_fallback
        if need_kb or do_quality:
            local = analyze_local(e["path"], with_quality=do_quality,
                                  need_keybpm=need_kb)
            if local:
                if need_kb and (local.get("bpm") or local.get("key")):
                    info = {k: local.get(k) for k in ("bpm", "key", "camelot")}
                    info["source"] = "librosa"
                    from_local += 1
                # Quality warning.
                if do_quality and local.get("est_bitrate"):
                    est = local["est_bitrate"]
                    if est < want_kbps:
                        lowq += 1
                        khz = local.get("cutoff_khz")
                        _log(f"   ⚠ calidad baja: {title}  ·  fuente ≈{est} kbps"
                             + (f" (corte {khz:.1f} kHz)" if khz else "")
                             + f", pediste {want_kbps} kbps", "warning")

        # 3. Embed full-resolution cover if one is available and missing.
        if embed_covers and e.get("cover_url"):
            if embed_cover(e["path"], fmt, e["cover_url"], only_if_missing=True):
                covers += 1

        # 4. ReplayGain (loudness normalisation tags).
        rg_gain = rg_peak = ""
        if replaygain:
            m = measure_loudness(e["path"], ffmpeg)
            if m:
                rg_gain, rg_peak = replaygain_values(m["lufs"], m["peak_dbfs"])
                gained += 1

        # Build the tag payload: BPM/key info (if any) + sorting tags + RG.
        # Write even when there's no BPM/key, so RG and sorting tags still land.
        if info is None:
            info = {}
        if not info.get("genre") and e.get("genre"):
            info["genre"] = e["genre"]
        for k in ("year", "publisher", "track_number", "tracks_count"):
            if e.get(k) and not info.get(k):
                info[k] = e[k]
        if rg_gain:
            info["rg_gain"] = rg_gain
            info["rg_peak"] = rg_peak

        has_payload = any(info.get(k) for k in (
            "bpm", "key", "camelot", "genre", "year", "publisher",
            "track_number", "rg_gain"))
        if has_payload and write_tags(e["path"], fmt, info):
            tagged += 1
            bpm = info.get("bpm") or "?"
            cam = info.get("camelot") or info.get("key") or "?"
            src = "DB" if info.get("source") == "getsongbpm" else "local"
            extra = " · RG" if rg_gain else ""
            _log(f"   ♪ {title}  ·  {bpm} BPM  ·  {cam}  ({src}){extra}", "success")

        # DJ filename: rename to '... [BPM - Camelot].ext' (last step).
        if dj_filename and (info.get("bpm") or info.get("camelot") or info.get("key")):
            new_path = _dj_rename(e["path"], info)
            if new_path:
                renames[e["path"]] = new_path
                e["path"] = new_path
                renamed += 1

    return {"total": total, "tagged": tagged, "db": from_db,
            "local": from_local, "covers": covers, "lowq": lowq,
            "renamed": renamed, "gained": gained, "renames": renames}
