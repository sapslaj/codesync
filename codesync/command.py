import os


def run_command(cmd, dry_run=False):
    print(cmd)
    if not dry_run:
        os.system(cmd)
