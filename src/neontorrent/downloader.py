"""NEON's HTTP download manager (the IDM part): many connections per file, pause and resume, resume after a restart,
a queue, a speed limit and a start time.

A file the server can serve in ranges (Accept-Ranges / 206) is split into up to ``connections`` segments, each fetched
on its own connection into one pre-allocated ``.neonpart`` file; a segment that finishes early takes half of the
largest one left, so all connections stay busy to the end. A server without ranges gets one connection and starts
over if it is interrupted. Progress is saved to ``<data>\\downloads\\<id>.json`` every few seconds, so a crash or a
restart loses little. A finished file gets its real name (never overwriting: "name (1).ext"), Mark-of-the-Web, and
a Download Guard check of its name.

Thread-safe; the UI polls ``snapshot()``.
"""
from __future__ import annotations

import json
import os
import secrets
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from . import web

PART_SUFFIX = ".neonpart"
BLOCK = 256 * 1024
MIN_SPLIT = 2 * 1024 * 1024              # never split a segment below this
SAVE_EVERY = 3.0
RETRIES = 5
DEFAULT_CONNECTIONS = 8
MAX_CONNECTIONS = 32


@dataclass
class Segment:
    start: int
    end: int                              # inclusive; -1 while the size is unknown
    done: int = 0

    @property
    def left(self) -> int:
        return -1 if self.end < 0 else self.end - self.start + 1 - self.done


@dataclass
class Job:
    id: str
    url: str
    folder: str
    name: str
    size: int = -1
    ranges: bool = False
    connections: int = DEFAULT_CONNECTIONS
    state: str = "queued"                  # queued / running / paused / done / failed / cancelled
    error: str = ""
    added: float = field(default_factory=time.time)
    finished: float = 0.0
    path: str = ""                         # the saved file once done
    segments: list[Segment] = field(default_factory=list)
    warning: str = ""                      # e.g. "program" when Download Guard flags the name

    @property
    def done(self) -> int:
        return sum(s.done for s in self.segments)

    def to_json(self) -> dict:
        data = asdict(self)
        data["segments"] = [asdict(s) for s in self.segments]
        return data

    @classmethod
    def from_json(cls, data: dict) -> Job:
        segments = [Segment(**s) for s in data.pop("segments", [])]
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        job = cls(**known)
        job.segments = segments
        return job


class _Bucket:
    """Global speed limit (bytes per second, 0 = unlimited) shared by every connection."""

    def __init__(self):
        self.rate = 0
        self.tokens = 0.0
        self.stamp = time.monotonic()
        self.lock = threading.Lock()

    def take(self, n: int) -> None:
        while self.rate > 0:
            with self.lock:
                now = time.monotonic()
                self.tokens = min(self.rate, self.tokens + (now - self.stamp) * self.rate)
                self.stamp = now
                if self.tokens >= n or self.tokens >= self.rate:
                    self.tokens -= n
                    return
                wait = (n - self.tokens) / self.rate
            time.sleep(min(wait, 0.25))


