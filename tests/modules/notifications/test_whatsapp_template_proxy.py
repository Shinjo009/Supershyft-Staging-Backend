from modules.notifications.whatsapp_template_proxy import normalize_template_response


def test_normalize_template_response_counts_body_slots():
    raw = {
        "data": [
            {
                "name": "camp17",
                "language": "en",
                "status": "APPROVED",
                "category": "UTILITY",
                "parameter_format": "POSITIONAL",
                "components": [
                    {
                        "type": "BODY",
                        "text": "Hello {{1}}, {{2}}",
                    }
                ],
            }
        ]
    }
    out = normalize_template_response(raw)
    assert out is not None
    assert out["body_positional_count"] == 2
    assert out["status"] == "APPROVED"


def test_normalize_template_response_header_document():
    raw = {
        "data": [
            {
                "name": "camp15",
                "status": "APPROVED",
                "components": [
                    {"type": "HEADER", "format": "DOCUMENT"},
                    {"type": "BODY", "text": "Hello {{1}}, {{2}}"},
                ],
            }
        ]
    }
    out = normalize_template_response(raw)
    assert out is not None
    assert out["header_format"] == "DOCUMENT"
    assert out["requires_header_document"] is True
    assert out["body_positional_count"] == 2


def test_normalize_template_response_body_examples():
    raw = {
        "data": [
            {
                "name": "con_comp",
                "language": "en",
                "status": "APPROVED",
                "category": "UTILITY",
                "parameter_format": "POSITIONAL",
                "components": [
                    {
                        "type": "BODY",
                        "text": "Hello {{1}},\n\nYour Supershyft {{2}} consultation",
                        "example": {"body_text": [["Name", "Doc/nutr"]]},
                    }
                ],
            }
        ]
    }
    out = normalize_template_response(raw)
    assert out is not None
    assert out["body_example_values"] == ["Name", "Doc/nutr"]
    assert "{{1}}" in out["body_text"]


def test_normalize_template_header_infers_document_from_example_handle():
    raw = {
        "data": [
            {
                "name": "camp15",
                "status": "APPROVED",
                "components": [
                    {
                        "type": "HEADER",
                        "format": "DOCUMENT",
                        "example": {"header_handle": ["https://example.com/a.pdf"]},
                    },
                    {"type": "BODY", "text": "Hello {{1}}"},
                ],
            }
        ]
    }
    out = normalize_template_response(raw)
    assert out is not None
    assert out["requires_header_document"] is True
    assert out["header_example_url"] == "https://example.com/a.pdf"


def test_normalize_template_response_header_example_image_and_video():
    image_raw = {
        "data": [
            {
                "name": "send_msg",
                "components": [
                    {
                        "type": "HEADER",
                        "format": "IMAGE",
                        "example": {"header_handle": ["https://example.com/sample.png"]},
                    },
                    {"type": "BODY", "text": "Hi {{1}}"},
                ],
            }
        ]
    }
    video_raw = {
        "data": [
            {
                "name": "inst_doc_2",
                "components": [
                    {
                        "type": "HEADER",
                        "format": "VIDEO",
                        "example": {"header_handle": ["https://example.com/sample.mp4"]},
                    },
                    {"type": "BODY", "text": "Hi {{1}}"},
                ],
            }
        ]
    }
    image = normalize_template_response(image_raw)
    video = normalize_template_response(video_raw)
    assert image is not None
    assert image["header_format"] == "IMAGE"
    assert image["header_example_url"] == "https://example.com/sample.png"
    assert video is not None
    assert video["header_format"] == "VIDEO"
    assert video["header_example_url"] == "https://example.com/sample.mp4"
