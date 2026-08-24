import json
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError, field_validator


class SourcesFileError(Exception):
    pass


class SourcesFileEntry(BaseModel):
    handle: str = Field(min_length=2)
    title: str | None = None
    enabled: bool

    @field_validator("handle")
    @classmethod
    def handle_starts_with_at(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped.startswith("@"):
            raise ValueError("handle must start with @")
        if len(stripped) < 2:
            raise ValueError("handle must contain a username after @")
        return stripped


def load_sources_file(path: Path) -> list[SourcesFileEntry]:
    raw_text = read_sources_file_text(path)
    payload = parse_sources_file_json(path, raw_text)
    entries = validate_sources_file_entries(path, payload)
    reject_duplicate_handles(path, entries)
    return entries


def read_sources_file_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as error:
        raise SourcesFileError(f"cannot read sources file {path}: {error}") from error


def parse_sources_file_json(path: Path, raw_text: str) -> object:
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError as error:
        raise SourcesFileError(f"sources file {path} is not valid JSON: {error}") from error


def validate_sources_file_entries(path: Path, payload: object) -> list[SourcesFileEntry]:
    if not isinstance(payload, list):
        raise SourcesFileError(f"sources file {path} must contain a JSON array of objects")
    entries: list[SourcesFileEntry] = []
    for index, item in enumerate(payload):
        try:
            entries.append(SourcesFileEntry.model_validate(item))
        except ValidationError as error:
            raise SourcesFileError(f"sources file {path}, entry #{index}: {error}") from error
    return entries


def reject_duplicate_handles(path: Path, entries: list[SourcesFileEntry]) -> None:
    seen: set[str] = set()
    for entry in entries:
        key = entry.handle.lower()
        if key in seen:
            raise SourcesFileError(f"sources file {path} contains duplicate handle {entry.handle}")
        seen.add(key)
