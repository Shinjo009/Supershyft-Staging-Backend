"""CTA button blocks: tag a + type button with link, styles, and alignment."""

import pytest

from modules.blog.content import (
    blocks_are_empty,
    normalize_blocks,
    present_blocks,
    render_blocks,
)
from modules.blog.errors import ApiError


CTA = {
    "tag": "a",
    "type": "button",
    "text": "Book Your Health Checkup",
    "attributes": {
        "href": "https://supershyft.com/gifting",
        "target": "_blank",
        "style": {
            "backgroundColor": "#0B2C2A",
            "color": "#FFFFFF",
            "fontSize": "16px",
            "fontWeight": "600",
            "borderRadius": "8px",
            "padding": "14px 28px",
        },
    },
    "alignment": "center",
}


def test_normalize_cta_button_preserves_shape():
    blocks = normalize_blocks([CTA])
    assert blocks == [
        {
            "tag": "a",
            "type": "button",
            "text": "Book Your Health Checkup",
            "attributes": {
                "href": "https://supershyft.com/gifting",
                "target": "_blank",
                "style": {
                    "backgroundColor": "#0B2C2A",
                    "color": "#FFFFFF",
                    "fontSize": "16px",
                    "fontWeight": "600",
                    "borderRadius": "8px",
                    "padding": "14px 28px",
                },
            },
            "alignment": "center",
        }
    ]


def test_normalize_omits_left_alignment():
    payload = {**CTA, "alignment": "left"}
    blocks = normalize_blocks([payload])
    assert "alignment" not in blocks[0]


def test_present_keeps_type_and_alignment():
    shown = present_blocks([CTA])
    assert shown[0]["type"] == "button"
    assert shown[0]["alignment"] == "center"
    assert shown[0]["attributes"]["href"] == "https://supershyft.com/gifting"


def test_cta_counts_as_content():
    assert blocks_are_empty([CTA]) is False
    assert blocks_are_empty([{"tag": "a", "type": "button", "text": "", "attributes": {"href": "https://x.com"}}]) is True


def test_render_cta_html():
    html = render_blocks([CTA])
    assert 'href="https://supershyft.com/gifting"' in html
    assert "Book Your Health Checkup" in html
    assert 'target="_blank"' in html
    assert "text-align:center" in html
    assert "background-color:#0B2C2A" in html


def test_reject_missing_href():
    with pytest.raises(ApiError, match="link"):
        normalize_blocks(
            [
                {
                    "tag": "a",
                    "type": "button",
                    "text": "Go",
                    "attributes": {"href": "not-a-url", "target": "_blank"},
                }
            ]
        )


def test_reject_anchor_without_button_type():
    with pytest.raises(ApiError, match="Unknown content block"):
        normalize_blocks([{"tag": "a", "text": "Go", "attributes": {"href": "https://example.com"}}])


def test_normalize_cta_border_styles():
    payload = {
        **CTA,
        "attributes": {
            **CTA["attributes"],
            "style": {
                **CTA["attributes"]["style"],
                "borderWidth": "2px",
                "borderColor": "#cc203b",
            },
        },
    }
    blocks = normalize_blocks([payload])
    style = blocks[0]["attributes"]["style"]
    assert style["borderWidth"] == "2px"
    assert style["borderColor"] == "#CC203B"
    html = render_blocks(blocks)
    assert "border:2px solid #CC203B" in html


def test_normalize_omits_zero_border_width():
    payload = {
        **CTA,
        "attributes": {
            **CTA["attributes"],
            "style": {
                **CTA["attributes"]["style"],
                "borderWidth": "0px",
                "borderColor": "#cc203b",
            },
        },
    }
    blocks = normalize_blocks([payload])
    style = blocks[0]["attributes"]["style"]
    assert "borderWidth" not in style
    assert "borderColor" not in style
