"""Drain child diagnostics concurrently and reap the owned process tree."""
import asyncio
import os
import signal
import subprocess


async def drain_stderr(stream):
    # Keep draining even after the bounded diagnostic tail fills the pipe.
    tail = b''
    if stream is not None:
        while chunk := await stream.read(8192):
            tail = (tail + chunk)[-8192:]
    return tail.decode('utf-8', errors='replace').strip()


def kill_tree(process):
    if os.name == 'posix':
        # Adapters start a fresh session, so this group contains only this CLI
        # and its tools. A descendant holding either pipe must be killed too.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    elif process.returncode is None:
        executable = os.path.join(os.environ.get('SystemRoot', r'C:\Windows'), 'System32', 'taskkill.exe')
        try:
            subprocess.run([executable, '/T', '/F', '/PID', str(process.pid)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=5, check=False, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except (OSError, subprocess.TimeoutExpired):
            pass
    if process.returncode is None:
        try:
            process.kill()
        except ProcessLookupError:
            pass


async def terminate(process):
    if os.name == 'nt':
        # taskkill must not block the WebSocket event loop.
        await asyncio.to_thread(kill_tree, process)
    else:
        kill_tree(process)


async def reap(process, stderr_task, termination_task=None, *, stop_tree=False):
    if termination_task is not None:
        await termination_task
    elif process.returncode is None or stop_tree:
        await terminate(process)
    await process.wait()
    await stderr_task
