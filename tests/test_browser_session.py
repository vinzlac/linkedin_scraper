"""Tests du chargement de session et de l'empreinte du navigateur (incident 2026-09-04)."""
import json

from linkedin_scraper.core.browser import (
    normalize_headless_user_agent,
    sanitize_storage_state,
)


class TestSanitizeStorageState:
    """Le Chromium partagé du homelab (zenika/alpine-chrome:124, via CDP) rejette
    l'attribut de cookie `partitionKey` (CHIPS) que les Playwright récents écrivent
    dans le storage state : `Storage.setCookies: Invalid parameters`. Toute rotation
    de session cassait donc le démarrage du navigateur."""

    def _state(self, tmp_path, cookies):
        p = tmp_path / "session.json"
        p.write_text(json.dumps({"cookies": cookies, "origins": []}), encoding="utf-8")
        return p

    def test_drops_partition_key(self, tmp_path):
        src = self._state(tmp_path, [
            {"name": "li_at", "value": "x", "domain": ".linkedin.com", "path": "/"},
            {"name": "_px3", "value": "y", "domain": ".linkedin.com", "path": "/",
             "partitionKey": {"sourceOrigin": "https://www.linkedin.com",
                              "hasCrossSiteAncestor": False}},
        ])

        out = sanitize_storage_state(str(src))
        data = json.loads(out.read_text(encoding="utf-8"))

        assert len(data["cookies"]) == 2, "aucun cookie ne doit être perdu"
        assert all("partitionKey" not in c for c in data["cookies"])
        assert data["cookies"][0]["value"] == "x"

    def test_returns_the_original_path_when_nothing_to_clean(self, tmp_path):
        src = self._state(tmp_path, [{"name": "li_at", "value": "x",
                                      "domain": ".linkedin.com", "path": "/"}])
        assert sanitize_storage_state(str(src)) == src

    def test_unreadable_file_is_returned_untouched(self, tmp_path):
        p = tmp_path / "broken.json"
        p.write_text("pas du json", encoding="utf-8")
        assert sanitize_storage_state(str(p)) == p


class TestNormalizeHeadlessUserAgent:
    """Le navigateur partagé annonce `HeadlessChrome/124.0.0.0` : c'est le signal
    d'automatisation le plus bruyant qu'on puisse envoyer, et il a valu au compte une
    vérification de sécurité le 2026-09-04. On retire le marqueur sans inventer une
    autre version — un numéro incohérent avec le reste de l'empreinte serait pire."""

    def test_replaces_the_headless_marker(self):
        ua = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "HeadlessChrome/124.0.0.0 Safari/537.36")
        out = normalize_headless_user_agent(ua)
        assert "HeadlessChrome" not in out
        assert "Chrome/124.0.0.0" in out
        assert out.endswith("Safari/537.36")

    def test_leaves_a_normal_user_agent_alone(self):
        ua = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
        assert normalize_headless_user_agent(ua) == ua

    def test_handles_missing_user_agent(self):
        assert normalize_headless_user_agent(None) is None
        assert normalize_headless_user_agent("") is None
