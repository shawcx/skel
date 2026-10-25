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

from . import DEFAULTS, __version__, argparser, checkout, installed, split

# where a skel that isn't a checkout or a git install gets the templates it made a project with
REPOSITORY = 'https://github.com/shawcx/skel'


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


def render(command, args, output):
    out = subprocess.run([*command, *args, '--output', output], capture_output=True, text=True)
    if out.returncode:
        raise RuntimeError(f'{" ".join(command)} failed:\n{out.stderr.strip()}')


def clone(repository, dest):
    '''a bare clone of skel, for an installed skel to get old templates from'''
    out = subprocess.run(['git', 'clone', '--quiet', '--bare', repository, dest], capture_output=True, text=True)
    if out.returncode:
        raise RuntimeError(f'Could not get skel from {repository}: {out.stderr.strip()}')


def old_skel(top, ref, dest, where):
    '''extract skel as it was at ref from the git repository at top'''
    out = subprocess.run(['git', '-C', top, 'archive', '--format=tar', ref], capture_output=True)
    if out.returncode:
        raise RuntimeError(f'{ref} is not in {where}: {out.stderr.decode().strip()}')
    with tarfile.open(fileobj=io.BytesIO(out.stdout)) as tar:
        try:
            tar.extractall(dest, filter='data')
        except TypeError:
            # Python 3.11 before 3.11.4 has no filter
            tar.extractall(dest)


def files(top):
    '''the paths of the files under top, relative to it and with / on every OS'''
    found = set()
    for base,directories,filenames in os.walk(top):
        directories[:] = [d for d in directories if d != '.git']
        for filename in filenames:
            found.add(os.path.relpath(os.path.join(base, filename), top).replace(os.sep, '/'))
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

    if not shutil.which('git'):
        argparser.error('--update needs git, to get the templates the project was made with')
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
            found = checkout()
            if found:
                top,where = found[0],f'the skel checkout {found[0]}'
                new_skel = [sys.executable, os.path.join(top, 'skel.py')]
            else:
                # an installed skel clones the repository that pip installed it from
                where = (installed() or (REPOSITORY,))[0]
                top = os.path.join(tmp, 'skel.git')
                print(f'Getting skel {ref[:12]} from {where}')
                clone(where, top)
                # -P leaves the current directory off the path, so it's this skel
                new_skel = [sys.executable, '-P', '-m', 'skel']
            old_skel(top, ref, os.path.join(tmp, 'old'), where)
            render([sys.executable, os.path.join(tmp, 'old', 'skel.py')],
                replay(record, record['with'], record['without']), os.path.join(tmp, 'base'))
            render(new_skel, replay(record, features, without), os.path.join(tmp, 'new'))
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
