# Contributing to AI Session Analyzer

Thanks for your interest in contributing! This guide will help you get started.

## Getting Started

1. Fork the repository
2. Clone your fork:
   ```bash
   git clone https://github.com/YOUR_USERNAME/AI-Session-Analyzer.git
   cd AI-Session-Analyzer
   ```
3. Create a feature branch:
   ```bash
   git checkout -b feature/your-feature-name
   ```

## Development Setup

No special setup needed — the project uses **zero external dependencies** (stdlib only).

```bash
# Verify your Python version (3.8+ required)
python3 --version

# Run the test suite
python3 -m unittest discover tests
```

## Compatibility Requirements

The codebase must remain compatible with **Python 3.8** through 3.13. This means:

- No walrus operator (`:=`)
- No `match` statements
- No generic type hints like `list[str]` or `dict[str, Any]` in annotations — use `List[str]`, `Dict[str, Any]` from `typing`
- No external dependencies — stdlib only

## Adding a New AI Agent Integration

See [`HOW_TO_ADD_A_PROVIDER.md`](HOW_TO_ADD_A_PROVIDER.md) for the 6-step checklist, including known performance pitfalls.

Each new integration should include:

1. Parser implementation in `process_sessions.py`
2. A `*_DATA_GUIDE.md` documenting the data format
3. Test class (e.g., `TestYourAgentIntegration`) with synthetic fixtures
4. CLI flag (`--your-agent-dir`)
5. Report files (sessions + model usage)
6. Section in `09_eficiencia_tokens.md`

## Running Tests

```bash
# All tests
python3 -m unittest discover tests

# Specific test class
python3 -m unittest tests.test_process_sessions.TestPiIntegration

# With pytest (if installed in your dev environment)
pytest
```

CI runs the full suite across **Python 3.8–3.13 × Ubuntu/macOS**. Make sure all tests pass before submitting a PR.

## Submitting Changes

1. Make sure all tests pass
2. Follow the existing code style (Spanish comments are fine — the codebase is bilingual)
3. Update relevant documentation if your change affects usage
4. Submit a pull request with a clear description of what changed and why

## Reporting Issues

When reporting a bug, please include:

- Python version
- OS (Ubuntu/macOS/Windows)
- The command you ran
- The error message or unexpected behavior
- A sample of the input data format (if relevant, anonymized)

## Code of Conduct

Be respectful, constructive, and collaborative. We're all here to build useful tools.

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
