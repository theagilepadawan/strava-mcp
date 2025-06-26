from setuptools import setup, find_packages

setup(
    name="create-strava-mcp",
    version="1.0.0",
    author="Michael Gundersen",
    author_email="michael.nesodden@gmail.com",
    description="Automated setup tool for Strava MCP integration with Claude Desktop",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    url="https://github.com/theagilepadawan/strava-mcp",
    py_modules=["setup_strava_mcp"],
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
    python_requires=">=3.8",
    install_requires=[
        "requests>=2.31.0",
        "toml",
        "dotenv",
        "mcp",
        "pydantic",
    ],
    entry_points={
        "console_scripts": [
            "create-strava-mcp=setup_strava_mcp:main",
        ],
    },
)
