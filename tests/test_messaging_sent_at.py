"""Horodatage des messages du thread DOM (issue #13) — fonction pure."""

import pytest

from linkedin_scraper.scrapers.messaging import sent_at_from_event_urn

SELF = "ACoAAAEKNzwB4E69dZJoooWDrlDaPEU8Mpaezoc"
# base64 de "1789378069865b45920-100&8ce2069a" : epoch ms en tête
URN = f"urn:li:msg_message:(urn:li:fsd_profile:{SELF},2-MTc4OTM3ODA2OTg2NWI0NTkyMC0xMDAmOGNlMjA2OWE=)"


def test_sent_at_is_decoded_from_the_epoch_embedded_in_the_urn():
    assert sent_at_from_event_urn(URN) == "2026-09-14T09:27:49.865000+00:00"


@pytest.mark.parametrize(
    "urn",
    [None, "", "urn:li:msg_message:garbage", "urn:li:msg_message:(urn:li:fsd_profile:x,2-!!!)"],
)
def test_sent_at_is_none_without_a_decodable_timestamp(urn):
    assert sent_at_from_event_urn(urn) is None


def _urn(token):
    return f"urn:li:msg_message:(urn:li:fsd_profile:{SELF},2-{token})"


@pytest.mark.parametrize(
    "token",
    [
        "MTc4OTM3ODA2OTg2NTFhYmM",  # préfixe de 14 chiffres : pas un epoch ms
        "OTk5OTk5OTk5OTk5OXg",  # an 2286
        "MDAwMDAwMDAwMDAwMXg",  # 1970
    ],
)
def test_sent_at_rejects_implausible_timestamps(token):
    assert sent_at_from_event_urn(_urn(token)) is None


def test_sent_at_survives_non_ascii_bytes_after_the_epoch():
    # "1789378069865é" : epoch valide suivi d'un octet non ASCII
    assert sent_at_from_event_urn(_urn("MTc4OTM3ODA2OTg2NcOp")) == "2026-09-14T09:27:49.865000+00:00"
