# How to Publish FinOps AI to PyPI 📦

This guide outlines the steps to build and publish the **FinOps AI** package to the Python Package Index (PyPI).

## Prerequisites

1.  **PyPI Account**: Create an account at [pypi.org](https://pypi.org/).
2.  **API Token**: Go to Account Settings > API Tokens and create a new token with "upload" scope.
3.  **Build Tools**: Ensure you have `build` and `twine` installed:
    ```bash
    pip install build twine
    ```

## Step 1: Prepare the Package

1.  **Update Version**:
    Edit `src/finops_ai/__version__.py` and bump the version number (e.g., `0.1.0` -> `0.1.1`).

2.  **Clean Previous Builds**:
    ```bash
    rm -rf dist/ build/ *.egg-info
    ```

## Step 2: Build the Package

Run the build command from the project root:

```bash
python -m build
```

This will create two files in the `dist/` directory:
- `finops_ai-0.1.0-py3-none-any.whl` (Wheel)
- `finops_ai-0.1.0.tar.gz` (Source Archive)

## Step 3: Verify the Package (Optional but Recommended)

Check the package description and contents using Twine:

```bash
twine check dist/*
```

## Step 4: Upload to TestPyPI (Recommended for First Time)

TestPyPI is a separate instance of PyPI for testing and experimentation.

1.  Register at [test.pypi.org](https://test.pypi.org/).
2.  Upload:
    ```bash
    twine upload --repository testpypi dist/*
    ```
3.  Try installing it:
    ```bash
    pip install --index-url https://test.pypi.org/simple/ --no-deps finops-ai
    ```

## Step 5: Upload to PyPI (Production)

Once verified, upload to the real PyPI:

```bash
twine upload dist/*
```

You will be prompted for your username (use `__token__`) and your API token as the password.

## GitHub Releases

After publishing to PyPI, it's good practice to create a GitHub Release:

1.  Tag the commit: `git tag v0.1.0`
2.  Push tag: `git push origin v0.1.0`
3.  Go to GitHub > Releases > Draft a new release.
4.  Select `v0.1.0`, auto-generate release notes, and publish.

## Automated Publishing (GitHub Actions)

A workflow file `.github/workflows/publish.yml` can automate this process when you push a new tag.
