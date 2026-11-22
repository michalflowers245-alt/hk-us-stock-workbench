from __future__ import annotations

import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
LABEL = "com.michalflowers245.hk-us-stock-workbench"
WAKE_LABEL = f"{LABEL}.keepawake"
AGENT_DIR = Path.home() / "Library" / "LaunchAgents"
AGENT_FILE = AGENT_DIR / f"{LABEL}.plist"
WAKE_FILE = AGENT_DIR / f"{WAKE_LABEL}.plist"
LOG_FILE = ROOT / "data" / "logs" / "web.log"


def config() -> dict[str, str]:
    sys.path.insert(0, str(ROOT / "ops"))
    from local_runtime import read_env

    values = read_env()
    if values["HKUS_HOST"] != "127.0.0.1":
        raise ValueError("安全设置要求 HKUS_HOST 固定为 127.0.0.1。")
    if values["HKUS_DATA_MODE"].upper() != "DEMO":
        raise ValueError("研究/回放数据必须保持 DEMO 模式。")
    values["HKUS_PORT"] = str(int(values["HKUS_PORT"]))
    values["HKUS_DATABASE"] = str(
        (ROOT / values["HKUS_DATABASE"]).resolve()
        if not Path(values["HKUS_DATABASE"]).is_absolute()
        else Path(values["HKUS_DATABASE"]).resolve()
    )
    return values


def launchctl(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["/bin/launchctl", *args], capture_output=True, text=True, timeout=15)


def domain() -> str:
    return f"gui/{os.getuid()}"


def is_loaded(label: str) -> bool:
    return launchctl("print", f"{domain()}/{label}").returncode == 0


def bootout(path: Path) -> None:
    launchctl("bootout", domain(), str(path))


def health(values: dict[str, str]) -> bool:
    try:
        with urlopen(f"http://127.0.0.1:{values['HKUS_PORT']}/api/health", timeout=1.5) as response:
            body = json.loads(response.read().decode("utf-8"))
            return response.status == 200 and body.get("app") == "hk-us-stock-workbench"
    except (URLError, TimeoutError, OSError, json.JSONDecodeError):
        return False


def service_plist(values: dict[str, str]) -> dict:
    python = ROOT / ".venv" / "bin" / "python"
    if not python.exists():
        raise FileNotFoundError("没有找到 .venv/bin/python；请先运行「设置环境.command」。")
    return {
        "Label": LABEL,
        "ProgramArguments": [
            str(python), str(ROOT / "ops" / "local_runtime.py"), "start",
        ],
        "WorkingDirectory": str(ROOT),
        "RunAtLoad": True,
        "StartInterval": 60,
        "ThrottleInterval": 10,
        "StandardOutPath": "/dev/null",
        "StandardErrorPath": "/dev/null",
    }


def install() -> int:
    if sys.platform != "darwin":
        print("此登录自启仅支持 macOS。")
        return 2
    try:
        values = config()
        AGENT_DIR.mkdir(parents=True, exist_ok=True)
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        # Stop only the app instance owned by this project's existing local launcher.
        subprocess.run([str(ROOT / ".venv" / "bin" / "python"), str(ROOT / "ops" / "local_runtime.py"), "stop"], check=False)
        bootout(AGENT_FILE)
        bootout(WAKE_FILE)

        with AGENT_FILE.open("wb") as stream:
            plistlib.dump(service_plist(values), stream, sort_keys=True)
        wake_plist = {
            "Label": WAKE_LABEL,
            "ProgramArguments": ["/usr/bin/caffeinate", "-s"],
            "RunAtLoad": True,
            "KeepAlive": True,
            "ThrottleInterval": 10,
            "StandardOutPath": "/dev/null",
            "StandardErrorPath": "/dev/null",
        }
        with WAKE_FILE.open("wb") as stream:
            plistlib.dump(wake_plist, stream, sort_keys=True)

        for path in (AGENT_FILE, WAKE_FILE):
            result = launchctl("bootstrap", domain(), str(path))
            if result.returncode != 0:
                detail = (result.stderr or result.stdout).strip()
                raise RuntimeError(f"launchd 加载失败：{detail or path.name}")
        for _ in range(40):
            if health(values) and is_loaded(LABEL) and is_loaded(WAKE_LABEL):
                print(f"已安装登录自启并启动工作台：http://127.0.0.1:{values['HKUS_PORT']}")
                print("launchd 每分钟检查并在服务退出后重新拉起；接电时 caffeinate 会阻止闲置睡眠。")
                print("删除 LaunchAgent 可用：python ops/macos_autostart.py stop")
                return 0
            time.sleep(.5)
        raise RuntimeError("launchd 已加载，但工作台未通过本机健康检查；请查看 data/logs/web.log。")
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(str(exc))
        return 1


def stop() -> int:
    if sys.platform != "darwin":
        print("此登录自启仅支持 macOS。")
        return 2
    bootout(AGENT_FILE)
    bootout(WAKE_FILE)
    AGENT_FILE.unlink(missing_ok=True)
    WAKE_FILE.unlink(missing_ok=True)
    python = ROOT / ".venv" / "bin" / "python"
    if python.exists():
        subprocess.run([str(python), str(ROOT / "ops" / "local_runtime.py"), "stop"], check=False)
    print("已停止并移除本项目的登录自启与防闲置睡眠任务。")
    print("工作台数据、OAuth 授权和行情历史均保留。")
    return 0


def status() -> int:
    if sys.platform != "darwin":
        print("此登录自启仅支持 macOS。")
        return 2
    try:
        values = config()
    except (ValueError, OSError) as exc:
        print(str(exc))
        return 1
    running = health(values)
    service_loaded = is_loaded(LABEL)
    wake_loaded = is_loaded(WAKE_LABEL)
    print(json.dumps({
        "service_loaded": service_loaded,
        "keep_awake_loaded": wake_loaded,
        "running": running,
        "url": f"http://127.0.0.1:{values['HKUS_PORT']}",
    }, ensure_ascii=False, indent=2))
    return 0 if running else 1


if __name__ == "__main__":
    commands = {"install": install, "stop": stop, "status": status}
    if len(sys.argv) != 2 or sys.argv[1] not in commands:
        print("用法：python ops/macos_autostart.py install|stop|status")
        raise SystemExit(2)
    raise SystemExit(commands[sys.argv[1]]())
