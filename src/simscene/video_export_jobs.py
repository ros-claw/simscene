"""Durable, reconnectable exports from recorded SimScene runs."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time

from .preparation.jobs import write
from .request_registry import invoke
from .scene import SceneError, SceneStore, _id

TERMINAL = {'completed', 'failed', 'cancelled', 'uncertain'}


def export_job_id(request_id):
    return 'export-' + hashlib.sha256(_id(request_id).encode()).hexdigest()


def owns(job_id):
    return isinstance(job_id, str) and job_id.startswith('export-')


def directory(job_id):
    if not isinstance(job_id, str) or not re.fullmatch(r'export-[0-9a-f]{64}', job_id):
        raise SceneError('invalid video export job ID')
    return SceneStore().path/'video_exports'/job_id


@contextmanager
def locked(path, mode=fcntl.LOCK_EX):
    with path.open('a') as file:
        fcntl.flock(file, mode)
        yield


def read(path):
    return json.loads(path.read_text())


def start(segments, destination, request_id, output_resolution=None, output=None,
          allow_upscale=False, font_file=None):
    from .jobs import _process_identity

    if not isinstance(segments, list) or not 1 <= len(segments) <= 64:
        raise SceneError('export requires 1..64 source segments')
    if not Path(destination).expanduser().is_absolute():
        raise SceneError('background export requires an absolute destination')
    destination = Path(destination).expanduser().resolve()
    if destination.suffix.lower() != '.mp4':
        raise SceneError('background export destination must be an MP4 path')
    job_id = export_job_id(request_id)
    root = directory(job_id)
    options = {'segments': segments, 'destination': str(destination),
               'output_resolution': output_resolution, 'output': output,
               'allow_upscale': allow_upscale, 'font_file': font_file}
    receipt = {'job_id': job_id, 'type': 'video_export'}

    def recover(identifier, digest):
        try:
            record = read(root/'job.json')
        except (OSError, ValueError):
            return None
        if record.get('request_id') == identifier and record.get('request_payload_sha256') == digest:
            return receipt
        return None

    def launch(identifier, digest):
        root.mkdir(parents=True, exist_ok=False)
        write(root/'request.json', options)
        write(root/'job.json', {**receipt, 'state': 'queued', 'request_id': identifier,
                                'request_payload_sha256': digest})
        package_root = Path(__file__).resolve().parents[1]
        env = dict(os.environ, PYTHONPATH=os.pathsep.join(filter(None, (
            str(package_root), os.environ.get('PYTHONPATH')))))
        with (root/'worker.log').open('ab') as log:
            child = subprocess.Popen(
                [sys.executable, '-m', 'simscene.video_export_jobs', str(root)],
                env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        write(root/'launch.json', {'pid': child.pid, 'identity': _process_identity(child.pid)})
        return receipt

    home = root.parents[1]
    return invoke(home, request_id, {'operation': 'video_export', **options}, launch, recover)


def status(job_id):
    from .jobs import _process_identity

    root = directory(job_id)
    try:
        record = read(root/'job.json')
    except (OSError, ValueError) as error:
        raise SceneError('video export job not found or record unreadable') from error
    if record.get('job_id') != job_id:
        raise SceneError('invalid video export job record')
    # Wait for the reservation and launcher metadata to finish publishing.
    with locked(root.parents[1]/'job-requests'/(_id(record['request_id'])+'.lock'), fcntl.LOCK_SH):
        record = read(root/'job.json')
        if record['state'] not in TERMINAL:
            try:
                launch = read(root/'launch.json')
                alive = launch['identity'] and _process_identity(launch['pid']) == launch['identity']
            except (OSError, ValueError, KeyError):
                alive = False
            if not alive:
                record = read(root/'job.json')
                if record['state'] not in TERMINAL:
                    record.update(state='uncertain', error='Export worker exited without a durable completion record.')
    response = {key: record[key] for key in ('job_id', 'type', 'state', 'result', 'error', 'finished_unix_ns')
                if key in record}
    response.update(record_path=str(root/'job.json'), log=str(root/'worker.log'))
    if (root/'cancel-request.json').is_file():
        response['cancel_requested'] = True
    if record['state'] == 'completed':
        response['completion_confirmed'] = True
    return response


def cancel(job_id):
    from .jobs import _process_identity

    root = directory(job_id)
    status(job_id)
    with locked(root/'finish.lock'):
        record = read(root/'job.json')
        if record['state'] not in TERMINAL:
            write(root/'cancel-request.json', {'requested_unix_ns': time.time_ns()})
            launch_path = root/'launch.json'
            if (record['state'] == 'running' and launch_path.is_file()
                    and hasattr(os, 'pidfd_open') and hasattr(signal, 'pidfd_send_signal')):
                launch = read(launch_path)
                try:
                    descriptor = os.pidfd_open(launch['pid'])
                except ProcessLookupError:
                    pass
                else:
                    try:
                        if launch['identity'] and _process_identity(launch['pid']) == launch['identity']:
                            signal.pidfd_send_signal(descriptor, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    finally:
                        os.close(descriptor)
    return status(job_id)


class Cancelled(Exception):
    pass


def _interrupt(*_):
    raise Cancelled()


def _publish(manifest, staged_movie, destination):
    """Publish the mapping last and roll back links created by this attempt."""
    staged_manifest = Path(manifest.pop('manifest_path'))
    manifest['path'] = str(destination)
    files = [(staged_movie, destination)]
    for segment in manifest['segments']:
        image = Path(segment['composed_keyframe'])
        final_image = destination.parent/image.name
        files.append((image, final_image))
        segment['composed_keyframe'] = str(final_image)
    write(staged_manifest, manifest)
    final_manifest = destination.with_suffix('.edit.json')
    files.append((staged_manifest, final_manifest))
    linked = []
    try:
        for original, final in files:
            with original.open('rb') as stream:
                os.fsync(stream.fileno())
            os.link(original, final)
            linked.append((original, final))
        descriptor = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except BaseException:
        for original, final in reversed(linked):
            if final.exists() and original.samefile(final):
                final.unlink()
        raise
    return {'video': str(destination), 'edit_map': str(final_manifest),
            'video_sha256': manifest['sha256'], 'edit_map_sha256': hashlib.sha256(staged_manifest.read_bytes()).hexdigest(),
            'visual_review': 'pending'}


def worker(root):
    from .video_tools import export

    record = read(root/'job.json')
    try:
        signal.signal(signal.SIGTERM, _interrupt)
        if (root/'cancel-request.json').is_file():
            raise Cancelled()
        options = read(root/'request.json')
        destination = Path(options.pop('destination'))
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() or destination.with_suffix('.edit.json').exists():
            raise SceneError('video or edit map destination exists')
        with locked(root/'finish.lock'):
            if (root/'cancel-request.json').is_file():
                raise Cancelled()
            write(root/'job.json', dict(record, state='running'))
        with tempfile.TemporaryDirectory(prefix='.simscene-video-export-', dir=destination.parent) as temp:
            staged_movie = Path(temp)/destination.name
            manifest = export(destination=staged_movie, **options)
            with locked(root/'finish.lock'):
                if (root/'cancel-request.json').is_file():
                    raise Cancelled()
                result = _publish(manifest, staged_movie, destination)
                write(root/'job.json', dict(record, state='completed', result=result, finished_unix_ns=time.time_ns()))
        return
    except Cancelled:
        terminal = {'state': 'cancelled'}
    except Exception as error:
        if isinstance(error, subprocess.CalledProcessError) and isinstance(error.stderr, bytes):
            print(error.stderr[-4096:].decode(errors='replace'), file=sys.stderr)
        terminal = {'state': 'failed', 'error': f'{type(error).__name__}: {error}'[:1500]}
    write(root/'job.json', {**record, **terminal, 'finished_unix_ns': time.time_ns()})


if __name__ == '__main__':
    worker(Path(sys.argv[1]))
