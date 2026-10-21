"""Drain child diagnostics concurrently and always reap the owned process."""
import asyncio


async def drain_stderr(stream):
    # Keep draining even after the bounded diagnostic tail fills the pipe.
    tail = b''
    if stream is not None:
        while chunk := await stream.read(8192):
            tail = (tail + chunk)[-8192:]
    return tail.decode('utf-8', errors='replace').strip()


async def reap(process, stderr_task):
    if process.returncode is None:
        try:
            process.kill()
        except ProcessLookupError:
            pass
    await process.wait()
    await stderr_task
