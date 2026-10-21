"""Native process-tree cleanup, with only local Python fixture processes."""
import asyncio
import os
import signal
import subprocess
import sys
import unittest
from app.services.agents.process_io import drain_stderr, reap


class AgentProcessTests(unittest.IsolatedAsyncioTestCase):
    async def test_reap_kills_descendant_holding_stdout_and_stderr(self):
        code = ('import subprocess,sys,time; '
                'child=subprocess.Popen([sys.executable,"-c","import time;time.sleep(60)"]); '
                'print(child.pid,flush=True); time.sleep(60)')
        process = await asyncio.create_subprocess_exec(
            sys.executable, '-c', code, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, start_new_session=(os.name == 'posix'))
        stderr_task = asyncio.create_task(drain_stderr(process.stderr))
        child_pid = None
        try:
            child_pid = int(await asyncio.wait_for(process.stdout.readline(), 5))
            await asyncio.wait_for(reap(process, stderr_task), 10)
            self.assertIsNotNone(process.returncode)
            self.assertEqual(await process.stdout.read(), b'')
            self.assertTrue(stderr_task.done())
        finally:
            if child_pid is not None:
                if os.name == 'nt':
                    executable = os.path.join(os.environ.get('SystemRoot', r'C:\Windows'), 'System32', 'taskkill.exe')
                    await asyncio.to_thread(subprocess.run, [executable, '/T', '/F', '/PID', str(child_pid)],
                                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
                else:
                    try: os.kill(child_pid, signal.SIGKILL)
                    except ProcessLookupError: pass
            if process.returncode is None:
                process.kill()
            await process.wait()
            await stderr_task
