from setuptools import setup, find_packages

setup(
    name="webscraper",
    version="0.1.001",
    packages=find_packages(),
    install_requires=[
        "git+https://github.com/Valcrist/toolbox.git",
        "playwright",
        "bs4",
        "aiohttp",
        "aiofiles",
    ],
    url="https://github.com/Valcrist/webscraper",
    author="Valcrist",
    author_email="github@valcrist.com",
    description="Valcrist's web scraper",
)
