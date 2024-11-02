import os
import json
import pickle
import time
import asyncio
import toolbox.fs as fs
from typing import Optional
from pathlib import Path
from urllib.parse import urlparse
from fake_useragent import FakeUserAgent
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, Response
from toolbox.dot_env import get_env
from toolbox.hash import hash_str
from toolbox.utils import debug, err, warn, printc
from traceback import format_exc as exc


_CACHE_EXP = get_env("CACHE_EXP", 1800)  # seconds
_CACHE_DIR = get_env("CACHE_DIR", "cache")
_MEDIA_DIR = get_env("MEDIA_DIR", "media")
_IMPORT_DIR = get_env("IMPORT_DIR", "import")


def cfg_scraper(key: str, value: str | int) -> None:
    if key.lower() == "cache_exp":
        global _CACHE_EXP
        _CACHE_EXP = int(value)
        printc(f"CACHE_EXP set to: {_CACHE_EXP}", "black", "blue", pad=1)
    elif key.lower() == "cache_dir":
        global _CACHE_DIR
        _CACHE_DIR = value
        printc(f"CACHE_DIR set to: {_CACHE_DIR}", "black", "blue", pad=1)
    elif key.lower() == "media_dir":
        global _MEDIA_DIR
        _MEDIA_DIR = value
        printc(f"MEDIA_DIR set to: {_MEDIA_DIR}", "black", "blue", pad=1)
    elif key.lower() == "import_dir":
        global _IMPORT_DIR
        _IMPORT_DIR = value
        printc(f"IMPORT_DIR set to: {_IMPORT_DIR}", "black", "blue", pad=1)


async def run_playwright(
    playwright: async_playwright,
    url: str,
    save_images: Optional[str] = None,
    firefox: bool = True,
    headless: bool = True,
    close_browser: bool = True,
    use_cookies: bool = False,
    page_timeout: int = 30000,
    idle_wait: int = 30000,
    volume: float = 0.0,  # mute
) -> BeautifulSoup | None:
    try:
        if firefox:
            ua = FakeUserAgent(browsers=["firefox"], os=["windows"])
            firefox_ua = ua.random
            browser = await playwright.firefox.launch(
                headless=headless,
                firefox_user_prefs={
                    "privacy.webdriver.enabled": False,
                    "dom.webdriver.enabled": False,
                    "media.navigator.enabled": True,
                    "general.useragent.override": firefox_ua,
                    "dom.navigator.hardwareConcurrency": 8,
                    "dom.maxHardwareConcurrency": 8,
                    "dom.webdriver.enabled": False,
                    "webgl.disabled": False,
                    "canvas.capturestream.enabled": True,
                    "privacy.webdriver.enabled": False,
                    "media.peerconnection.enabled": False,
                    "media.volume_scale": str(volume),
                    "media.navigator.enabled": True,
                    "media.autoplay.default": 0,
                    "media.autoplay.blocking_policy": 0,
                },
            )
            context = await browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent=firefox_ua,
                has_touch=True,
                locale="en-US",
                timezone_id="Asia/Singapore",
                color_scheme="dark",
                reduced_motion="reduce",
            )
        else:
            ua = FakeUserAgent(browsers=["chrome"], os=["windows"])
            chrome_ua = ua.random
            browser = await playwright.chromium.launch(
                headless=headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-features=IsolateOrigins,site-per-process",
                    f"--user-agent={chrome_ua}",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                    "--enable-webgl",
                    "--enable-audio-service",
                    "--window-size=1920,1080",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-features=IsolateOrigins,site-per-process",
                ],
            )
            context = await browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent=chrome_ua,
                locale="en-US",
                timezone_id="Asia/Singapore",
                geolocation={"latitude": 1.3521, "longitude": 103.8198},
                permissions=["geolocation"],
                color_scheme="dark",
                reduced_motion="reduce",
                media_volume_scale=volume,
            )
        if use_cookies:
            domain = urlparse(url).netloc
            cookies_file = Path(f"cache/_cookies/{domain}_cookies.json")
            cookies_file.parent.mkdir(exist_ok=True)
            if cookies_file.exists():
                try:
                    with open(cookies_file) as f:
                        cookies = json.load(f)
                    await context.add_cookies(cookies)
                except Exception as e:
                    warn(f"Failed to load cookies: {e}")
        page = await context.new_page()
        firefox_script = """
            const overrides = {
                webdriver: false,
                languages: ['en-US', 'en'],
                plugins: [],  // Firefox typically has empty plugins
                mimeTypes: [],
                webglVendor: "Mozilla",
                webglRenderer: "Mozilla",
                hardwareConcurrency: 8,
                deviceMemory: 8,
                platform: "Win32",
            };
        """
        chrome_script = """
            const overrides = {
                webdriver: false,
                languages: ['en-US', 'en'],
                plugins: [
                    [{ description: "PDF Viewer", filename: "internal-pdf-viewer" }],
                    [{ description: "Chrome PDF Viewer", filename: "chrome-pdf-viewer" }],
                    [{ description: "Chromium PDF Viewer", filename: "chromium-pdf-viewer" }]
                ],
                webglVendor: "Google Inc. (Intel)",
                webglRenderer: "ANGLE (Intel, Intel(R) UHD Graphics Direct3D11 vs_5_0 ps_5_0)",
                hardwareConcurrency: 8,
                deviceMemory: 8,
                platform: "Win32",
            };
        """
        base_script = """
            Object.defineProperties(navigator, {
                ...Object.fromEntries(
                    Object.entries(overrides).map(([key, value]) => [
                        key,
                        { get: () => value }
                    ])
                )
            });
            delete navigator.__proto__.webdriver;
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications' ?
                Promise.resolve({ state: Notification.permission }) :
                originalQuery(parameters)
            );
        """
        await context.add_init_script(
            (firefox_script if firefox else chrome_script) + base_script
        )

        async def intercept(
            resp: Response,
        ):  # Intercept network requests to save images
            img_bytes = await resp.body()
            url_resp = resp.url
            url_split = url_resp.split("/")
            img_ext = os.path.splitext(url_split[-1])[1]
            if img_ext not in [
                ".jpg",
                ".png",
                ".jpeg",
                ".webp",
                ".gif",
                ".bmp",
                ".tiff",
            ]:
                return
            img_name = os.path.join(save_images, url_split[-2], url_split[-1])
            os.makedirs(os.path.dirname(img_name), exist_ok=True)
            with open(img_name, "wb+") as handler:
                handler.write(img_bytes)

        if save_images:
            page.on("response", intercept)
        await page.goto(
            url,
            timeout=page_timeout,
            wait_until="domcontentloaded",  # Less strict than 'load'
        )
        if idle_wait > 0:
            try:
                await page.wait_for_load_state("networkidle", timeout=idle_wait)
            except:
                print(
                    f"{url} - Network idle timeout ({idle_wait}ms); "
                    "continuing anyway"
                )
        if use_cookies:  # Save cookies after successful page load
            try:
                cookies = await context.cookies()
                for cookie in cookies:
                    if "expires" in cookie:
                        cookie["expires"] = int(
                            time.time() + 10 * 365 * 24 * 60 * 60
                        )  # set to 10 years to make it persistent
                with open(cookies_file, "w") as f:
                    json.dump(cookies, f)
            except Exception as e:
                warn(f"Failed to save cookies: {e}")
        content = await page.content()
        soup = BeautifulSoup(content, "html.parser")
        if close_browser:
            await browser.close()
        else:
            time.sleep(30)
        return soup
    except Exception as e:
        err(e)
        warn(exc())
        return None


