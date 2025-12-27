from __future__ import annotations

from genai_tag_db_tools import core_api


class FakeRepo:
    def __init__(self, mapping: dict[str, str]) -> None:
        self._mapping = mapping

    def get_format_id(self, format_name: str) -> int | None:
        return 1 if format_name == "danbooru" else None

    def search_tags_bulk(
        self,
        keywords: list[str],
        *,
        format_name: str | None = None,
        resolve_preferred: bool = False,
    ) -> dict[str, dict[str, str]]:
        return {key: {"tag": self._mapping[key]} for key in keywords if key in self._mapping}


def test_convert_tags_normalizes_and_falls_back_to_words():
    repo = FakeRepo(
        {
            "blue hair": "blue hair",
            "red eyes": "red eyes",
            "object": "object",
        }
    )

    result = core_api.convert_tags(repo, "blue_hair\nmysterious object, red eyes", "danbooru")

    assert result == "blue hair, mysterious, object, red eyes"


def test_convert_tags_unknown_format_returns_original():
    repo = FakeRepo({"blue hair": "blue hair"})

    result = core_api.convert_tags(repo, "blue hair", "unknown")

    assert result == "blue hair"
