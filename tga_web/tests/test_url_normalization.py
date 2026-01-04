import pytest

from tga_web.services.url_normalization import GuessComUrlNormalizer


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("", ""),
        ("   ", ""),
        ("example.com", "https://example.com"),
        ("example.com/path", "https://example.com/path"),
        ("example", "https://example.com"),
        ("example/path", "https://example.com/path"),
        ("localhost", "https://localhost"),                 # no .com appended
        ("localhost:5000", "https://localhost:5000"),       # no .com appended
        ("127.0.0.1", "https://127.0.0.1"),                 # no .com appended
        ("127.0.0.1:5000/test", "https://127.0.0.1:5000/test"),
        ("https://example.com", "https://example.com"),     # already has scheme -> unchanged
        ("http://example.com/a/b", "http://example.com/a/b"),
        ("HTTP://Example.com", "HTTP://Example.com"),       # unchanged (your regex allows case-insensitive)
    ],
)
def test_normalize_default_behavior(raw, expected):
    norm = GuessComUrlNormalizer(
        default_scheme="https",
        guess_com_if_no_dot=True,
        no_guess_hosts={"localhost", "127.0.0.1"},
    )
    assert norm.normalize(raw) == expected


def test_guess_com_disabled():
    norm = GuessComUrlNormalizer(
        default_scheme="https",
        guess_com_if_no_dot=False,
        no_guess_hosts={"localhost"},
    )
    assert norm.normalize("example") == "https://example"
    assert norm.normalize("example/path") == "https://example/path"


def test_default_scheme_respected():
    norm = GuessComUrlNormalizer(
        default_scheme="http",
        guess_com_if_no_dot=True,
        no_guess_hosts={"localhost"},
    )
    assert norm.normalize("example") == "http://example.com"
    assert norm.normalize("example.com") == "http://example.com"


def test_no_guess_hosts_case_insensitive():
    norm = GuessComUrlNormalizer(
        default_scheme="https",
        guess_com_if_no_dot=True,
        no_guess_hosts={"LocalHost"},
    )
    # implementation lower()s host before checking, so this should still be excluded from .com guessing
    assert norm.normalize("localhost") == "https://localhost"
