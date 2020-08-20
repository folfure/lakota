#!/usr/bin/env python
from pathlib import Path
from setuptools import setup


def get_version():
    ini_path = Path(__file__).parent / 'nagra' / '__init__.py'
    for line in ini_path.open():
        if line.startswith('__version__'):
            return line.split('=')[1].strip("' \"\n")
    raise ValueError(f'__version__ line not found in {ini_path}')


long_description = """
Nagra is a columnar storage solution for timeseries.

Nagra organise reads and writes through a changelog inspired by
Git. This changelog provides: historisation, concurrency control and
ease of synchronisation across different storage backends.
"""

description = "Versioned columnar storage for timeseries"

setup(
    name="nagra",
    version=get_version(),
    description=description,
    long_description=long_description,
    author="Bertrand Chenal",
    url="https://github.com/bertrandchenal/nagra",
    license="MIT",
    packages=["nagra"],
    install_requires=["numpy", "numcodecs", "s3fs", "numexpr", "tabulate", "msgpack"],
    entry_points={"console_scripts": ["nagra = nagra.cli:run",],},
)
