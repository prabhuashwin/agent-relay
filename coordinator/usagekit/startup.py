"""Current-user Windows login startup, with explicit install/remove/status controls."""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from . import collectors, config
from .errors import CtlError


def launch_config(paths, root, port, codex_account, claude_account):
    if not 1 <= port <= 65535:
        raise CtlError('startup port must be between 1 and 65535')
    cfg = config.load(paths)
    command = [sys.executable, str(Path(__file__).resolve().parent.parent / 'usagectl.py'),
               'board', 'serve', '--port', str(port)]
    for alias, provider, flag in [(codex_account, 'codex', '--codex-account'),
                                 (claude_account, 'claude', '--experimental-claude-account')]:
        if alias:
            collectors.require_provider(cfg, alias, provider)
            command.extend([flag, alias])
    env = {'CLAUDE_SETUP_HOME': paths.home}
    for key in ('CLAUDE_CONFIG_DIR', 'CODEX_HOME'):
        if os.environ.get(key):
            env[key] = str(Path(os.environ[key]).resolve())
    return dict(enabled=True, command=command, cwd=str(Path(root).resolve()), env=env, port=port)


def locations(paths):
    if os.name != 'nt' or not os.environ.get('APPDATA'):
        raise CtlError('Automatic login startup is currently supported on Windows only')
    # One clearly named shortcut per state home, so separate installations do not collide.
    import hashlib
    suffix = hashlib.sha256(paths.home.casefold().encode()).hexdigest()[:8]
    shortcut = Path(os.environ['APPDATA']) / 'Microsoft/Windows/Start Menu/Programs/Startup' / ('Agent Relay-' + suffix + '.lnk')
    return Path(paths.state) / 'relay-startup.json', shortcut


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data, indent=2), encoding='utf-8')
    temp.replace(path)


def startup_status(paths):
    path, shortcut = locations(paths)
    result = {'enabled': False, 'shortcut': str(shortcut)}
    if path.exists():
        cfg = json.loads(path.read_text(encoding='utf-8'))
        result.update(enabled=cfg.get('enabled', False) and shortcut.exists(), port=cfg['port'])
    status_path = path.with_suffix('.status.json')
    if status_path.exists():
        result['last_supervisor_report'] = json.loads(status_path.read_text(encoding='utf-8'))
    return result


def disable(paths):
    path, shortcut = locations(paths)
    if path.exists():
        cfg = json.loads(path.read_text(encoding='utf-8'))
        cfg['enabled'] = False
        save(path, cfg)
    shortcut.unlink(missing_ok=True)
    lock_path = path.with_suffix('.lock')
    if lock_path.exists():
        import msvcrt
        deadline = time.monotonic() + 15
        with lock_path.open('r+b') as lock:
            while True:
                try:
                    lock.seek(0)
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                    msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise CtlError('Startup disabled, but the supervisor has not stopped yet. Check startup status before enabling again.') from None
                    time.sleep(0.1)
    return startup_status(paths)


def enable(paths, root, port, codex_account, claude_account):
    path, shortcut = locations(paths)
    if shortcut.exists():
        raise CtlError('Startup is already installed. Disable it before changing its configuration.')
    lock_path = path.with_suffix('.lock')
    if lock_path.exists():
        import msvcrt
        with lock_path.open('r+b') as lock:
            try:
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                raise CtlError('Previous Relay supervisor is still stopping. Wait a few seconds before enabling startup.') from None
    cfg = launch_config(paths, root, port, codex_account, claude_account)
    pythonw = Path(sys.executable).with_name('pythonw.exe')
    if not pythonw.exists():
        raise CtlError('pythonw.exe is required for hidden Windows startup')
    supervisor = Path(__file__).with_name('relay_supervisor.py').resolve()
    arguments = subprocess.list2cmdline([str(supervisor), str(path)])
    def quote(value):
        return "'" + str(value).replace("'", "''") + "'"
    script = ("$ErrorActionPreference='Stop'; $relayShell=New-Object -ComObject WScript.Shell; "
              '$relayLink=$relayShell.CreateShortcut(' + quote(shortcut) + '); '
              '$relayLink.TargetPath=' + quote(pythonw) + '; '
              '$relayLink.Arguments=' + quote(arguments) + '; '
              '$relayLink.WorkingDirectory=' + quote(root) + '; $relayLink.WindowStyle=7; $relayLink.Save()')
    shortcut.parent.mkdir(parents=True, exist_ok=True)
    save(path, cfg)
    try:
        subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-EncodedCommand',
            base64.b64encode(script.encode('utf-16le')).decode()], check=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20,
            creationflags=subprocess.CREATE_NO_WINDOW)
        subprocess.Popen([str(pythonw), str(supervisor), str(path)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        disable(paths)
        raise CtlError('Could not enable Windows startup; installation was disabled.') from None
    return startup_status(paths)
