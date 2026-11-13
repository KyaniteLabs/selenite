from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_ci_runs_pane_queries_with_pinned_query_core():
    for path in (".forgejo/workflows/ci.yml", ".github/workflows/validate.yml"):
        workflow = (ROOT / path).read_text()
        assert "@tanstack/query-core@5.83.0" in workflow
        assert 'TANSTACK_QUERY_CORE="$RUNNER_TEMP/query-core/node_modules/@tanstack/query-core"' in workflow
        assert "tests/test_pane_queries.mjs" in workflow


def test_native_hermes_job_fails_on_skipped_tests():
    for path in (".forgejo/workflows/ci.yml", ".github/workflows/validate.yml"):
        workflow = (ROOT / path).read_text()
        hermes_job = workflow.split("  hermes-validate:", 1)[1]
        assert "pytest -q -rs" in hermes_job
        assert 'grep -q "^SKIPPED"' in hermes_job
        assert "exit 1" in hermes_job


def test_github_hermes_job_uses_the_pinned_source_and_runs_native_tests():
    workflow = (ROOT / ".github/workflows/validate.yml").read_text()
    hermes_job = workflow.split("  hermes-validate:", 1)[1]
    assert "2bd378ed1b8d6bf2192cb26e0a55ff3091e6bd19" in hermes_job
    assert "git -C .hermes-runtime fetch -q --depth 1" in hermes_job
    assert 'SELENITE_TEST_HERMES_SOURCE="$(cd ../.hermes-runtime && pwd)"' in hermes_job
