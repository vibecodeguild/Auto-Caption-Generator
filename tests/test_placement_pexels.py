"""Placement overlay B-roll: Pexels search filters and local freeze."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core import story_assets
from app.core.placement import (
    list_placement_clips,
    placement_library_video_path,
    select_placement_pexels,
    write_placement_original,
)
from app.core.video_project import VIDEO_PROJECT_SUFFIX


def test_trusted_pexels_urls_allow_official_hosts_only() -> None:
    assert story_assets.trusted_pexels_media_url("https://videos.pexels.com/video-files/1.mp4")
    assert story_assets.trusted_pexels_media_url(
        "https://player.vimeo.com/external/123.hd.mp4?s=abc"
    )
    assert not story_assets.trusted_pexels_media_url("https://attacker.example/video.mp4")
    assert not story_assets.trusted_pexels_media_url("http://videos.pexels.com/video-files/1.mp4")
    assert not story_assets.trusted_pexels_media_url("https://player.vimeo.com/videos/123")


def test_pexels_file_pick_prefers_1080p_16x9_and_drops_portrait() -> None:
    video = {
        "video_files": [
            {
                "width": 1080,
                "height": 1920,
                "file_type": "video/mp4",
                "quality": "hd",
                "link": "https://videos.pexels.com/portrait.mp4",
            },
            {
                "width": 3840,
                "height": 2160,
                "file_type": "video/mp4",
                "quality": "hd",
                "link": "https://videos.pexels.com/uhd.mp4",
            },
            {
                "width": 1920,
                "height": 1080,
                "file_type": "video/mp4",
                "quality": "hd",
                "link": "https://videos.pexels.com/fhd.mp4",
            },
            {
                "width": 640,
                "height": 360,
                "file_type": "video/mp4",
                "quality": "sd",
                "link": "https://videos.pexels.com/sd.mp4",
            },
            {
                "width": 1920,
                "height": 1080,
                "file_type": "video/mp4",
                "quality": "hls",
                "link": "https://videos.pexels.com/stream.m3u8",
            },
        ]
    }
    files = story_assets._pexels_mp4_files(video)
    links = {item["link"] for item in files}
    assert "https://videos.pexels.com/portrait.mp4" not in links
    assert "https://videos.pexels.com/stream.m3u8" not in links
    render = story_assets._pick_pexels_render_file(files)
    assert render is not None
    assert render["link"] == "https://videos.pexels.com/fhd.mp4"
    preview = story_assets._pick_pexels_preview_file(files, render)
    assert preview["link"] == "https://videos.pexels.com/sd.mp4"


def test_select_placement_pexels_freezes_clip_and_license(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _fake_download(url: str, destination: Path) -> None:
        Path(destination).write_bytes(b"fake-pexels-mp4")

    monkeypatch.setattr(story_assets, "download_trusted_pexels_file", _fake_download)
    monkeypatch.setattr(
        "app.core.placement._probe_placement_clip_duration", lambda _path: 4.0
    )

    root = tmp_path / "proj"
    root.mkdir()
    (root / ".vcg-private").write_text("private\n", encoding="utf-8")
    manifest = root / f"show{VIDEO_PROJECT_SUFFIX}"
    manifest.write_text("{}", encoding="utf-8")
    write_placement_original(root, {"schemaVersion": 1, "beats": []})

    result = select_placement_pexels(
        manifest,
        {
            "id": "99",
            "provider": "pexels",
            "downloadUrl": "https://videos.pexels.com/video-files/99.mp4",
            "creator": "Ada",
            "creatorUrl": "https://www.pexels.com/@ada",
            "assetPage": "https://www.pexels.com/video/99/",
            "width": 1920,
            "height": 1080,
            "durationSec": 4,
        },
    )
    assert result["assetId"] == "pexels-99"
    assert result["durationSec"] == 4.0
    assert result["license"] == "Pexels License"
    clip = root / "assets" / "placement" / "pexels-99.mp4"
    evidence = root / "assets" / "placement" / "licenses" / "pexels-99.json"
    assert clip.is_file()
    assert evidence.is_file()
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    assert payload["provider"] == "pexels"
    assert payload["providerAssetId"] == "99"
    assert payload["sha256"]


def test_search_pexels_videos_requests_page_and_keeps_full_page(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            payload = {
                "page": 2,
                "per_page": 20,
                "total_results": 240,
                "videos": [
                    {
                        "id": 11,
                        "duration": 8,
                        "url": "https://www.pexels.com/video/11/",
                        "image": "https://images.pexels.com/11.jpg",
                        "user": {"name": "Ada", "url": "https://www.pexels.com/@ada"},
                        "video_files": [
                            {
                                "width": 1920,
                                "height": 1080,
                                "file_type": "video/mp4",
                                "quality": "hd",
                                "link": "https://videos.pexels.com/11.mp4",
                            }
                        ],
                    }
                ],
            }
            return json.dumps(payload).encode("utf-8")

    def _open(request, timeout=30):
        captured["url"] = request.full_url
        return _Resp()

    monkeypatch.setattr(story_assets, "pexels_settings", lambda: {"apiKey": "x" * 20, "source": "test"})
    monkeypatch.setattr(story_assets.urllib.request, "urlopen", _open)
    result = story_assets.search_pexels_videos({"query": "office"}, limit=20, page=2)
    assert "page=2" in captured["url"]
    assert "per_page=20" in captured["url"]
    assert "size=large" in captured["url"]
    assert "orientation=landscape" in captured["url"]
    assert result["page"] == 2
    assert result["totalResults"] == 240
    assert result["hasPrev"] is True
    assert result["hasNext"] is True
    assert len(result["candidates"]) == 1


def test_search_pexels_videos_sends_size_and_max_duration(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"page": 1, "per_page": 20, "total_results": 0, "videos": []}).encode("utf-8")

    def _open(request, timeout=30):
        captured["url"] = request.full_url
        return _Resp()

    monkeypatch.setattr(story_assets, "pexels_settings", lambda: {"apiKey": "x" * 20, "source": "test"})
    monkeypatch.setattr(story_assets.urllib.request, "urlopen", _open)
    story_assets.search_pexels_videos(
        {"query": "city", "size": "medium", "minDurationSec": 4, "maxDurationSec": 12},
        page=1,
    )
    assert "size=medium" in captured["url"]
    assert "min_duration=4" in captured["url"]
    assert "max_duration=12" in captured["url"]


def test_list_placement_clips_reuses_frozen_pexels(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_download(url: str, destination: Path) -> None:
        Path(destination).write_bytes(b"fake-pexels-mp4")

    monkeypatch.setattr(story_assets, "download_trusted_pexels_file", _fake_download)
    monkeypatch.setattr("app.core.placement._probe_placement_clip_duration", lambda _path: 4.0)
    root = tmp_path / "proj"
    root.mkdir()
    (root / ".vcg-private").write_text("private\n", encoding="utf-8")
    manifest = root / f"show{VIDEO_PROJECT_SUFFIX}"
    manifest.write_text("{}", encoding="utf-8")
    write_placement_original(root, {"schemaVersion": 1, "beats": []})
    select_placement_pexels(
        manifest,
        {
            "id": "77",
            "provider": "pexels",
            "downloadUrl": "https://videos.pexels.com/video-files/77.mp4",
            "creator": "Ada",
            "previewUrl": "https://images.pexels.com/77.jpg",
            "width": 1920,
            "height": 1080,
            "durationSec": 4,
        },
    )
    listed = list_placement_clips(manifest)["clips"]
    assert listed[0]["assetId"] == "pexels-77"
    assert listed[0]["provider"] == "pexels"
    assert listed[0]["previewUrl"] == "https://images.pexels.com/77.jpg"
    path = placement_library_video_path(manifest, "pexels-77")
    assert path.is_file()
    with pytest.raises(ValueError, match="Invalid clip id"):
        placement_library_video_path(manifest, "../secret")


def test_select_placement_pexels_rejects_untrusted_host(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    (root / ".vcg-private").write_text("private\n", encoding="utf-8")
    manifest = root / f"show{VIDEO_PROJECT_SUFFIX}"
    manifest.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="not trusted"):
        select_placement_pexels(
            manifest,
            {
                "id": "1",
                "provider": "pexels",
                "downloadUrl": "https://attacker.example/steal.mp4",
            },
        )
