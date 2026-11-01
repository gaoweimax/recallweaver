"""Run RecallWeaver's CLI with Unicode-safe output when called through Node."""

import recallweaver.cli as cli_module
from rich.console import Console


def main() -> None:
    cli_module.console = Console(legacy_windows=False)
    cli_module.cli()


if __name__ == "__main__":
    main()
