PYTHON  := .venv/bin/python
PIP     := .venv/bin/pip
PYTEST  := .venv/bin/pytest

.PHONY: install test test-unit test-sanity test-sanity-b lint clean help scan-demo generate-demo

## install       — install pytest + jsonschema into the project venv
install:
	$(PIP) install pytest jsonschema

## test           — run all unit + sanity tests (tool_a + tool_b)
test: test-unit test-sanity test-sanity-b

## test-unit      — run pytest unit tests in tests/
test-unit:
	$(PYTEST) tests/ -v

## test-sanity    — run tool_a sanity test suite
test-sanity:
	$(PYTHON) test_sanity.py

## test-sanity-b  — run tool_b sanity test suite
test-sanity-b:
	$(PYTHON) tests/test_tool_b_sanity.py

## lint           — syntax-check all source files (tool_a + tool_b + toolchain)
lint:
	$(PYTHON) -m py_compile \
		tool_a.py tool_a/__main__.py \
		tool_a/detector.py tool_a/framework_detector.py \
		tool_a/helper_registry.py tool_a/models.py \
		tool_a/redactor.py tool_a/reporter.py \
		tool_a/route_mapper.py tool_a/scanner.py \
		tool_a/scorer.py tool_a/serializer.py \
		tool_a/signals.py
	$(PYTHON) -m py_compile \
		tool_b.py tool_b/__main__.py \
		tool_b/jsonl_reader.py tool_b/context_selector.py \
		tool_b/prompt_assembler.py tool_b/agent_runner.py \
		tool_b/response_parser.py tool_b/output_writer.py \
		tool_b/agents/base.py tool_b/agents/claude.py \
		tool_b/agents/codex.py tool_b/agents/gemini.py \
		tool_b/agents/mock.py \
		toolchain/toolchain_validator.py
	@echo "Syntax OK"

## clean          — remove compiled bytecode and pytest cache
clean:
	find . -type d -name __pycache__ -not -path './.venv/*' -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -not -path './.venv/*' -delete
	rm -rf .pytest_cache

## scan-demo      — run a demo scan against the fixtures/ directory
scan-demo:
	$(PYTHON) tool_a.py scan --root fixtures/ --out report.md --raw raw.jsonl

## generate-demo  — dry-run tool_b against test.jsonl (no agent call)
generate-demo:
	$(PYTHON) tool_b.py generate \
		--jsonl test.jsonl \
		--out pattern_demo.json \
		--agent mock \
		--mock-response-file fixtures/fixture_mock_agent_valid.json \
		--dry-run

## help           — list available targets
help:
	@grep -E '^##' Makefile | sed 's/## /  /'
