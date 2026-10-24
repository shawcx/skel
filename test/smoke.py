#!/usr/bin/env python3
'''generate a project into a temporary directory and check that it works

the web assets are not built, so this runs offline
'''

import asyncio
import http.cookies
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import zipfile

import tornado.httpclient
import tornado.websocket


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

sys.path.insert(0, ROOT)
from skel import DEFAULTS


def step(name):
    print(f'-- {name}', flush=True)


def run(*cmd, **kwds):
    subprocess.run(cmd, check=True, **kwds)


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


class Server:
    '''the generated app, on a new free port each time it starts'''

    def __init__(self, module, env, cwd, prefix):
        self.module = module
        self.env    = env
        self.cwd    = cwd
        self.prefix = prefix

    def start(self):
        '''start the app and return its first page'''
        self.port = free_port()
        self.proc = subprocess.Popen([sys.executable, '-m', self.module, '--port', str(self.port)],
            env=self.env, cwd=self.cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(50):
            try:
                with urllib.request.urlopen(f'http://127.0.0.1:{self.port}{self.prefix}/') as rsp:
                    return rsp.read().decode()
            except OSError:
                time.sleep(0.1)
        self.stop()
        raise AssertionError('server did not respond')

    def stop(self):
        self.proc.terminate()
        self.proc.wait(5)

    def cli(self, *args):
        '''run the app with other options, like --list-users'''
        return subprocess.run([sys.executable, '-m', self.module, *args],
            env=self.env, cwd=self.cwd, capture_output=True, text=True)


async def refused(url, headers):
    request = tornado.httpclient.HTTPRequest(url, headers=headers)
    try:
        await tornado.websocket.websocket_connect(request)
    except tornado.httpclient.HTTPClientError as e:
        assert e.code == 403, e
    else:
        raise AssertionError(f'WebSocket was accepted with {headers}')


async def check_websockets(port, prefix, headers={}):
    url = f'ws://127.0.0.1:{port}{prefix}/ws'
    a = await tornado.websocket.websocket_connect(tornado.httpclient.HTTPRequest(url, headers=headers))
    b = await tornado.websocket.websocket_connect(tornado.httpclient.HTTPRequest(url, headers=headers))

    # the ping keep-alive must not be relayed, so the first message b sees is the JSON
    await a.write_message('ping')
    await a.write_message('{"action":"test"}')
    msg = await asyncio.wait_for(b.read_message(), 2)
    assert msg == '{"action":"test"}', f'unexpected relay: {msg!r}'

    await refused(url, dict(headers, Origin='http://example.com'))


def cookies(rsp):
    '''the cookies that a response sets'''
    jar = http.cookies.SimpleCookie()
    for header in rsp.headers.get_list('Set-Cookie'):
        jar.load(header)
    return {name:morsel.value for name,morsel in jar.items()}


async def check_auth(server):
    prefix = server.prefix
    client = tornado.httpclient.AsyncHTTPClient()

    async def fetch(path, jar=None, **form):
        kwds = dict(follow_redirects=False, raise_error=False)
        if jar:
            kwds['headers'] = {'Cookie':'; '.join(f'{k}={v}' for k,v in jar.items())}
        if form:
            kwds.update(method='POST', body=urllib.parse.urlencode(form))
        return await client.fetch(f'http://127.0.0.1:{server.port}{prefix}{path}', **kwds)

    async def log_in(jar):
        rsp = await fetch('/login', jar, _xsrf=jar['_xsrf'], username='alice', password='secret')
        assert rsp.code == 302, rsp
        jar.update(cookies(rsp))

    home = prefix + '/'

    # pages and the WebSocket need a login
    rsp = await fetch('/')
    login = f'{prefix}/login?' + urllib.parse.urlencode(dict(next=home))
    assert rsp.code == 302 and rsp.headers['Location'] == login, rsp
    await refused(f'ws://127.0.0.1:{server.port}{prefix}/ws', {})

    # the login page sets the xsrf cookie, the form must send it back
    rsp = await fetch('/login?next=/')
    assert rsp.code == 200 and b'name="_xsrf"' in rsp.body, rsp
    jar = cookies(rsp)
    rsp = await fetch('/login', username='alice', password='secret')
    assert rsp.code == 403, rsp

    rsp = await fetch('/login', jar, _xsrf=jar['_xsrf'], username='alice', password='wrong')
    assert rsp.code == 403 and b'Invalid login' in rsp.body, rsp

    # next can't send people to another site
    rsp = await fetch('/login', jar, _xsrf=jar['_xsrf'], username='alice', password='secret', next='//example.com')
    assert rsp.code == 302 and rsp.headers['Location'] == home, rsp
    jar.update(cookies(rsp))
    assert 'session_id' in jar, jar

    rsp = await fetch('/', jar)
    assert rsp.code == 200 and b'alice' in rsp.body, rsp
    await check_websockets(server.port, prefix, {'Cookie':f'session_id={jar["session_id"]}'})

    out = server.cli('--list-users')
    assert out.returncode == 0 and out.stdout.split() == ['alice'], out

    # the sessions and the secret that signs their cookies survive a restart
    server.stop()
    server.start()
    rsp = await fetch('/', jar)
    assert rsp.code == 200 and b'alice' in rsp.body, rsp

    # logging out is a POST with the xsrf token, and ends the session, not just the cookie
    rsp = await fetch('/logout', jar)
    assert rsp.code == 405, rsp
    rsp = await fetch('/logout', jar, next='/')
    assert rsp.code == 403, rsp
    rsp = await fetch('/logout', jar, _xsrf=jar['_xsrf'])
    assert rsp.code == 302 and rsp.headers['Location'] == home, rsp
    rsp = await fetch('/', jar)
    assert rsp.code == 302, rsp

    # removing a user ends their sessions while the app is running
    await log_in(jar)
    rsp = await fetch('/', jar)
    assert rsp.code == 200, rsp
    out = server.cli('--remove-user', 'alice')
    assert out.returncode == 0, out
    rsp = await fetch('/', jar)
    assert rsp.code == 302, rsp
    out = server.cli('--remove-user', 'alice')
    assert out.returncode == 1 and 'No user: alice' in out.stderr, out


def check_options(tmp):
    step('bad features')
    project = os.path.join(tmp, 'bad')
    for args,error in [
            (['--with', 'nope'], 'unknown feature: nope'),
            (['--without', 'auth'], 'auth is not on by default'),
            (['--with', 'web', '--without', 'web'], 'web is in both --with and --without'),
            (['--without', 'web', '--with', 'auth'], 'auth needs web'),
            ]:
        out = subprocess.run([sys.executable, os.path.join(ROOT, 'skel.py'), *args, '--output', project, 'Smoke'],
            capture_output=True, text=True)
        assert out.returncode == 2 and error in out.stderr, (args, out)
        assert not os.path.exists(project), project


def check(tmp, namespace, features, prefix):
    project = os.path.join(tmp, '-'.join([namespace or 'none', *features]), 'smoke')
    module  = f'{namespace}.smoke' if namespace else 'smoke'
    package = os.path.join(project, *module.split('.'))
    env = dict(os.environ, PYTHONPATH=project)

    # features are all of the project's, the options add and leave out the defaults
    args = ['--namespace', namespace] if namespace else []
    if set(features) - set(DEFAULTS):
        args += ['--with', ','.join(sorted(set(features) - set(DEFAULTS)))]
    if set(DEFAULTS) - set(features):
        args += ['--without', ','.join(sorted(set(DEFAULTS) - set(features)))]

    step('generate')
    run(sys.executable, os.path.join(ROOT, 'skel.py'), *args, '--output', project, 'Smoke')
    assert os.path.isfile(os.path.join(package, 'smoke.py')), package
    if prefix:
        with open(os.path.join(package, 'data', 'smoke.ini.local'), 'w') as fp:
            fp.write(f'[smoke]\nprefix = {prefix}\n')

    step('gitignore')
    run('git', 'init', '-q', project)
    static = os.path.join(package, 'data', 'static')
    for path,ignored in [
            *([(os.path.join(static, 'css', 'smoke.css'), True),
               (os.path.join(static, 'js', 'smoke.js'), True),
               (os.path.join(project, 'src', 'node_modules', 'x'), True),
               (os.path.join(project, 'src', 'package-lock.json'), False)] if 'frontend' in features else []),
            *([(os.path.join(static, 'favicon.ico'), False)] if 'web' in features else []),
            (os.path.join(package, 'data', 'smoke.ini.local'), True),
            (os.path.join(package, 'data', 'smoke.ini'), False),
            *([(os.path.join(package, 'data', 'smoke.users'), True),
               (os.path.join(package, 'data', 'smoke.sessions'), True)] if 'auth' in features else []),
            *([(os.path.join(package, 'data', 'smoke.db'), True)] if 'sqlite' in features else []),
            ]:
        rc = subprocess.run(['git', '-C', project, 'check-ignore', '-q', path]).returncode
        assert (rc == 0) == ignored, f'{path} should {"" if ignored else "not "}be ignored'

    step('compile')
    run(sys.executable, '-m', 'compileall', '-q', project)

    step('version')
    out = subprocess.run([sys.executable, '-m', module, '--version'],
        env=env, check=True, capture_output=True, text=True).stdout
    assert '0.1.0' in out, out

    step('json')
    code = (f'import datetime, uuid, {module}; print({module}.json_encode(dict(b=b"hi", '
        'u=uuid.UUID(int=1), d=datetime.date(2026, 1, 2), t=datetime.timedelta(seconds=90))))')
    out = subprocess.run([sys.executable, '-c', code],
        env=env, check=True, capture_output=True, text=True).stdout
    assert out.strip() == ('{"b": "aGk=", "u": "00000000-0000-0000-0000-000000000001", '
        '"d": "2026-01-02", "t": 90.0}'), out

    step('errors')
    bad = os.path.join(project, 'bad.ini')
    with open(bad, 'w') as fp:
        fp.write('not an ini file\n')
    rsp = subprocess.run([sys.executable, '-m', module, '--ini', bad],
        env=env, capture_output=True, text=True)
    assert rsp.returncode == 1 and 'Unable to parse' in rsp.stderr, rsp

    step('systemd')
    if 'systemd' in features:
        # write the service into the project instead of /etc
        ini = os.path.join(project, 'systemd.ini')
        service = os.path.join(project, 'smoke.service')
        with open(ini, 'w') as fp:
            fp.write(f'[systemd]\npath = {service}\n')
        run(sys.executable, '-m', module, '--ini', ini, '--systemd', 'nobody', env=env, cwd=project)
        with open(service) as fp:
            conf = dict(line.split('=', 1) for line in fp.read().splitlines() if '=' in line)
        assert conf['User'] == 'nobody', conf
        assert f'-m {module} --ini' in conf['ExecStart'], conf
        assert os.path.samefile(conf['WorkingDirectory'], project), conf
    else:
        assert not os.path.exists(os.path.join(package, 'systemd.py'))
        rc = subprocess.run([sys.executable, '-m', module, '--systemd'],
            env=env, capture_output=True).returncode
        assert rc == 2, f'--systemd without the feature exited with {rc}'

    step('nginx')
    if 'nginx' in features:
        # write the site into the project instead of /etc
        ini = os.path.join(project, 'nginx.ini')
        site = os.path.join(project, 'nginx.site')
        with open(ini, 'w') as fp:
            fp.write(f'[nginx]\npath = {site}\n')
        run(sys.executable, '-m', module, '--ini', ini, '--nginx', 'smoke.example.com', '--port', '9999',
            env=env, cwd=project)
        with open(site) as fp:
            conf = fp.read()
        for line in ('server 127.0.0.1:9999;', 'server_name smoke.example.com;',
                f'location ^~ {prefix}/static/ {{', f'location {prefix}/ws {{', f'location {prefix}/ {{'):
            assert line in conf, f'{line!r} not in nginx site:\n{conf}'
        # the temp directory has another path on macOS, /private/var for /var
        alias = re.search(r'alias (.*)/;', conf)
        assert alias and os.path.samefile(alias[1], os.path.join(package, 'data', 'static')), conf

        # without a server name it fails
        rc = subprocess.run([sys.executable, '-m', module, '--ini', ini, '--nginx'],
            env=env, capture_output=True).returncode
        assert rc == 1, f'--nginx without a server name exited with {rc}'

        # a path of - prints the site, and with static_path empty, as in a container,
        # nginx sends the static files to the app too
        with open(ini, 'w') as fp:
            fp.write('[nginx]\npath = -\nstatic_path =\n')
        out = subprocess.run([sys.executable, '-m', module, '--ini', ini, '--nginx', 'smoke.example.com'],
            env=env, capture_output=True, text=True)
        assert out.returncode == 0 and 'server_name smoke.example.com;' in out.stdout, out
        assert 'alias' not in out.stdout and f'location {prefix}/ {{' in out.stdout, out.stdout
    else:
        assert not os.path.exists(os.path.join(package, 'nginx.py'))
        rc = subprocess.run([sys.executable, '-m', module, '--nginx', 'x'],
            env=env, capture_output=True).returncode
        assert rc == 2, f'--nginx without the feature exited with {rc}'

    step('auth')
    if 'auth' in features:
        run(sys.executable, '-m', module, '--add-user', 'alice', env=env, input='secret\n', text=True)
        with open(os.path.join(package, 'data', 'smoke.users')) as fp:
            assert fp.read().startswith('alice:scrypt$'), 'user not saved'
    else:
        assert not os.path.exists(os.path.join(package, 'auth.py'))
        rc = subprocess.run([sys.executable, '-m', module, '--add-user', 'alice'],
            env=env, capture_output=True).returncode
        assert rc == 2, f'--add-user without the feature exited with {rc}'

    # which files the features add
    for name,feature in [('src/Makefile', 'frontend'), (f'{module.replace(".", "/")}/handlers/base.py', 'web'),
            ('.github/workflows/test.yml', 'github'), ('.gitlab-ci.yml', 'gitlab'),
            ('Dockerfile', 'docker'), ('compose.yaml', 'docker'), ('docker/smoke.ini', 'docker')]:
        assert os.path.isfile(os.path.join(project, name)) == (feature in features), name

    if 'web' in features:
        check_serve(features, prefix, module, env, project, package)
    else:
        check_run(module, env, project)

    step('pytest')
    run(sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider', cwd=project)

    step('wheel')
    # files made at run time must stay out of the wheel
    for name in ('smoke.ini.local', 'smoke.log'):
        open(os.path.join(package, 'data', name), 'w').close()
    dist = os.path.join(project, 'dist')
    run(sys.executable, '-m', 'pip', 'wheel', '--no-deps', '--no-build-isolation',
        '-q', '-w', dist, project)
    wheel = os.listdir(dist)
    assert wheel == ['smoke-0.1.0-py3-none-any.whl'], wheel

    # the package and its data files must be inside the wheel
    with zipfile.ZipFile(os.path.join(dist, wheel[0])) as zf:
        names = zf.namelist()
    top = module.replace('.', '/')
    expected = ['smoke.py', 'data/smoke.ini']
    if 'web' in features:
        expected += ['handlers/base.py', 'data/static/favicon.ico', 'data/templates/index.html']
    if 'systemd' in features:
        expected += ['systemd.py', 'data/systemd.service']
    if 'nginx' in features:
        expected += ['nginx.py', 'data/nginx.conf', 'data/nginx-static.conf']
    if 'sqlite' in features:
        expected += ['db.py', 'models.py'] + (['handlers/messages.py'] if 'web' in features else [])
    if 'auth' in features:
        expected += ['auth.py', 'handlers/login.py', 'data/templates/login.html']
    for name in expected:
        assert f'{top}/{name}' in names, f'{top}/{name} missing from wheel'
    for name in ('data/smoke.ini.local', 'data/smoke.log', 'data/smoke.users', 'data/smoke.sessions', 'data/smoke.db'):
        assert f'{top}/{name}' not in names, f'{top}/{name} is in the wheel'
    if 'web' not in features:
        assert not any('/handlers/' in name for name in names), names


def check_serve(features, prefix, module, env, project, package):
    step('serve')
    server = Server(module, env, project, prefix)
    body = server.start()
    try:
        assert '<title>Smoke</title>' in body, body
        # links and static files use the prefix
        assert f'data-prefix="{prefix}"' in body and f'href="{prefix}/static/' in body, body
        # the stylesheet and script come with the frontend
        stylesheet = f'href="{prefix}/static/css/smoke.css'
        assert (stylesheet in body) == ('frontend' in features), body

        for path in [f'{prefix}/static/favicon.ico'] + ([] if prefix else ['/favicon.ico']):
            with urllib.request.urlopen(f'http://127.0.0.1:{server.port}{path}') as rsp:
                assert rsp.status == 200, path

        asyncio.run(check_auth(server) if 'auth' in features else check_websockets(server.port, prefix))
    finally:
        server.stop()

    # only the owner can read the password hashes and the cookie secret
    if 'auth' in features and os.name == 'posix':
        for name in ('smoke.users', 'smoke.sessions'):
            mode = os.stat(os.path.join(package, 'data', name)).st_mode & 0o777
            assert mode == 0o600, f'{name} is {oct(mode)}'


def check_run(module, env, project):
    '''an app without web runs until it's stopped'''
    step('run')
    proc = subprocess.Popen([sys.executable, '-m', module], env=env, cwd=project,
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    for line in proc.stderr:
        if 'Smoke is running' in line:
            break
    else:
        raise AssertionError('the app did not start')
    proc.terminate()
    # SIGTERM stops it cleanly, on Windows terminate() kills it
    code = proc.wait(10)
    assert code == 0 or os.name != 'posix', code


def main():
    # the generated tests need pytest, and the sqlite feature its packages
    for module in ('pytest', 'sqlalchemy', 'aiosqlite'):
        try:
            __import__(module)
        except ImportError:
            print(f'{module} is needed, install the test packages with:\n'
                '  python3 -m pip install tornado "setuptools>=77" pytest "sqlalchemy[asyncio]" aiosqlite',
                file=sys.stderr)
            return 1
    with tempfile.TemporaryDirectory() as tmp:
        check_options(tmp)
        everything = ['auth', 'docker', 'frontend', 'github', 'gitlab', 'nginx', 'sqlite', 'systemd', 'web']
        for namespace,features,prefix in [
                ('skunk', DEFAULTS, ''),
                ('', DEFAULTS, ''),
                ('skunk', everything, '/app'),
                # without a frontend, and without web at all
                ('', ['auth', 'web'], ''),
                ('skunk', ['docker', 'github', 'sqlite', 'systemd'], ''),
                ]:
            print(f'== namespace {namespace!r} features {features} prefix {prefix!r}', flush=True)
            check(tmp, namespace, features, prefix)

    print('ok')
    return 0


if '__main__' == __name__:
    sys.exit(main())
