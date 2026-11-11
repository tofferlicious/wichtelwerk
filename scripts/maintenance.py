"""Run the existing mail queue every minute and cleanup daily."""
import subprocess
import sys
import time


def run_due(now, last_cleanup):
    commands = ['send-draw-mail']
    if last_cleanup is None or now-last_cleanup >= 86400:
        commands.append('cleanup')
    for command in commands:
        result = subprocess.run([sys.executable, '-m', 'flask', '--app', 'wichtelwerk:create_app()', command])
        if result.returncode:
            print(f'Maintenance {command} failed; retrying next minute.', file=sys.stderr, flush=True)
        elif command == 'cleanup':
            last_cleanup = now
    return last_cleanup


def main():
    last_cleanup = None
    while True:
        last_cleanup = run_due(time.monotonic(), last_cleanup)
        time.sleep(60)


if __name__ == '__main__':
    main()
