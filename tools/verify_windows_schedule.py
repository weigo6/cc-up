"""Create, inspect and immediately remove a uniquely scoped test task. No sync is run."""
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cc_up.config import Config
from cc_up.schedule import manage_schedule, task_name

if __name__ == '__main__':
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'schedule-test.json'
        config = Config(daily_times=[(datetime.now() + timedelta(minutes=10)).strftime('%H:%M')])
        created = False
        try:
            print(manage_schedule(config, path))
            created = True
            name = task_name(str(path.resolve()).casefold())
            result = subprocess.run(['schtasks.exe', '/Query', '/TN', name, '/XML'], capture_output=True)
            if result.returncode:
                raise RuntimeError('无法查询刚创建的任务')
            # Don't print the task XML or account identifiers.
            print('Windows task creation and query passed; no task was executed.')
        finally:
            if created:
                print(manage_schedule(config, path, remove=True))
