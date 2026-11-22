from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
PID_FILE = DATA / "local-runtime.json"
LOG_FILE = DATA / "logs" / "web.log"


def read_env() -> dict[str, str]:
    values = {"HKUS_HOST": "127.0.0.1", "HKUS_PORT": "8740", "HKUS_DATA_MODE": "DEMO", "HKUS_DATABASE": "./data/market.sqlite3"}
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key in values:
                values[key] = value
    return values


def identity(pid: int) -> dict | None:
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "uid=", "-o", "lstart=", "-o", "command="],
            capture_output=True, text=True, timeout=2, check=True,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return None
    output = result.stdout.strip()
    if not output:
        return None
    pieces = output.split(None, 6)
    if len(pieces) < 7:
        return None
    return {"uid": pieces[0], "started": " ".join(pieces[1:6]), "command": pieces[6]}


def managed_identity(pid: int, expected: dict | None = None) -> dict | None:
    current = identity(pid)
    if not current or current["uid"] != str(os.getuid()):
        return None
    command = current["command"]
    if str(ROOT / "backend") not in command or "app.main:app" not in command:
        return None
    if expected and (current["started"] != expected.get("started") or str(ROOT) != expected.get("root")):
        return None
    return current


def health(host: str, port: int) -> dict | None:
    try:
        with urlopen(f"http://{host}:{port}/api/health", timeout=1.2) as response:
            body = json.loads(response.read().decode("utf-8"))
            if response.status == 200 and body.get("app") == "hk-us-stock-workbench":
                return body
    except (URLError, TimeoutError, OSError, json.JSONDecodeError):
        return None
    return None


def port_is_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=.3):
            return True
    except OSError:
        return False


def load_record() -> dict | None:
    try:
        return json.loads(PID_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def start() -> int:
    env_config = read_env()
    host = env_config["HKUS_HOST"]
    if host != "127.0.0.1":
        print("安全设置要求 HKUS_HOST 固定为 127.0.0.1；未启动。")
        return 2
    if env_config["HKUS_DATA_MODE"].upper() != "DEMO":
        print("目前只实现 DEMO 合成数据；未启动真实行情模式。")
        return 2
    try:
        port = int(env_config["HKUS_PORT"])
    except ValueError:
        print("HKUS_PORT 必须为数字。")
        return 2
    if not 1024 <= port <= 65535:
        print("HKUS_PORT 范围须在 1024–65535。")
        return 2

    record = load_record()
    if record and record.get("root") == str(ROOT):
        existing = managed_identity(int(record.get("pid", -1)), record)
        if existing:
            if health(host, port):
                print(f"工作台已运行：http://{host}:{port}")
                return 0
            print("已找到本工作台进程，但健康检查未通过；请查看 data/logs/web.log。")
            return 1

    if port_is_open(host, port):
        running = health(host, port)
        if running:
            print(f"本工作台已在运行：http://{host}:{port}；该进程未由此启动器管理。")
            return 0
        print(f"端口 {port} 已被其他程序占用；未启动，也未结束其他程序。请修改 .env 的 HKUS_PORT。")
        return 1

    python = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.exists():
        print("运行环境尚未安装。请先运行 设置环境.command。")
        return 2
    DATA.mkdir(parents=True, exist_ok=True)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update(env_config)
    env["HKUS_DATABASE"] = str((ROOT / env_config["HKUS_DATABASE"]).resolve()) if not Path(env_config["HKUS_DATABASE"]).is_absolute() else env_config["HKUS_DATABASE"]
    command = [sys.executable if os.name == "nt" else str(python), "-m", "uvicorn", "app.main:app", "--app-dir", str(ROOT / "backend"), "--host", host, "--port", str(port), "--no-access-log"]
    with LOG_FILE.open("ab") as log:
        process = subprocess.Popen(command, cwd=ROOT, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=(os.name != "nt"))
    time.sleep(.5)
    current = managed_identity(process.pid)
    if not current:
        process.terminate()
        print("启动进程身份核验失败，进程已退出。")
        return 1
    PID_FILE.write_text(json.dumps({"pid": process.pid, "started": current["started"], "root": str(ROOT), "host": host, "port": port}, indent=2), encoding="utf-8")
    for _ in range(40):
        if health(host, port):
            print(f"港美股工作台已启动：http://{host}:{port}")
            return 0
        if process.poll() is not None:
            break
        time.sleep(.25)
    details = LOG_FILE.read_text(encoding="utf-8", errors="replace")[-2500:] if LOG_FILE.exists() else ""
    print("工作台未通过健康检查。最新日志：")
    print(details or "暂无日志")
    return 1


def stop() -> int:
    record = load_record()
    if not record or record.get("root") != str(ROOT):
        print("没有本启动器登记的工作台进程。")
        return 0
    pid = int(record.get("pid", -1))
    current = managed_identity(pid, record)
    if not current:
        print("登记进程已经退出或身份不匹配；没有结束任何进程。")
        try:
            PID_FILE.unlink()
        except FileNotFoundError:
            pass
        return 0
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        PID_FILE.unlink(missing_ok=True)
        print("工作台进程已退出。")
        return 0
    for _ in range(40):
        if not managed_identity(pid, record):
            PID_FILE.unlink(missing_ok=True)
            print("港美股工作台已停止。")
            return 0
        time.sleep(.1)
    print("工作台没有在4秒内停止；未发送强制结束信号。")
    return 1


def status() -> int:
    env_config = read_env()
    host, port = env_config["HKUS_HOST"], int(env_config["HKUS_PORT"])
    record = load_record()
    current = managed_identity(int(record.get("pid", -1)), record) if record and record.get("root") == str(ROOT) else None
    running = health(host, port)
    print(json.dumps({"running": bool(running), "managed_by_launcher": bool(current), "url": f"http://{host}:{port}", "health": running}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in {"start", "stop", "status"}:
        print("用法：python ops/local_runtime.py start|stop|status")
        raise SystemExit(2)
    raise SystemExit({"start": start, "stop": stop, "status": status}[sys.argv[1]]())
