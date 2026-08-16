.PHONY: install test lint format typecheck audit build bench demo clean

install:
	python -m pip install -e '.[dev]'

test:
	pytest -q --cov=vouchline --cov-report=term-missing

lint:
	ruff check src tests benchmarks

format:
	ruff format --check src tests benchmarks

typecheck:
	mypy src

audit:
	pip-audit -r requirements-audit.txt --strict

build:
	python -m build

bench:
	python benchmarks/bench.py

demo:
	mkdir -p .demo
	vouchline capture examples/sample_run.jsonl --output .demo/run.json --run-id demo-001
	vouchline verify .demo/run.json
	vouchline replay .demo/run.json
	vouchline assert .demo/run.json --policy examples/policy.json

clean:
	rm -rf .demo build dist *.egg-info .coverage htmlcov .pytest_cache .mypy_cache .ruff_cache
