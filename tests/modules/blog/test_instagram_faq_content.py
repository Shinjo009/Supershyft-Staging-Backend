"""Instagram embed and FAQ content block shape / present / reject rules."""

import pytest

from modules.blog.content import normalize_blocks, present_blocks, reading_text, render_blocks
from modules.blog.errors import ApiError


def test_normalize_instagram_post_url():
    blocks = normalize_blocks(
        [
            {
                "tag": "instagram",
                "attributes": {"src": "https://www.instagram.com/p/ABC123xyz/"},
            }
        ]
    )
    assert blocks == [
        {
            "tag": "instagram",
            "attributes": {"src": "https://www.instagram.com/p/ABC123xyz/"},
        }
    ]


def test_normalize_instagram_reel_url():
    blocks = normalize_blocks(
        [{"tag": "instagram", "attributes": {"src": "https://instagram.com/reel/ReelCode99/?utm_source=ig"}}]
    )
    assert blocks[0]["attributes"]["src"] == "https://www.instagram.com/reel/ReelCode99/"


def test_normalize_rejects_non_instagram_url():
    with pytest.raises(ApiError, match="Instagram"):
        normalize_blocks(
            [{"tag": "instagram", "attributes": {"src": "https://example.com/p/ABC123/"}}]
        )


def test_normalize_rejects_instagram_profile_url():
    with pytest.raises(ApiError, match="Instagram"):
        normalize_blocks(
            [{"tag": "instagram", "attributes": {"src": "https://www.instagram.com/supershyft/"}}]
        )


def test_present_instagram():
    shown = present_blocks(
        [{"tag": "instagram", "attributes": {"src": "https://www.instagram.com/p/ABC123/"}}]
    )
    assert shown == [
        {"tag": "instagram", "attributes": {"src": "https://www.instagram.com/p/ABC123/"}}
    ]


def test_render_instagram_iframe_embed():
    html = render_blocks(
        [{"tag": "instagram", "attributes": {"src": "https://www.instagram.com/p/ABC123/"}}]
    )
    assert 'class="blog-instagram-iframe"' in html
    assert "https://www.instagram.com/p/ABC123/embed" in html
    assert "https://www.instagram.com/p/ABC123/" in html


def test_normalize_faq_block():
    blocks = normalize_blocks(
        [
            {
                "tag": "faq",
                "text": "Frequently Asked Questions",
                "items": [
                    {
                        "text": "What is SuperShyft?",
                        "marks": [],
                        "answer": {"text": "A preventive healthcare platform.", "marks": []},
                    },
                    {
                        "text": "What are biomarkers?",
                        "marks": [{"type": "bold", "start": 0, "end": 10}],
                        "answer": {"text": "Measurable health indicators.", "marks": []},
                    },
                ],
            }
        ]
    )
    assert blocks[0]["tag"] == "faq"
    assert blocks[0]["text"] == "Frequently Asked Questions"
    assert len(blocks[0]["items"]) == 2
    assert blocks[0]["items"][0]["answer"]["text"] == "A preventive healthcare platform."
    assert blocks[0]["items"][1]["marks"][0]["type"] == "bold"


def test_normalize_faq_defaults_heading():
    blocks = normalize_blocks(
        [
            {
                "tag": "faq",
                "items": [
                    {
                        "text": "Q1",
                        "marks": [],
                        "answer": {"text": "A1", "marks": []},
                    }
                ],
            }
        ]
    )
    assert blocks[0]["text"] == "Frequently Asked Questions"


def test_normalize_rejects_empty_faq():
    with pytest.raises(ApiError, match="FAQ"):
        normalize_blocks([{"tag": "faq", "text": "FAQ", "items": []}])


def test_normalize_rejects_faq_without_answer():
    with pytest.raises(ApiError, match="FAQ"):
        normalize_blocks(
            [
                {
                    "tag": "faq",
                    "items": [{"text": "Only a question", "marks": [], "answer": {"text": "", "marks": []}}],
                }
            ]
        )


def test_present_faq_block():
    shown = present_blocks(
        [
            {
                "tag": "faq",
                "text": "Frequently Asked Questions",
                "items": [
                    {
                        "text": "Q",
                        "marks": [],
                        "answer": {"text": "A", "marks": []},
                    }
                ],
            }
        ]
    )
    assert shown[0] == {
        "tag": "faq",
        "text": "Frequently Asked Questions",
        "items": [{"text": "Q", "marks": [], "answer": {"text": "A", "marks": []}}],
    }


def test_reading_text_includes_faq():
    text = reading_text(
        [
            {
                "tag": "faq",
                "text": "Frequently Asked Questions",
                "items": [
                    {
                        "text": "What is SuperShyft?",
                        "marks": [],
                        "answer": {"text": "A healthcare platform.", "marks": []},
                    }
                ],
            }
        ]
    )
    assert "Frequently Asked Questions" in text
    assert "What is SuperShyft?" in text
    assert "A healthcare platform." in text


def test_render_faq_accordion_markup():
    html = render_blocks(
        [
            {
                "tag": "faq",
                "text": "Frequently Asked Questions",
                "items": [
                    {
                        "text": "Q1",
                        "marks": [],
                        "answer": {"text": "A1", "marks": []},
                    }
                ],
            }
        ]
    )
    assert 'class="blog-faq"' in html
    assert "Frequently Asked Questions" in html
    assert 'class="blog-faq-question"' in html
    assert "Q1" in html
    assert "A1" in html
