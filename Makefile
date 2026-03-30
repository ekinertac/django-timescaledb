.PHONY: db-up db-down test test-39 test-310 test-311 test-312 test-313 test-all

db-up:
	docker compose up -d

db-down:
	docker compose down

# Run against the current Python in the uv environment
test:
	uv run --extra test pytest

# Run against specific Python versions (uv downloads the interpreter if absent)
test-39:
	uv run --python 3.9 --extra test --with "Django>=4.2,<5.0" pytest

test-310:
	uv run --python 3.10 --extra test pytest

test-311:
	uv run --python 3.11 --extra test pytest

test-312:
	uv run --python 3.12 --extra test pytest

test-313:
	uv run --python 3.13 --extra test pytest

# Run all Python versions in sequence
test-all: test-39 test-310 test-311 test-312 test-313