async def run_scraper(
    url: str,
    save_images: Optional[str] = None,
    firefox: bool = True,
    headless: bool = True,
    close_browser: bool = True,
    use_cookies: bool = False,
    page_timeout: int = 30000,
    idle_wait: int = 30000,
    volume: float = 0.0,  # mute
) -> BeautifulSoup | None:
    printc(f"Scraping: {url} ..", "bright_magenta", pad=0, no_nl=True)
    async with async_playwright() as playwright:
        return await run_playwright(
            playwright,
            url,
            save_images=save_images,
            firefox=firefox,
            headless=headless,
            close_browser=close_browser,
            use_cookies=use_cookies,
            page_timeout=page_timeout,
            idle_wait=idle_wait,
            volume=volume,
        )


def load_from_cache(path: str, exp: int = _CACHE_EXP) -> BeautifulSoup | None:
    if exp == 0:
        return None
    file_path = f"{path}.pkl"
    try:
        if os.path.exists(file_path):
            with open(file_path, "rb") as f:
                timestamp, soup = pickle.load(f)
                if exp < 0 or time.time() - timestamp < exp:
                    print(f"Loaded from cache: {file_path}")
                    return soup
    except Exception as e:
        err(e)
    return None


def save_to_cache(path: str, soup: BeautifulSoup) -> None:
    file_path = f"{path}.pkl"
    try:
        with open(file_path, "wb") as f:
            pickle.dump((time.time(), soup), f)
    except Exception as e:
        err(e)


def scrape(
    url: str, save_images: bool = True, exp: int = _CACHE_EXP, firefox: bool = True
) -> tuple[BeautifulSoup | None, str, str]:
    print(f"URL to scrape: {url}")
    cache_path = fs.build_path([hash_str(url)], basedir=_CACHE_DIR)
    image_path = (
        fs.build_path([_CACHE_DIR], basedir=_MEDIA_DIR) if save_images else None
    )
    os.makedirs(cache_path, exist_ok=True)
    debug(cache_path, "cache path", lvl=3)
    soup = load_from_cache(cache_path, exp=exp)
    if soup is None:
        soup = asyncio.run(run_scraper(url, save_images=image_path, firefox=firefox))
        if soup:
            save_to_cache(cache_path, soup)
    if save_images:
        return soup, cache_path, image_path
    return soup, cache_path


async def async_scrape(
    url: str, save_images: bool = True, exp: int = _CACHE_EXP, firefox: bool = True
) -> tuple[BeautifulSoup | None, str, str]:
    print(f"URL to scrape: {url}")
    cache_path = fs.build_path([hash_str(url)], basedir=_CACHE_DIR)
    image_path = (
        fs.build_path([_CACHE_DIR], basedir=_MEDIA_DIR) if save_images else None
    )
    os.makedirs(cache_path, exist_ok=True)
    debug(cache_path, "cache path", lvl=3)
    soup = load_from_cache(cache_path, exp=exp)
    if soup is None:
        soup = await run_scraper(url, save_images=image_path, firefox=firefox)
        if soup:
            save_to_cache(cache_path, soup)
    if save_images:
        return soup, cache_path, image_path
    return soup, cache_path


def get_text_from_element_id(soup: BeautifulSoup, elt: str, id: str) -> str:
    try:
        item = soup.find(elt, id=id)
        if item:
            return item.get_text(strip=True)
    except Exception as e:
        err(e)
    return ""


def get_text_from_element_class(soup: BeautifulSoup, elt: str, cls: str) -> str:
    try:
        item = soup.find(elt, class_=cls)
        if item:
            return item.get_text(strip=True)
    except Exception as e:
        err(e)
    return ""
