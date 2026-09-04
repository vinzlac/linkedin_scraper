"""Browser lifecycle management for Playwright."""

import asyncio
import json
import logging
import os
import tempfile
import urllib.request
from pathlib import Path
from typing import Optional, Dict, Any
from playwright.async_api import async_playwright, Browser, BrowserContext, Page, Playwright

from .exceptions import NetworkError

logger = logging.getLogger(__name__)


# Champs de cookie que les Playwright récents écrivent dans un storage state et que
# les Chromium plus anciens rejettent via CDP (`Storage.setCookies: Invalid
# parameters`), faisant échouer la création du contexte — donc tout le scraping.
# Constaté le 2026-09-04 : session neuve refusée par le Chromium partagé du homelab
# (zenika/alpine-chrome:124) à cause de `partitionKey` (CHIPS).
_UNSUPPORTED_COOKIE_FIELDS = ("partitionKey",)


def sanitize_storage_state(filepath: str) -> Path:
    """Storage state débarrassé des champs de cookie qu'un vieux CDP refuse.

    Renvoie le chemin d'origine s'il n'y a rien à nettoyer (cas courant) ou si le
    fichier n'est pas exploitable — le nettoyage ne doit jamais faire échouer un
    démarrage qui aurait fonctionné. Sinon, écrit une copie nettoyée dans un fichier
    temporaire en mode 600 : le storage state contient les cookies de session.
    """
    path = Path(filepath)
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        cookies = state.get("cookies", [])
    except Exception as exc:
        logger.debug("Storage state illisible pour nettoyage (%s) : %s", path, exc)
        return path

    touched = [c for c in cookies if any(f in c for f in _UNSUPPORTED_COOKIE_FIELDS)]
    if not touched:
        return path

    for cookie in cookies:
        for field in _UNSUPPORTED_COOKIE_FIELDS:
            cookie.pop(field, None)

    fd, tmp = tempfile.mkstemp(prefix="linkedin_session_", suffix=".json")
    os.close(fd)
    tmp_path = Path(tmp)
    tmp_path.write_text(json.dumps(state), encoding="utf-8")
    os.chmod(tmp_path, 0o600)
    logger.info(
        "Storage state nettoyé : %s champ(s) de cookie non supporté(s) retiré(s) "
        "sur %s cookies", len(touched), len(cookies),
    )
    return tmp_path


def storage_state_cookies(filepath: str) -> list:
    """Cookies d'un storage state, débarrassés des champs qu'un vieux CDP refuse."""
    state = json.loads(Path(filepath).read_text(encoding="utf-8"))
    cookies = []
    for cookie in state.get("cookies", []):
        for field in _UNSUPPORTED_COOKIE_FIELDS:
            cookie.pop(field, None)
        cookies.append(cookie)
    return cookies


def normalize_headless_user_agent(user_agent: Optional[str]) -> Optional[str]:
    """User-agent sans le marqueur ``HeadlessChrome``.

    Un Chromium lancé en ``--headless=new`` annonce
    ``HeadlessChrome/124.0.0.0`` : c'est le signal d'automatisation le plus
    bruyant qu'on puisse envoyer, et il a valu au compte une vérification de
    sécurité LinkedIn le 2026-09-04 (cf. ADR-002, qui proscrit déjà le mode
    headless pour cette raison).

    On se contente de retirer le marqueur : inventer une autre version rendrait
    l'user-agent incohérent avec le reste de l'empreinte (version du moteur,
    client hints), ce qui est un signal plus mauvais encore.
    """
    if not user_agent:
        return None
    return user_agent.replace("HeadlessChrome/", "Chrome/")


