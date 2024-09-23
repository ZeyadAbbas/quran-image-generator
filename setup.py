try:
    from setuptools import setup, find_packages
except ImportError:
    print(f"'setuptools' is required to install this program. Please install it using 'pip install setuptools' "
          f"and try again.\n"
          f"If you are experiencing issues doing this, please check ")
    import sys
    sys.exit(1)

with open('README.md', encoding="utf-8") as f:
    readme_file = f.read()

setup(
    name="quran_post_generator",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "requests",
        "wand>=0.6.13",
        "pyyaml",
        "colorama",
        "instagrapi>=2.0.0"
    ],
    author="Zeyad Abbas",
    author_email="zeyadabbas238@gmail.com",
    description="Generate endless fully customizable designs of Quran verses to post online",
    long_description=readme_file,
    url="https://github.com/ZeyadAbbas/quran-image-generator",
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires='>=3.10',
)
