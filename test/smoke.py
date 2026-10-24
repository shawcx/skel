#!/usr/bin/env python3
'''generate a project into a temporary directory and check that it works

the web assets are not built, so this runs offline
'''

import asyncio
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile

import tornado.httpclient
import tornado.websocket


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def step(name):
    print(f'-- {name}', flush=True)


def run(*cmd, **kwds):
    subprocess.run(cmd, check=True, **kwds)


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


async def check_websockets(port):
    url = f'ws://127.0.0.1:{port}/ws'
    a = await tornado.websocket.websocket_connect(url)
    b = await tornado.websocket.websocket_connect(url)

    # the ping keep-alive must not be relayed, so the first message b sees is the JSON
    await a.write_message('ping')
    await a.write_message('{"action":"test"}')
    msg = await asyncio.wait_for(b.read_message(), 2)
    assert msg == '{"action":"test"}', f'unexpected relay: {msg!r}'

    request = tornado.httpclient.HTTPRequest(url, headers={'Origin':'http://example.com'})
    try:
        await tornado.websocket.websocket_connect(request)
    except tornado.httpclient.HTTPClientError as e:
        assert e.code == 403, e
    else:
        raise AssertionError('cross-origin WebSocket was accepted')


def check_options(tmp):
    step('unknown feature')
    project = os.path.join(tmp, 'unknown')
    rc = subprocess.run([sys.executable, os.path.join(ROOT, 'skel.py'),
        '--with', 'nope', '--output', project, 'Smoke'], capture_output=True).returncode
    assert rc == 2, f'unknown feature exited with {rc}'
    assert not os.path.exists(project), project


def check(tmp, namespace, features):
    project = os.path.join(tmp, '-'.join([namespace or 'none', *features]), 'smoke')
    module  = f'{namespace}.smoke' if namespace else 'smoke'
    package = os.path.join(project, *module.split('.'))
    env = dict(os.environ, PYTHONPATH=project)

    args = ['--namespace', namespace] if namespace else []
    if features:
        args += ['--with', ','.join(features)]

    step('generate')
    run(sys.executable, os.path.join(ROOT, 'skel.py'), *args, '--output', project, 'Smoke')
    assert os.path.isfile(os.path.join(package, 'smoke.py')), package

    step('gitignore')
    run('git', 'init', '-q', project)
    static = os.path.join(package, 'data', 'static')
    for path,ignored in [
            (os.path.join(static, 'css', 'smoke.css'), True),
            (os.path.join(static, 'js', 'smoke.js'), True),
            (os.path.join(project, 'src', 'node_modules', 'x'), True),
            (os.path.join(package, 'data', 'smoke.ini.local'), True),
            (os.path.join(static, 'favicon.ico'), False),
            (os.path.join(package, 'data', 'smoke.ini'), False),
            (os.path.join(project, 'src', 'package-lock.json'), False),
            ]:
        rc = subprocess.run(['git', '-C', project, 'check-ignore', '-q', path]).returncode
        assert (rc == 0) == ignored, f'{path} should {"" if ignored else "not "}be ignored'

    step('compile')
    run(sys.executable, '-m', 'compileall', '-q', project)

    step('version')
    out = subprocess.run([sys.executable, '-m', module, '--version'],
        env=env, check=True, capture_output=True, text=True).stdout
    assert '0.1.0' in out, out

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

    step('serve')
    port = free_port()
    server = subprocess.Popen([sys.executable, '-m', module, '--port', str(port)],
        env=env, cwd=project, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/') as rsp:
                    body = rsp.read().decode()
                break
            except OSError:
                time.sleep(0.1)
        else:
            raise AssertionError('server did not respond')
        assert '<title>Smoke</title>' in body, body

        with urllib.request.urlopen(f'http://127.0.0.1:{port}/favicon.ico') as rsp:
            assert rsp.status == 200

        asyncio.run(check_websockets(port))
    finally:
        server.terminate()
        server.wait(5)

    step('wheel')
    dist = os.path.join(project, 'dist')
    run(sys.executable, '-m', 'pip', 'wheel', '--no-deps', '--no-build-isolation',
        '-q', '-w', dist, project)
    wheel = os.listdir(dist)
    assert wheel == ['smoke-0.1.0-py3-none-any.whl'], wheel

    # the package and its data files must be inside the wheel
    with zipfile.ZipFile(os.path.join(dist, wheel[0])) as zf:
        names = zf.namelist()
    prefix = module.replace('.', '/')
    expected = ['smoke.py', 'data/smoke.ini', 'data/static/favicon.ico', 'data/templates/index.html']
    if 'systemd' in features:
        expected += ['systemd.py', 'data/systemd.service']
    for name in expected:
        assert f'{prefix}/{name}' in names, f'{prefix}/{name} missing from wheel'


def main():
    with tempfile.TemporaryDirectory() as tmp:
        check_options(tmp)
        for namespace,features in [('skunk', []), ('', []), ('skunk', ['systemd'])]:
            print(f'== namespace {namespace!r} features {features}', flush=True)
            check(tmp, namespace, features)

    print('ok')
    return 0


if '__main__' == __name__:
    sys.exit(main())
