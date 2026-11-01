from pathlib import Path
import shutil
import sys


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    project_root = Path(__file__).resolve().parent.parent
    source = (project_root / "dsh-plugin-recallweaver").resolve()
    plugins_directory = Path.home() / ".dsh" / "plugins"
    destination = plugins_directory / source.name

    if not source.is_dir():
        raise FileNotFoundError(f"Plugin source directory not found: {source}")

    plugins_directory.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination, dirs_exist_ok=True)
    print("✅ 插件已成功复制到 DSH 目录！请立刻彻底退出 DSH 托盘程序，重新打开即可生效。")


if __name__ == "__main__":
    try:
        main()
    except OSError as error:
        print(f"Plugin installation failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
