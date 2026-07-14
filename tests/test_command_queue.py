import base64
import shlex
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from command_queue import CommandQueue


def wait_for(queue, execution_id, statuses, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = queue.get_state(execution_id)
        if state['status'] in statuses:
            return state
        time.sleep(0.02)
    pytest.fail(f'{execution_id} did not reach {statuses}: {queue.get_state(execution_id)}')


def python_command(code):
    return f'"{sys.executable}" -c "{code}"'


def test_enqueue_returns_immediately_and_captures_cursor_output(tmp_path):
    queue = CommandQueue(tmp_path / 'queue.sqlite3', tmp_path / 'logs', worker_limit=1)
    started = time.monotonic()
    job = queue.enqueue(python_command("import time; print('one', flush=True); time.sleep(.2); print('two')"))
    assert time.monotonic() - started < 0.15
    assert job['status'] in {'queued', 'starting', 'running'}

    final = wait_for(queue, job['execution_id'], {'success'})
    page = queue.get_state(job['execution_id'], after_cursor=0, limit=1)
    assert page['lines'][0]['text'] == 'one'
    assert page['has_more'] is True
    rest = queue.get_output(job['execution_id'], after_cursor=page['cursor'], limit=10)
    assert [line['text'] for line in rest['lines']] == ['two']
    assert final['exit_code'] == 0
    assert final['line_count'] == 2
    queue.close()


def test_fifo_worker_limit_and_stop_starts_next(tmp_path):
    queue = CommandQueue(tmp_path / 'queue.sqlite3', tmp_path / 'logs', worker_limit=1)
    first = queue.enqueue(python_command('import time; time.sleep(5)'))
    second = queue.enqueue(python_command("print('next')"))
    wait_for(queue, first['execution_id'], {'running'})
    assert queue.get_state(second['execution_id'])['status'] == 'queued'

    stopped = queue.stop(first['execution_id'])
    assert stopped['status'] in {'cancelled', 'running'}
    wait_for(queue, first['execution_id'], {'cancelled'})
    wait_for(queue, second['execution_id'], {'success'})
    queue.close()


def test_timeout_and_failure_statuses(tmp_path):
    queue = CommandQueue(tmp_path / 'queue.sqlite3', tmp_path / 'logs', worker_limit=2)
    timeout = queue.enqueue(python_command('import time; time.sleep(5)'), timeout_seconds=.15)
    failure = queue.enqueue(python_command("import sys; print('bad', file=sys.stderr); sys.exit(3)"))
    assert wait_for(queue, timeout['execution_id'], {'timeout'})['exit_code'] is not None
    failed = wait_for(queue, failure['execution_id'], {'failed'})
    assert failed['exit_code'] == 3
    assert failed['last_stream'] == 'stderr'
    queue.close()


def test_cr_replaces_current_line_and_partial_chunks_are_flushed(tmp_path):
    queue = CommandQueue(tmp_path / 'queue.sqlite3', tmp_path / 'logs', worker_limit=1)
    code = "import sys,time; sys.stdout.write('10%\\r20%\\r30%'); sys.stdout.flush()"
    job = queue.enqueue(python_command(code))
    final = wait_for(queue, job['execution_id'], {'success'})
    output = queue.get_output(job['execution_id'], limit=20)
    assert final['last_line'] == '30%'
    assert [line['text'] for line in output['lines']] == ['10%', '20%', '30%']
    assert [line['replace'] for line in output['lines']] == [False, True, True]
    queue.close()


def test_unknown_id_and_safe_cwd_validation(tmp_path):
    queue = CommandQueue(tmp_path / 'queue.sqlite3', tmp_path / 'logs', worker_limit=1)
    with pytest.raises(ValueError, match='unknown execution_id'):
        queue.get_state('missing')
    with pytest.raises(ValueError, match='cwd'):
        queue.enqueue('echo no', cwd=str(tmp_path / 'missing'))
    queue.close()


def test_retention_removes_old_output_and_history(tmp_path):
    queue = CommandQueue(
        tmp_path / 'queue.sqlite3', tmp_path / 'logs', worker_limit=1,
        max_lines_per_execution=100, history_limit=10,
    )
    large = queue.enqueue(python_command("[print(i) for i in range(110)]"))
    final = wait_for(queue, large['execution_id'], {'success'})
    output = queue.get_output(large['execution_id'], limit=200)
    assert final['truncated'] is True
    assert len(output['lines']) == 100
    assert output['lines'][0]['text'] == '10'
    offset = 0
    chunks = []
    while True:
        page = queue.get_log(large['execution_id'], offset=offset, limit_bytes=1024)
        chunks.append(base64.b64decode(page['content_base64']))
        offset = page['offset']
        if not page['has_more']:
            break
    full_log = b''.join(chunks).decode()
    assert '\n0\n' in full_log
    assert '\n109\n' in full_log
    for index in range(11):
        job = queue.enqueue(python_command(f"print({index})"))
        wait_for(queue, job['execution_id'], {'success'})
    with pytest.raises(ValueError, match='unknown execution_id'):
        queue.get_state(large['execution_id'])
    queue.close()


def test_stop_kills_child_process_tree(tmp_path):
    if sys.platform == 'win32':
        pytest.skip('POSIX process-group assertion')
    queue = CommandQueue(tmp_path / 'queue.sqlite3', tmp_path / 'logs', worker_limit=1)
    pid_file = tmp_path / 'child.pid'
    child = f"import os,time,pathlib; pathlib.Path(r'{pid_file}').write_text(str(os.getpid())); time.sleep(30)"
    parent = f"import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',{child!r}]); time.sleep(30)"
    job = queue.enqueue(f'"{sys.executable}" -c {shlex.quote(parent)}')
    wait_for(queue, job['execution_id'], {'running'})
    deadline = time.monotonic() + 2
    while not pid_file.exists() and time.monotonic() < deadline:
        time.sleep(.02)
    queue.stop(job['execution_id'])
    wait_for(queue, job['execution_id'], {'cancelled'})
    child_pid = int(pid_file.read_text())
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        try:
            __import__('os').kill(child_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(.02)
    else:
        pytest.fail('child survived stop')
    queue.close()


def test_restart_marks_active_execution_interrupted(tmp_path):
    db = tmp_path / 'queue.sqlite3'
    queue = CommandQueue(db, tmp_path / 'logs', worker_limit=0)
    job = queue.enqueue('echo interrupted')
    with queue._connect() as connection:
        connection.execute(
            "UPDATE executions SET status='running',pid=NULL WHERE execution_id=?",
            (job['execution_id'],),
        )
    queue.close()
    restarted = CommandQueue(db, tmp_path / 'logs', worker_limit=1)
    assert restarted.get_state(job['execution_id'])['status'] == 'interrupted'
    assert restarted.queue_state()['recovery_required'] is True
    restarted.close()


def test_restart_suspends_queue_until_atomic_recovery_choice(tmp_path):
    db = tmp_path / 'queue.sqlite3'
    logs = tmp_path / 'logs'
    queue = CommandQueue(db, logs, worker_limit=0)
    queued = queue.enqueue(python_command("print('resumed')"))
    queue.close()

    restarted = CommandQueue(db, logs, worker_limit=1)
    state = restarted.queue_state()
    assert state['recovery_required'] is True
    assert state['commands'][0]['status'] == 'waiting'
    time.sleep(.1)
    assert restarted.get_state(queued['execution_id'])['status'] == 'waiting'

    recovery = restarted.resolve_recovery('resume')
    assert recovery['recovery_required'] is False
    wait_for(restarted, queued['execution_id'], {'success'})
    restarted.close()


def test_callback_failure_does_not_strand_next_command(tmp_path):
    def broken_callback(execution_id, state):
        raise RuntimeError('callback failed')

    queue = CommandQueue(
        tmp_path / 'queue.sqlite3', tmp_path / 'logs', worker_limit=1, on_event=broken_callback,
    )
    first = queue.enqueue(python_command("print('first')"))
    second = queue.enqueue(python_command("print('second')"))
    wait_for(queue, first['execution_id'], {'success'})
    wait_for(queue, second['execution_id'], {'success'})
    queue.close()


def test_unterminated_output_is_bounded_and_split(tmp_path):
    queue = CommandQueue(tmp_path / 'queue.sqlite3', tmp_path / 'logs', worker_limit=1)
    job = queue.enqueue(python_command("print('x' * 70000, end='')"))
    final = wait_for(queue, job['execution_id'], {'success'})
    assert final['line_count'] == 2
    queue.close()


def test_restart_can_clear_waiting_queue(tmp_path):
    db = tmp_path / 'queue.sqlite3'
    queue = CommandQueue(db, tmp_path / 'logs', worker_limit=0)
    job = queue.enqueue('echo no')
    queue.close()
    restarted = CommandQueue(db, tmp_path / 'logs', worker_limit=1)
    restarted.resolve_recovery('clear')
    assert restarted.get_state(job['execution_id'])['status'] == 'cancelled'
    restarted.close()