class DownloadManager:
    def __init__(self, data_dir: Path, notify: Callable[[str, str], None] = lambda text, level: None):
        self.dir = Path(data_dir) / "downloads"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.notify = notify
        self.lock = threading.RLock()
        self.jobs: dict[str, Job] = {}
        self.workers: dict[str, list[threading.Thread]] = {}
        self.stop_flags: dict[str, threading.Event] = {}
        self.speeds: dict[str, list[tuple[float, int]]] = {}
        self.bucket = _Bucket()
        self.max_active = 3
        self.start_at = 0.0                    # epoch seconds: queued jobs wait until then (0 = now)
        self._closing = False
        self._load()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="neon-downloads")
        self._thread.start()

    # ---------------------------------------------------------- persistence
    def _load(self) -> None:
        for path in sorted(self.dir.glob("*.json")):
            try:
                job = Job.from_json(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError, TypeError):
                continue
            if job.state == "running":
                job.state = "queued"                           # interrupted by a quit or a crash: carry on
            self.jobs[job.id] = job

    def _save(self, job: Job) -> None:
        path = self.dir / f"{job.id}.json"
        tmp = path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(job.to_json()), encoding="utf-8")
            tmp.replace(path)
        except OSError:
            pass

    def _part(self, job: Job) -> Path:
        return Path(job.folder) / f".{job.id}{PART_SUFFIX}"

    # ---------------------------------------------------------- public API (any thread)
    def add(self, url: str, folder: str, name: str = "", size: int = -1, ranges: bool = False,
            connections: int = DEFAULT_CONNECTIONS, start: bool = True) -> Job:
        from .share import safe_name
        web.check_url(url)
        job = Job(secrets.token_hex(6), url, str(folder), safe_name(name) if name else "download",
                  size, ranges, max(1, min(MAX_CONNECTIONS, connections)), "queued" if start else "paused")
        with self.lock:
            self.jobs[job.id] = job
            self._save(job)
        return job

    def pause(self, ids: list[str]) -> None:
        with self.lock:
            for job_id in ids:
                job = self.jobs.get(job_id)
                if job and job.state in ("queued", "running"):
                    self._stop(job_id)
                    job.state = "paused"
        self._join(ids)
        with self.lock:
            for job_id in ids:
                if job_id in self.jobs:
                    self._save(self.jobs[job_id])              # after the connections stopped: exact progress

    def resume(self, ids: list[str]) -> None:
        with self.lock:
            for job_id in ids:
                job = self.jobs.get(job_id)
                if job and job.state in ("paused", "failed"):
                    job.state, job.error = "queued", ""
                    self._save(job)

    def remove(self, ids: list[str], delete_file: bool = False) -> None:
        with self.lock:
            for job_id in ids:
                job = self.jobs.pop(job_id, None)
                if job is None:
                    continue
                self._stop(job_id)
                threads = self.workers.pop(job_id, [])
                for t in threads:
                    t.join(timeout=5)
                self._part(job).unlink(missing_ok=True)
                if delete_file and job.path:
                    Path(job.path).unlink(missing_ok=True)
                (self.dir / f"{job_id}.json").unlink(missing_ok=True)

    def set_limit(self, bytes_per_second: int) -> None:
        self.bucket.rate = max(0, int(bytes_per_second))

    def snapshot(self) -> list[dict]:
        now = time.monotonic()
        with self.lock:
            rows = []
            for job in sorted(self.jobs.values(), key=lambda j: j.added):
                samples = [s for s in self.speeds.get(job.id, []) if now - s[0] <= 4]
                speed = (samples[-1][1] - samples[0][1]) / (samples[-1][0] - samples[0][0]) \
                    if len(samples) > 1 and samples[-1][0] > samples[0][0] else 0.0
                rows.append({"id": job.id, "name": job.name, "url": job.url, "size": job.size, "done": job.done,
                             "state": job.state, "error": job.error, "speed": speed, "path": job.path,
                             "connections": sum(1 for t in self.workers.get(job.id, []) if t.is_alive()),
                             "ranges": job.ranges, "warning": job.warning, "folder": job.folder})
            return rows

    def close(self) -> None:
        self._closing = True
        with self.lock:
            running = list(self.stop_flags)
            for job_id in running:
                self._stop(job_id)
        self._join(running)
        with self.lock:
            for job in self.jobs.values():
                self._save(job)

    def _join(self, ids: list[str], timeout: float = 10.0) -> None:
        """Wait (outside the lock) until the connections of these jobs have closed their files."""
        deadline = time.monotonic() + timeout
        with self.lock:
            threads = [t for job_id in ids for t in self.workers.get(job_id, [])]
        for thread in threads:
            if thread is not threading.current_thread():
                thread.join(max(0.0, deadline - time.monotonic()))

    # ---------------------------------------------------------- scheduling
    def _stop(self, job_id: str) -> None:
        flag = self.stop_flags.pop(job_id, None)
        if flag is not None:
            flag.set()

    def _loop(self) -> None:
        last_save = time.monotonic()
        while not self._closing:
            with self.lock:
                running = [j for j in self.jobs.values() if j.state == "running"]
                if time.time() >= self.start_at:
                    for job in sorted(self.jobs.values(), key=lambda j: j.added):
                        if len(running) >= self.max_active:
                            break
                        if job.state == "queued":
                            self._start(job)
                            running.append(job)
                now = time.monotonic()
                for job in running:
                    self.speeds.setdefault(job.id, []).append((now, job.done))
                    self.speeds[job.id] = self.speeds[job.id][-20:]
                if now - last_save >= SAVE_EVERY:
                    for job in running:
                        self._save(job)
                    last_save = now
            time.sleep(0.5)

    def _start(self, job: Job) -> None:
        job.state, job.error = "running", ""
        flag = threading.Event()
        self.stop_flags[job.id] = flag
        thread = threading.Thread(target=self._run, args=(job, flag), daemon=True, name=f"neon-dl-{job.id}")
        self.workers[job.id] = [thread]
        thread.start()

    # ---------------------------------------------------------- one job
    def _run(self, job: Job, stop: threading.Event) -> None:
        try:
            if not job.segments:
                info = web.probe(job.url)
                if info.kind == "page":
                    raise web.WebError("this link is a web page, not a file")
                job.url, job.ranges = info.url, info.ranges and info.size > 0
                job.size = info.size
                if not job.name or job.name == "download":
                    from .share import safe_name
                    job.name = safe_name(info.name)
                self._plan(job)
            part = self._part(job)
            Path(job.folder).mkdir(parents=True, exist_ok=True)
            if not part.exists():
                with open(part, "wb") as handle:
                    if job.size > 0:
                        handle.truncate(job.size)              # pre-allocate: every segment writes in place
                for seg in job.segments:
                    seg.done = 0
            if job.ranges:
                self._run_ranges(job, part, stop)
            else:
                self._run_single(job, part, stop)
            if stop.is_set():
                return
            if any(s.left > 0 for s in job.segments):
                raise web.WebError("the server stopped sending the file")
            self._finish(job, part)
        except web.WebError as exc:
            with self.lock:
                if not stop.is_set():
                    job.state, job.error = "failed", str(exc)
                    self.notify(f"DOWNLOAD FAILED · {job.name} · {exc}", "error")
        except OSError as exc:
            with self.lock:
                job.state, job.error = "failed", exc.strerror or str(exc)
                self.notify(f"DOWNLOAD FAILED · {job.name} · {job.error}", "error")
        finally:
            with self.lock:
                self.stop_flags.pop(job.id, None)
                self._save(job)

    def _plan(self, job: Job) -> None:
        if not job.ranges or job.size <= 0:
            job.ranges = False
            job.segments = [Segment(0, job.size - 1 if job.size > 0 else -1)]
            return
        count = max(1, min(job.connections, job.size // MIN_SPLIT or 1))
        step = job.size // count
        job.segments = [Segment(i * step, (i + 1) * step - 1 if i < count - 1 else job.size - 1)
                        for i in range(count)]

    def _run_ranges(self, job: Job, part: Path, stop: threading.Event) -> None:
        pending = [s for s in job.segments if s.left > 0]
        threads = [threading.Thread(target=self._segment, args=(job, part, s, stop), daemon=True) for s in pending]
        with self.lock:
            self.workers[job.id] = threads + self.workers.get(job.id, [])[:1]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    def _steal(self, job: Job) -> Segment | None:
        """A finished connection takes the second half of the largest segment still running."""
        with self.lock:
            biggest = max(job.segments, key=lambda s: s.left, default=None)
            if biggest is None or biggest.left < 2 * MIN_SPLIT:
                return None
            middle = biggest.start + biggest.done + biggest.left // 2
            new = Segment(middle, biggest.end)
            biggest.end = middle - 1
            job.segments.append(new)
            return new

    def _segment(self, job: Job, part: Path, seg: Segment, stop: threading.Event) -> None:
        tries = 0
        while not stop.is_set() and seg is not None:
            if seg.left <= 0:
                seg = self._steal(job)
                continue
            try:
                start = seg.start + seg.done
                response = web.open_url(job.url, headers={"Range": f"bytes={start}-{seg.end}"})
                with response, open(part, "r+b") as handle:
                    if response.status != 206:
                        raise web.WebError("the server stopped serving parts of the file")
                    handle.seek(start)
                    while not stop.is_set():
                        want = min(BLOCK, seg.left)
                        if want <= 0:
                            break
                        self.bucket.take(want)
                        data = response.read(want)
                        if not data:
                            break
                        handle.write(data)
                        with self.lock:
                            seg.done += len(data)
                tries = 0
            except (web.WebError, OSError):
                tries += 1
                if tries > RETRIES:
                    return
                time.sleep(min(30, 2 ** tries))

    def _run_single(self, job: Job, part: Path, stop: threading.Event) -> None:
        seg = job.segments[0]
        for attempt in range(RETRIES + 1):
            seg.done = 0                                      # no ranges: an interrupted file starts over
            try:
                with web.open_url(job.url) as response, open(part, "wb") as handle:
                    while not stop.is_set():
                        self.bucket.take(BLOCK)
                        data = response.read(BLOCK)
                        if not data:
                            break
                        handle.write(data)
                        with self.lock:
                            seg.done += len(data)
                if stop.is_set():
                    return
                if job.size < 0:
                    job.size = seg.done
                    seg.end = seg.done - 1
                return
            except (web.WebError, OSError):
                if attempt == RETRIES:
                    raise
                time.sleep(min(30, 2 ** (attempt + 1)))

    def _finish(self, job: Job, part: Path) -> None:
        from . import guard
        from .share import commit_file
        # an antivirus scanning the just-written file can hold it for a moment: retry the rename for up to ~15 s
        for attempt in range(30):
            try:
                saved = commit_file(part, Path(job.folder), job.name)
                break
            except PermissionError:
                if attempt == 29:
                    raise
                time.sleep(0.5)
        guard.mark_of_the_web(saved)
        kind = web.link_kind(saved.name)
        with self.lock:
            job.path, job.state, job.finished = str(saved), "done", time.time()
            job.warning = "program" if kind == "program" else ""
        self.notify(f"DOWNLOADED · {saved.name}" + (" · it is a program: run it only if you trust the site"
                                                     if job.warning else ""), "warn" if job.warning else "ok")
