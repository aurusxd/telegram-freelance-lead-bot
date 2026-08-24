from pathlib import Path

import pytest

from app.services.chat_service import SourcesFileError, load_sources_file
from tests.conftest import write_sources_file


def test_loads_valid_entries(tmp_path: Path) -> None:
    path = write_sources_file(
        tmp_path,
        [
            {"handle": "@first_chat", "title": "Первый", "enabled": True},
            {"handle": "@second_chat", "enabled": False},
        ],
    )

    entries = load_sources_file(path)

    assert [entry.handle for entry in entries] == ["@first_chat", "@second_chat"]
    assert [entry.enabled for entry in entries] == [True, False]
    assert entries[1].title is None


def test_rejects_duplicate_handle(tmp_path: Path) -> None:
    path = write_sources_file(
        tmp_path,
        [
            {"handle": "@same_chat", "enabled": True},
            {"handle": "@SAME_chat", "enabled": True},
        ],
    )

    with pytest.raises(SourcesFileError, match="duplicate handle"):
        load_sources_file(path)


def test_rejects_broken_json(tmp_path: Path) -> None:
    path = tmp_path / "sources.json"
    path.write_text('[{"handle": "@chat", "enabled": true},]', encoding="utf-8")

    with pytest.raises(SourcesFileError, match="not valid JSON"):
        load_sources_file(path)


def test_rejects_handle_without_at(tmp_path: Path) -> None:
    path = write_sources_file(tmp_path, [{"handle": "chat", "enabled": True}])

    with pytest.raises(SourcesFileError, match="entry #0"):
        load_sources_file(path)


def test_rejects_missing_enabled_flag(tmp_path: Path) -> None:
    path = write_sources_file(tmp_path, [{"handle": "@chat"}])

    with pytest.raises(SourcesFileError, match="entry #0"):
        load_sources_file(path)


def test_rejects_non_array_payload(tmp_path: Path) -> None:
    path = write_sources_file(tmp_path, {"handle": "@chat", "enabled": True})

    with pytest.raises(SourcesFileError, match="JSON array"):
        load_sources_file(path)


def test_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(SourcesFileError, match="cannot read"):
        load_sources_file(tmp_path / "absent.json")
