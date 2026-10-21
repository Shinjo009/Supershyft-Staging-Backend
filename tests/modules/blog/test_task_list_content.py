"""Task list content shape: per-item checked with legacy array fallback."""

from modules.blog.content import normalize_blocks, present_blocks


def test_normalize_task_list_stores_checked_on_items():
    blocks = normalize_blocks(
        [
            {
                "tag": "ul",
                "attributes": {"listType": "task"},
                "items": [
                    {"text": "task1", "marks": [], "checked": False},
                    {"text": "task 2", "marks": [], "checked": True},
                ],
            }
        ]
    )
    assert blocks == [
        {
            "tag": "ul",
            "attributes": {"listType": "task"},
            "items": [
                {"text": "task1", "marks": [], "checked": False},
                {"text": "task 2", "marks": [], "checked": True},
            ],
        }
    ]
    assert "checked" not in blocks[0]


def test_normalize_accepts_legacy_parallel_checked_array():
    blocks = normalize_blocks(
        [
            {
                "tag": "ul",
                "attributes": {"listType": "task"},
                "items": [
                    {"text": "Old one", "marks": []},
                    {"text": "Old two", "marks": []},
                ],
                "checked": [False, True],
            }
        ]
    )
    assert blocks[0]["items"][0]["checked"] is False
    assert blocks[0]["items"][1]["checked"] is True
    assert "checked" not in blocks[0]


def test_present_task_list_uses_per_item_checked():
    shown = present_blocks(
        [
            {
                "tag": "ul",
                "attributes": {"listType": "task"},
                "items": [
                    {"text": "A", "marks": [], "checked": True},
                    {"text": "B", "marks": [], "checked": False},
                ],
            }
        ]
    )
    assert shown[0]["items"][0] == {"text": "A", "marks": [], "checked": True}
    assert shown[0]["items"][1] == {"text": "B", "marks": [], "checked": False}
    assert "checked" not in shown[0]


def test_present_legacy_parallel_checked_array():
    shown = present_blocks(
        [
            {
                "tag": "ul",
                "attributes": {"listType": "task"},
                "items": [
                    {"text": "A", "marks": []},
                    {"text": "B", "marks": []},
                ],
                "checked": [True, False],
            }
        ]
    )
    assert shown[0]["items"][0]["checked"] is True
    assert shown[0]["items"][1]["checked"] is False
    assert "checked" not in shown[0]
