import setuptools
import os

__version__ = '0.0.1'

here = os.path.abspath(os.path.dirname(__file__))

# read README for long description
with open(os.path.join(here, "README.md")) as f:
    readme_content = f.read()

# list dependencies
with open(os.path.join(here, "requirements.txt")) as f:
    requirements = f.read().split("\n")

setuptools.setup(
    name='xdc',
    version=__version__,
    description="Use an XSens DOT from pure python code, with no external dependencies",
    long_description=readme_content,
    url="https://github.com/adamkewley/xdc",
    license="Apache 2.0",
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: Apache Software License',
    ],
    keywords="XSens DOT",
    py_modules=["xdc"],
    author="Adam Kewley",
    author_email="contact@adamkewley.com",
    install_requires=requirements,
    python_requires=">=3",
)
    
    
