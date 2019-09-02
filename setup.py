import setuptools

with open('README.md', 'r') as fh:
    long_description = fh.read()

setuptools.setup(
    name = 'm5preprocessor',
    version = '1.0',
    author = 'Eric Smith',
    author_email = 'spacewar@gmail.com',
    description = 'A simple macro preprocessor',
    long_description_content = long_description,
    long_description_content_type = 'text/markdown',
    url = 'https://github.com/brouhaha/m5preprocessor',
    packages = setuptools.find_packages(),
    classifiers = [
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
        "Operating System :: OS Independent",
    ],
    python_requires='>=3.6',
)
