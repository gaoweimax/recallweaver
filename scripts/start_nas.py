"""Launch RecallWeaver's HTTP service for access from a local network."""

import os
import socket
import subprocess
import sys
from pathlib import Path

from rich.console import Console

PROJECT_ROOT = Path(__file__).resolve().parents[1]
HOST = "0.0.0.0"
PORT = 8000
console = Console()


def _local_ip_address() -> str:
    """Return the IPv4 address selected for outbound LAN traffic, if available."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        try:
            # UDP connect only selects a local route; it does not send an application
            # request to the address.
            probe.connect(("192.0.2.1", 80))
            address = probe.getsockname()[0]
            if address and not address.startswith("127."):
                return address
        except OSError:
            pass

    for result in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
        address = result[4][0]
        if not address.startswith("127."):
            return address
    return "127.0.0.1"


def main() -> int:
    """Check configuration, print LAN URLs, and run the Uvicorn service."""
    if os.environ.get("DEEPSEEK_API_KEY", "").strip():
        print("已检测到 DEEPSEEK_API_KEY。")
    else:
        console.print(
            "[bold red]警告：未设置 DEEPSEEK_API_KEY；"
            "请配置密钥后重新启动服务。[/bold red]"
        )
        sys.exit(1)

    local_ip = _local_ip_address()
    print(f"RecallWeaver API: http://{local_ip}:{PORT}")
    print(f"Web/API 文档: http://{local_ip}:{PORT}/docs")
    print("请确认 NAS 防火墙允许访问该端口。")

    child_env = os.environ.copy()
    source_path = str(PROJECT_ROOT / "src")
    existing_python_path = child_env.get("PYTHONPATH")
    child_env["PYTHONPATH"] = os.pathsep.join(
        path for path in (source_path, existing_python_path) if path
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "recallweaver.server:app",
            "--host",
            HOST,
            "--port",
            str(PORT),
        ],
        cwd=PROJECT_ROOT,
        env=child_env,
        check=False,
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
