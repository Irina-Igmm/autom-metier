import io
import csv
import json
import pytest
from src.tools.tools import (
    extract_text,
    extract_variables,
    safe_parse_json,
    generate_from_template,
    submit_form,
)


class DummyResponse:
    def __init__(self, content):
        self.content = content


def test_extract_text_txt_and_csv():
    txt_content = b"Hello\nWorld"
    txt_text = extract_text("test.txt", txt_content)
    assert "Hello" in txt_text
    assert "World" in txt_text

    csv_content = b"a,b,c\n1,2,3"
    csv_text = extract_text("test.csv", csv_content)
    # extract_text joins rows without newline
    assert "a,b,c" in csv_text
    assert "1,2,3" in csv_text


def test_extract_variables(monkeypatch):
    # Simuler l'invocation LLM qui renvoie un JSON
    monkeypatch.setattr("src.tools.tools.llm_extractor.invoke",
                        lambda msgs: '{"montant": 100}')
    result = extract_variables(b"dummy content", "test.pdf")
    assert isinstance(result, dict)
    assert result.get("montant") == 100


def test_parse_json_safely_valid_and_code_fence():
    valid = '{"key": "value"}'
    parsed = safe_parse_json(valid)
    assert parsed["key"] == "value"

    fenced = '```json\n{"foo": 123}```'
    parsed2 = safe_parse_json(fenced)
    assert parsed2["foo"] == 123

    bad = "not json"
    parsed3 = safe_parse_json(bad)
    assert "error" in parsed3


def test_generate_from_template():
    template = "Hello {{ name }}"
    variables = {"name": "Alice"}
    result = generate_from_template(template, variables)
    assert "Hello Alice" == result.strip()


def test_submit_form_error(monkeypatch):
    # Simuler un timeout ou échec de navigation
    monkeypatch.setattr("src.tools.tools.sync_playwright",
                        pytest.raises(Exception))
    res = submit_form("http://invalid.url", {"sel": "val"}, timeout=10)
    assert res["status"] == "error"
