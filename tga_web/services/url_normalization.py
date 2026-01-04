import re
from dataclasses import dataclass


class UrlNormalizer:
    """Strategy interface."""
    def normalize(self, s: str) -> str:
        raise NotImplementedError


@dataclass(frozen=True)
class GuessComUrlNormalizer(UrlNormalizer):
    default_scheme: str = "https"
    guess_com_if_no_dot: bool = True
    no_guess_hosts: set[str] = None

    def normalize(self, s: str) -> str:
        s = (s or "").strip()
        if not s:
            return ""

        if re.match(r"^https?://", s, flags=re.IGNORECASE):
            return s

        parts = s.split("/", 1)
        host = parts[0].strip()
        rest = ("/" + parts[1]) if len(parts) > 1 else ""

        no_guess_hosts = self.no_guess_hosts or set()
        if self.guess_com_if_no_dot and "." not in host and host.lower() not in no_guess_hosts:
            host = host + ".com"

        return f"{self.default_scheme}://" + host + rest
