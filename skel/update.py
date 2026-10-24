'''skel --update: render a project with the skel that made it and with this one,
and merge the difference into the project'''

import io
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib

from . import DEFAULTS, ROOT, __version__, argparser, checkout, split


def replay(record, features, without):
    '''the skel options that make the project again'''
    args = [record['name'], '--namespace', record['namespace']]
    if features:
        args += ['--with', ','.join(sorted(features))]
    if without:
        args += ['--without', ','.join(sorted(without))]
    for key,value in record['values'].items():
        args += ['--set', f'{key}={value}']
    return args


def render(launcher, args, output, env=None):
    out = subprocess.run([sys.executable, launcher, *args, '--output', output],
        env=env, capture_output=True, text=True)
    if out.returncode:
        raise RuntimeError(f'{launcher} failed:\n{out.stderr.strip()}')


def old_skel(top, ref, dest):
    '''extract skel as it was at ref from the checkout at top'''
    out = subprocess.run(['git', '-C', top, 'archive', '--format=tar', ref], capture_output=True)
    if out.returncode:
        raise RuntimeError(f'{ref} is not in the skel checkout {top}: {out.stderr.decode().strip()}')
    with tarfile.open(fileobj=io.BytesIO(out.stdout)) as tar:
        try:
            tar.extractall(dest, filter='data')
        except TypeError:
            # Python 3.11 before 3.11.4 has no filter
            tar.extractall(dest)


def files(top):
    '''the paths of the files under top, relative to it'''
    found = set()
    for base,directories,filenames in os.walk(top):
        directories[:] = [d for d in directories if d != '.git']
        for filename in filenames:
            found.add(os.path.relpath(os.path.join(base, filename), top))
    found.discard('.skel.toml')
    return found


def read(path):
    try:
        with open(path, 'rb') as fp:
            return fp.read()
    except FileNotFoundError:
        return None


def merge(project, base, new, dry_run):
    '''bring the changes from base to new into project, returns the number of conflicts'''
    conflicts = 0
    for path in sorted(files(base) | files(new)):
        mine,old,ours = (read(os.path.join(top, path)) for top in (project, base, new))
        target = os.path.join(project, path)

        if ours is None:
            print(f'kept      {path}  (skel no longer makes it)')
            continue
        if mine is None and old is not None:
            # deleted in the project, so leave it deleted
            if old != ours:
                print(f'skipped   {path}  (deleted here, changed in skel)')
            continue
        if mine == ours or old == ours:
            continue

        if mine is None or mine == old:
            action = 'added' if mine is None else 'updated'
            if not dry_run:
                os.makedirs(os.path.dirname(target) or '.', exist_ok=True)
                with open(target, 'wb') as fp:
                    fp.write(ours)
            print(f'{action:<9} {path}')
            continue

        if old is None:
            print(f'conflict  {path}  (new in skel, but already here, kept yours)')
            conflicts += 1
            continue
        # changed here and in skel, so merge it line by line
        if b'\0' in mine + old + ours:
            print(f'conflict  {path}  (changed here and in skel, kept yours)')
            conflicts += 1
            continue
        with tempfile.TemporaryDirectory() as tmp:
            merged = os.path.join(tmp, 'merged')
            shutil.copy(target, merged)
            out = subprocess.run(['git', 'merge-file', '-L', 'yours', '-L', 'old skel', '-L', 'new skel',
                merged, os.path.join(base, path), os.path.join(new, path)], capture_output=True, text=True)
            if out.returncode < 0:
                raise RuntimeError(f'git merge-file {path}: {out.stderr.strip()}')
            if not dry_run:
                shutil.copy(merged, target)
        if out.returncode:
            print(f'conflict  {path}  ({out.returncode} to resolve)')
            conflicts += 1
        else:
            print(f'merged    {path}')
    return conflicts


def update(args):
    project = os.path.abspath(args.update)
    try:
        with open(os.path.join(project, '.skel.toml'), 'rb') as fp:
            record = tomllib.load(fp)
    except FileNotFoundError:
        argparser.error(f'{project} has no .skel.toml, so it was made before skel --update')
    except tomllib.TOMLDecodeError as e:
        argparser.error(f'{project}/.skel.toml: {e}')

    found = checkout()
    if not found or not shutil.which('git'):
        argparser.error('--update needs git and a git checkout of skel, which has the templates the project was made with')
    top = found[0]
    ref = record.get('commit') or f'v{record["version"]}'

    # the project's features, plus or minus the ones given now
    features = set(record['with']) | split(args.features)
    without  = set(record['without']) - split(args.features)
    for feature in split(args.without):
        if feature in DEFAULTS:
            without.add(feature)
        features.discard(feature)

    with tempfile.TemporaryDirectory() as tmp:
        try:
            old_skel(top, ref, os.path.join(tmp, 'old'))
            render(os.path.join(tmp, 'old', 'skel.py'), replay(record, record['with'], record['without']),
                os.path.join(tmp, 'base'))
            render(os.path.join(top, 'skel.py'), replay(record, features, without), os.path.join(tmp, 'new'))
            conflicts = merge(project, os.path.join(tmp, 'base'), os.path.join(tmp, 'new'), args.dry_run)
        except RuntimeError as e:
            print(e, file=sys.stderr)
            return 1

        # the project now matches the current skel, which the next update starts from
        if not args.dry_run:
            shutil.copy(os.path.join(tmp, 'new', '.skel.toml'), os.path.join(project, '.skel.toml'))

    if conflicts:
        print(f'{conflicts} file(s) need their conflicts resolved', file=sys.stderr)
        return 1
    print(f'{"Would update" if args.dry_run else "Updated"} {project} from {ref[:12]} to skel {__version__}')
    return 0
