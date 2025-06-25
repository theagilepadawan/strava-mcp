from setuptools import setup, find_packages

setup(
    name="create-strava-mcp",  # ← Package name uses dashes
    version="1.0.0",
    author="Your Name",
    author_email="your.email@example.com",
    description="Automated setup tool for Strava MCP integration with Claude Desktop",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    url="https://github.com/your-username/strava-mcp",
    py_modules=["setup_strava_mcp"],  # ← Python module uses underscores
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
        # No dependencies for the setup tool itself
    ],
    entry_points={
        "console_scripts": [
            "create-strava-mcp=setup_strava_mcp:main",  # ← Entry point: dash=underscore:function
        ],
    },
)
