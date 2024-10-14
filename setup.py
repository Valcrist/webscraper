from setuptools import setup, find_packages

setup(
    name="webscraper",
    version="0.1.9",
    packages=find_packages(),
    install_requires=[
        "playwright",
        "bs4",
        "aiohttp",
        "aiofiles",
    ],
    dependency_links=[
        "git+https://github.com/Valcrist/toolbox.git#egg=toolbox",
    ],
    url="https://github.com/Valcrist/webscraper",
    author="Valcrist",
    author_email="github@valcrist.com",
    description="Valcrist's web scraper",
)