class BrowserManager:
    """Async context manager for Playwright browser lifecycle."""
    
    def __init__(
        self,
        headless: bool = True,
        slow_mo: int = 0,
        viewport: Optional[Dict[str, int]] = None,
        user_agent: Optional[str] = None,
        cdp_url: Optional[str] = None,
        persistent_context: bool = False,
        **launch_options: Any
    ):
        """
        Initialize browser manager.

        Args:
            headless: Run browser in headless mode (ignored when cdp_url is set —
                the remote browser's own launch flags decide that)
            slow_mo: Slow down operations by specified milliseconds (ignored when
                cdp_url is set)
            viewport: Browser viewport size (default: 1280x720)
            user_agent: Custom user agent string
            cdp_url: Connect to an existing Chromium over the DevTools Protocol
                (e.g. "http://192.168.1.153:9222") instead of launching a new
                local browser. See ADR-017: the browser then runs on a remote
                host and no window ever appears locally, regardless of headless.
            persistent_context: réutiliser le contexte du navigateur distant
                (son profil sur disque) au lieu d'en créer un isolé à chaque
                démarrage. Sans effet hors CDP.

                LinkedIn traite un contexte neuf comme un appareil inconnu et
                redemande une vérification de sécurité : le 2026-09-04, un
                identifiant de challenge différent est apparu à chaque scrape,
                quels que soient la session, l'IP ou la version du navigateur.
                Le profil persistant donne un appareil stable, pour lequel une
                seule vérification suffit.

                Contrepartie : les cookies vivent dans le profil du navigateur,
                partagé avec ses autres clients — à n'activer que sur un
                navigateur dédié.
            **launch_options: Additional Playwright launch options (ignored when
                cdp_url is set)
        """
        self.headless = headless
        self.slow_mo = slow_mo
        self.viewport = viewport or {"width": 1280, "height": 720}
        self.user_agent = user_agent
        self.cdp_url = cdp_url
        self.persistent_context = persistent_context
        self.launch_options = launch_options

        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        # False quand le contexte appartient au navigateur distant : le fermer
        # couperait l'herbe sous le pied de ses autres clients.
        self._owns_context = True
        self._page: Optional[Page] = None
        self._is_authenticated = False
    
    async def __aenter__(self) -> "BrowserManager":
        """Start browser and create context."""
        await self.start()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Close browser and cleanup."""
        await self.close()
    
    async def start(self) -> None:
        """Start Playwright and either connect to an existing browser (CDP) or
        launch a new local one."""
        try:
            self._playwright = await async_playwright().start()

            if self.cdp_url:
                self._browser = await self._playwright.chromium.connect_over_cdp(
                    self.cdp_url
                )
                logger.info(f"Connected to existing browser via CDP: {self.cdp_url}")
                if not self.user_agent:
                    self.user_agent = normalize_headless_user_agent(
                        self._probe_cdp_user_agent()
                    )
                    if self.user_agent:
                        logger.info("User-agent du contexte : %s", self.user_agent)
            else:
                self._browser = await self._playwright.chromium.launch(
                    headless=self.headless,
                    slow_mo=self.slow_mo,
                    **self.launch_options
                )
                logger.info(f"Browser launched (headless={self.headless})")

            # Create context
            context_options: Dict[str, Any] = {
                "viewport": self.viewport,
            }
            
            if self.user_agent:
                context_options["user_agent"] = self.user_agent

            if self._use_persistent_context():
                self._context = self._browser.contexts[0]
                self._owns_context = False
                logger.info("Contexte persistant du navigateur distant réutilisé")
            else:
                self._context = await self._browser.new_context(**context_options)
                self._owns_context = True
            
            # Create initial page
            self._page = await self._context.new_page()
            
            logger.info("Browser context and page created")
            
        except Exception as e:
            await self.close()
            raise NetworkError(f"Failed to start browser: {e}")
    
    def _use_persistent_context(self) -> bool:
        """True si l'on doit réutiliser le contexte du navigateur distant."""
        return bool(
            self.persistent_context
            and self.cdp_url
            and self._browser
            and self._browser.contexts
        )

    def _probe_cdp_user_agent(self) -> Optional[str]:
        """User-agent annoncé par le navigateur distant, via ``/json/version``.

        Best effort : un échec de sonde laisse simplement le contexte hériter de
        l'user-agent du navigateur, comportement d'avant.
        """
        if not self.cdp_url:
            return None
        try:
            with urllib.request.urlopen(
                f"{self.cdp_url.rstrip('/')}/json/version", timeout=5
            ) as resp:
                return json.loads(resp.read().decode()).get("User-Agent")
        except Exception as exc:
            logger.debug("Sonde user-agent CDP en échec : %s", exc)
            return None

    async def close(self) -> None:
        """Close browser and cleanup resources."""
        try:
            if self._page:
                await self._page.close()
                self._page = None
            
            if self._context:
                if self._owns_context:
                    await self._context.close()
                else:
                    logger.debug(
                        "Contexte persistant laissé ouvert (il appartient au "
                        "navigateur distant)"
                    )
                self._context = None
                self._owns_context = True
            
            if self._browser:
                # For a CDP connection, Playwright's Browser.close() disconnects
                # the client rather than killing the remote browser process —
                # safe to call unconditionally, it never terminates a shared
                # Chromium (e.g. the openclaw chromium-cdp-host/pod) that other
                # clients may still be using.
                await self._browser.close()
                self._browser = None

            if self._playwright:
                await self._playwright.stop()
                self._playwright = None

            logger.info(
                "Browser disconnected (CDP)" if self.cdp_url else "Browser closed"
            )
            
        except Exception as e:
            logger.error(f"Error closing browser: {e}")
    
    async def new_page(self) -> Page:
        """
        Create a new page in the current context.
        
        Returns:
            New Playwright page
        """
        if not self._context:
            raise RuntimeError("Browser context not initialized. Call start() first.")
        
        page = await self._context.new_page()
        return page
    
    @property
    def page(self) -> Page:
        """
        Get the main page.
        
        Returns:
            Main Playwright page
        """
        if not self._page:
            raise RuntimeError("Browser not started. Use async context manager or call start().")
        return self._page
    
    @property
    def context(self) -> BrowserContext:
        """
        Get the browser context.
        
        Returns:
            Playwright browser context
        """
        if not self._context:
            raise RuntimeError("Browser context not initialized.")
        return self._context
    
    @property
    def browser(self) -> Browser:
        """
        Get the browser instance.
        
        Returns:
            Playwright browser
        """
        if not self._browser:
            raise RuntimeError("Browser not started.")
        return self._browser
    
    async def save_session(self, filepath: str) -> None:
        """
        Save browser session (cookies and storage) to file.
        
        Args:
            filepath: Path to save session file
        """
        if not self._context:
            raise RuntimeError("No browser context to save")
        
        storage_state = await self._context.storage_state()
        
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(filepath, 'w') as f:
            json.dump(storage_state, f, indent=2)
        
        logger.info(f"Session saved to {filepath}")
    
    async def load_session(self, filepath: str) -> None:
        """
        Load browser session from file.
        
        Args:
            filepath: Path to session file
        """
        if not Path(filepath).exists():
            raise FileNotFoundError(f"Session file not found: {filepath}")
        
        # Fermer le contexte courant — sauf s'il appartient au navigateur distant :
        # en mode persistant c'est son contexte par défaut, le détruire revient à
        # jeter le profil (et donc l'appareil connu de LinkedIn) à chaque
        # chargement de session, en plus de casser ses autres clients.
        if self._context:
            if self._owns_context:
                await self._context.close()
            self._context = None
        
        if not self._browser:
            raise RuntimeError("Browser not started")
        
        if self._use_persistent_context():
            self._context = self._browser.contexts[0]
            self._owns_context = False
            await self._context.add_cookies(storage_state_cookies(filepath))
            logger.info(
                "Session injectée dans le contexte persistant du navigateur distant"
            )
            if self._page:
                await self._page.close()
            self._page = await self._context.new_page()
            self._is_authenticated = True
            return

        state_path = sanitize_storage_state(filepath)
        try:
            self._context = await self._browser.new_context(
                storage_state=str(state_path),
                viewport=self.viewport,
                user_agent=self.user_agent
            )
            self._owns_context = True
        finally:
            # La copie nettoyée porte les cookies de session : elle ne survit pas
            # à la création du contexte (Playwright la lit de façon synchrone).
            if state_path != Path(filepath):
                try:
                    os.unlink(state_path)
                except OSError:
                    pass
        
        # Create new page
        if self._page:
            await self._page.close()
        self._page = await self._context.new_page()
        
        self._is_authenticated = True
        
        logger.info(f"Session loaded from {filepath}")
    
    async def set_cookie(self, name: str, value: str, domain: str = ".linkedin.com") -> None:
        """
        Set a single cookie.
        
        Args:
            name: Cookie name
            value: Cookie value
            domain: Cookie domain
        """
        if not self._context:
            raise RuntimeError("No browser context")
        
        await self._context.add_cookies([{
            "name": name,
            "value": value,
            "domain": domain,
            "path": "/"
        }])
        
        logger.debug(f"Cookie set: {name}")
    
    @property
    def is_authenticated(self) -> bool:
        """Check if user is authenticated."""
        return self._is_authenticated
    
    @is_authenticated.setter
    def is_authenticated(self, value: bool) -> None:
        """Set authentication status."""
        self._is_authenticated = value
