import os
import pickle
import time
import asyncio
import toolbox.fs as fs
from typing import Optional
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
    headless: bool = True,
    no_close: bool = False,
    firefox: bool = False,
) -> BeautifulSoup | None:
    try:
        if not firefox:
            browser = await playwright.chromium.launch(headless=headless)
        else:
            browser = await playwright.firefox.launch(headless=headless)
        context = await browser.new_context()
        page = await context.new_page()
        await page.add_init_script(  # Enable stealth mode
            """
            Object.defineProperty(navigator, 'webdriver', {
                get: () => false,
            });
            """
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
        await page.goto(url)
        content = await page.content()
        soup = BeautifulSoup(content, "html.parser")
        if not no_close:
            await browser.close()
        return soup
    except Exception as e:
        err(e)
        warn(exc())
        return None


async def run_scraper(
    url: str, save_images: Optional[str] = None, firefox: bool = False
) -> BeautifulSoup | None:
    printc(f"Scraping: {url} ..", "black", "magenta")
    async with async_playwright() as playwright:
        return await run_playwright(
            playwright, url, save_images=save_images, firefox=firefox
        )


def load_from_cache(path: str, exp: int = _CACHE_EXP) -> BeautifulSoup | None:
    if exp <= 0:
        return None
    file_path = f"{path}.pkl"
    try:
        if os.path.exists(file_path):
            with open(file_path, "rb") as f:
                timestamp, soup = pickle.load(f)
                if time.time() - timestamp < exp:
                    printc(f"Loaded from cache: {file_path}", "black", "blue")
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
    url: str, save_images: bool = True, exp: int = _CACHE_EXP, firefox: bool = False
) -> tuple[BeautifulSoup | None, str, str]:
    debug(url, "URL to scrape", lvl=2)
    cache_path = fs.build_path([hash_str(url)], basedir=_CACHE_DIR)
    image_path = (
        fs.build_path([_CACHE_DIR], basedir=_MEDIA_DIR) if save_images else None
    )
    os.makedirs(cache_path, exist_ok=True)
    debug(cache_path, "cache path", lvl=2)
    soup = load_from_cache(cache_path, exp=exp)
    if soup is None:
        soup = asyncio.run(run_scraper(url, save_images=image_path, firefox=firefox))
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
