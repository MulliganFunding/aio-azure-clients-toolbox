# just manual: https://github.com/casey/just#readme

_default:
    just --list

# Install dependencies used by this project
bootstrap default="3.12":
    uv venv --python {{default}}
    just sync

# Sync dependencies with environment
sync:
    uv sync

# Build the project as a package (uv build)
build *args:
    uv build

# Run the code formatter
format:
    uv run ruff format aio_azure_clients_toolbox tests

# Run code quality checks
check:
    #!/bin/bash -eux
    uv run ruff check aio_azure_clients_toolbox tests

# Run mypy checks
check-types:
    #!/bin/bash -eux
    uv run mypy aio_azure_clients_toolbox

# Run all tests locally
test *args:
    #!/bin/bash -eux
    uv run pytest {{args}}

# Run the project tests for CI environment (e.g. with code coverage)
ci-test coverage_dir='./coverage':
    uv run pytest --cov=aio_azure_clients_toolbox --cov-report xml --junitxml=./coverage/unittest.junit.xml
