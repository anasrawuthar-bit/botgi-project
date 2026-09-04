import logging
import os
import shutil
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

BRIDGE_DIR = Path(settings.BASE_DIR) / 'whatsapp_bridge'
PID_FILE = Path(settings.BASE_DIR) / '.tmp_whatsapp_bridge_pid'
LOG_FILE = Path(settings.BASE_DIR) / '.tmp_whatsapp_bridge.log'
ERR_LOG_FILE = Path(settings.BASE_DIR) / '.tmp_whatsapp_bridge.err.log'
DEFAULT_BRIDGE_URL = 'http://127.0.0.1:3001'
LOCAL_HOSTS = {'127.0.0.1', 'localhost', '::1'}


def _read_pid() -> int | None:
    try:
        raw_pid = PID_FILE.read_text(encoding='utf-8').strip()
        return int(raw_pid) if raw_pid else None
    except (OSError, ValueError):
        return None


def _write_pid(pid: int) -> None:
    PID_FILE.write_text(str(pid), encoding='utf-8')


def _remove_pid() -> None:
    try:
        PID_FILE.unlink()
    except FileNotFoundError:
        pass


def _process_is_running(pid: int | None) -> bool:
    if not pid:
        return False

    if os.name == 'nt':
        completed = subprocess.run(
            ['tasklist', '/FI', f'PID eq {pid}', '/FO', 'CSV', '/NH'],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return str(pid) in (completed.stdout or '')

    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _settings_base_url(settings_obj=None) -> str:
    raw_url = ''
    if settings_obj is not None:
        raw_url = (getattr(settings_obj, 'bridge_base_url', '') or '').strip()
    raw_url = raw_url or os.environ.get('WA_BRIDGE_BASE_URL', '') or DEFAULT_BRIDGE_URL
    if raw_url.startswith('http://') or raw_url.startswith('https://'):
        return raw_url.rstrip('/')
    return f"http://{raw_url}".rstrip('/')


def _is_local_bridge_url(base_url: str) -> bool:
    parsed = urlparse(base_url)
    return (parsed.hostname or '').lower() in LOCAL_HOSTS


def can_manage_bridge(settings_obj=None) -> bool:
    return _is_local_bridge_url(_settings_base_url(settings_obj))


def _bridge_port(settings_obj=None) -> str:
    parsed = urlparse(_settings_base_url(settings_obj))
    if parsed.port:
        return str(parsed.port)
    return '443' if parsed.scheme == 'https' else '80'


def _bridge_is_reachable(settings_obj=None) -> bool:
    try:
        response = requests.get(f"{_settings_base_url(settings_obj)}/api/health", timeout=1.5)
    except requests.RequestException:
        return False
    return response.ok


def bridge_process_snapshot(settings_obj=None) -> dict:
    pid = _read_pid()
    return {
        'manageable': can_manage_bridge(settings_obj),
        'pid': pid,
        'running': _process_is_running(pid),
        'reachable': _bridge_is_reachable(settings_obj),
        'base_url': _settings_base_url(settings_obj),
        'log_file': str(LOG_FILE),
        'error_log_file': str(ERR_LOG_FILE),
    }


def start_bridge(settings_obj=None) -> dict:
    if not can_manage_bridge(settings_obj):
        return {
            'ok': False,
            'started': False,
            'error': 'Bridge URL is not local, so Django will not manage that process.',
            'process': bridge_process_snapshot(settings_obj),
        }

    if _bridge_is_reachable(settings_obj):
        return {
            'ok': True,
            'started': False,
            'message': 'Bridge is already reachable.',
            'process': bridge_process_snapshot(settings_obj),
        }

    pid = _read_pid()
    if _process_is_running(pid):
        return {
            'ok': True,
            'started': False,
            'message': 'Bridge process is already running.',
            'process': bridge_process_snapshot(settings_obj),
        }

    server_js = BRIDGE_DIR / 'server.js'
    node_modules = BRIDGE_DIR / 'node_modules'
    if not server_js.exists():
        return {
            'ok': False,
            'started': False,
            'error': f'Bridge server file not found: {server_js}',
            'process': bridge_process_snapshot(settings_obj),
        }
    if not node_modules.exists():
        return {
            'ok': False,
            'started': False,
            'error': 'Bridge dependencies are missing. Run npm install inside whatsapp_bridge.',
            'process': bridge_process_snapshot(settings_obj),
        }

    node_exe = shutil.which('node')
    if not node_exe:
        return {
            'ok': False,
            'started': False,
            'error': 'Node.js was not found in PATH.',
            'process': bridge_process_snapshot(settings_obj),
        }

    env = os.environ.copy()
    env.setdefault('WA_BRIDGE_PORT', _bridge_port(settings_obj))
    env.setdefault('WA_CLIENT_ID', 'botgi_default')
    env.setdefault('WA_HEADLESS', 'true')

    creationflags = getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0
    with LOG_FILE.open('a', encoding='utf-8') as stdout, ERR_LOG_FILE.open('a', encoding='utf-8') as stderr:
        process = subprocess.Popen(
            [node_exe, 'server.js'],
            cwd=str(BRIDGE_DIR),
            env=env,
            stdout=stdout,
            stderr=stderr,
            creationflags=creationflags,
        )

    _write_pid(process.pid)
    time.sleep(1)
    logger.info('Started WhatsApp bridge process pid=%s', process.pid)
    return {
        'ok': True,
        'started': True,
        'message': 'Bridge process started.',
        'process': bridge_process_snapshot(settings_obj),
    }


def stop_bridge() -> dict:
    pid = _read_pid()
    if not pid:
        return {'ok': True, 'stopped': False, 'message': 'No bridge PID file found.'}

    if _process_is_running(pid):
        if os.name == 'nt':
            subprocess.run(['taskkill', '/PID', str(pid), '/T', '/F'], capture_output=True, text=True, timeout=15)
        else:
            os.kill(pid, 15)
            time.sleep(1)
            if _process_is_running(pid):
                os.kill(pid, 9)

    _remove_pid()
    return {'ok': True, 'stopped': True, 'message': 'Bridge process stopped.'}


def clear_bridge_session(settings_obj=None) -> dict:
    client_id = os.environ.get('WA_CLIENT_ID', 'botgi_default')
    auth_root = Path(os.environ.get('WA_AUTH_ROOT') or BRIDGE_DIR / '.wwebjs_auth')
    session_dir = auth_root / f'session-{client_id}'
    shutil.rmtree(session_dir, ignore_errors=True)
    return {'ok': True, 'cleared': True, 'session_dir': str(session_dir)}


def restart_bridge(settings_obj=None, *, clear_session: bool = False) -> dict:
    stop_result = stop_bridge()
    if clear_session:
        clear_bridge_session(settings_obj)
    start_result = start_bridge(settings_obj)
    return {
        'ok': bool(start_result.get('ok')),
        'stop': stop_result,
        'start': start_result,
        'process': bridge_process_snapshot(settings_obj),
        'error': start_result.get('error', ''),
    }


def ensure_bridge_running(settings_obj=None) -> dict:
    if _bridge_is_reachable(settings_obj):
        return bridge_process_snapshot(settings_obj)
    start_bridge(settings_obj)
    return bridge_process_snapshot(settings_obj)
