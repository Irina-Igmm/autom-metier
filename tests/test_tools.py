import io
import csv
from src.tools.tools import (
    extract_text_from_bytes,
    _parse_json_safely,
    generate_email,
    fill_html_template,
)


class DummyResponse:
    def __init__(self, content):
        self.content = content


def test_extract_text_txt_and_csv():
    txt_content = b"Hello\nWorld"
    txt_text = extract_text_from_bytes("test.txt", txt_content)
    assert "Hello" in txt_text

    csv_content = "a,b,c\n1,2,3".encode()
    csv_text = extract_text_from_bytes("test.csv", csv_content)
    assert "a b c" in csv_text
    assert "1 2 3" in csv_text


def test_parse_json_safely_valid_and_code_fence():
    valid = '{"key": "value"}'
    parsed = _parse_json_safely(valid)
    assert parsed["key"] == "value"

    fenced = '```json\n{"foo": 123}```'
    parsed2 = _parse_json_safely(fenced)
    assert parsed2["foo"] == 123

    bad = "not json"
    parsed3 = _parse_json_safely(bad)
    assert "error" in parsed3


class MockLLM:
    def invoke(self, messages):
        return DummyResponse("Dear Alice, your order is confirmed.")


def test_generate_email(monkeypatch):
    # Monkeypatch LLM with object that has invoke method
    monkeypatch.setattr("src.tools.tools.llm_generation", MockLLM())
    variables = {"name": "Alice"}
    template = "Hello {{ name }}"
    result = generate_email(variables, template)
    assert "Alice" in result
    assert "order is confirmed" in result


def test_fill_html_template():
    template = "<p>Hello {{ name }}</p>"
    output = fill_html_template(template, {"name": "Bob"})
    assert "<p>Hello Bob</p>" in output
