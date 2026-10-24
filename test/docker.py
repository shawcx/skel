#!/usr/bin/env python3
'''build and run generated projects with docker compose, a web app with auth,
nginx and sqlite, and a service without web

needs docker with compose, and network access to pull images and packages
'''

import asyncio
import http.cookies
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.parse

import tornado.httpclient

from smoke import ROOT, free_port, run, step


class Stack:
    '''a generated project run with docker compose under its own project name'''

    def __init__(self, project, service, **env):
        self.project = project
        self.service = service
        self.name    = f'skel-test-{service}-{os.getpid()}'
        self.env     = dict(os.environ, **env)

    def compose(self, *args, input=None):
        return subprocess.run(['docker', 'compose', '-p', self.name, *args], cwd=self.project,
            env=self.env, input=input, capture_output=True, text=True)

    def check(self, *args, input=None):
        out = self.compose(*args, input=input)
        assert out.returncode == 0, f'docker compose {" ".join(args)}:\n{out.stdout}\n{out.stderr}'
        return out.stdout

    def exec(self, *args):
        return self.check('exec', '-T', self.service, *args).strip()

    def container(self):
        return self.check('ps', '-aq', self.service).strip()

    def inspect(self, field):
        return subprocess.run(['docker', 'inspect', '-f', field, self.container()],
            capture_output=True, text=True).stdout.strip()

    def healthy(self):
        for _ in range(120):
            if self.inspect('{{.State.Health.Status}}') == 'healthy':
                return
            time.sleep(1)
        raise AssertionError(f'not healthy:\n{self.compose("logs").stdout}')

    def logs(self, text):
        for _ in range(60):
            if text in self.compose('logs').stdout:
                return
            time.sleep(1)
        raise AssertionError(f'{text!r} not in the logs:\n{self.compose("logs").stdout}')

    def stop(self):
        '''stop the app and return its exit code'''
        self.check('stop')
        return self.inspect('{{.State.ExitCode}}')

    def layer_files(self):
        '''the names of the files in every layer of the image'''
        saved = subprocess.run(['docker', 'save', self.inspect('{{.Config.Image}}')],
            capture_output=True, check=True).stdout
        names = set()
        with tarfile.open(fileobj=io.BytesIO(saved)) as outer:
            for member in outer.getmembers():
                if not member.isfile():
                    continue
                try:
                    with tarfile.open(fileobj=outer.extractfile(member)) as layer:
                        names.update(layer.getnames())
                except tarfile.ReadError:
                    # the manifest and config are JSON
                    pass
        return names

    def down(self):
        self.compose('down', '--volumes', '--rmi', 'local')


def generate(tmp, *args):
    project = os.path.join(tmp, args[-1].lower())
    run(sys.executable, os.path.join(ROOT, 'skel.py'), *args[:-1], '--output', project, args[-1])
    return project


class Browser:
    '''an HTTP client that keeps cookies and doesn't follow redirects'''

    def __init__(self, port):
        self.port = port
        self.cookies = {}

    async def fetch(self, path, **kwds):
        headers = {'Cookie':'; '.join(f'{k}={v}' for k,v in self.cookies.items())}
        rsp = await tornado.httpclient.AsyncHTTPClient().fetch(f'http://127.0.0.1:{self.port}{path}',
            headers=headers, follow_redirects=False, raise_error=False, **kwds)
        for header in rsp.headers.get_list('Set-Cookie'):
            for name,morsel in http.cookies.SimpleCookie(header).items():
                self.cookies[name] = morsel.value
        return rsp


async def log_in(browser):
    rsp = await browser.fetch('/')
    assert rsp.code == 302, rsp
    await browser.fetch('/login')
    form = dict(_xsrf=browser.cookies['_xsrf'], username='alice', password='secret')
    rsp = await browser.fetch('/login', method='POST', body=urllib.parse.urlencode(form))
    assert rsp.code == 302, rsp

    rsp = await browser.fetch('/')
    assert rsp.code == 200 and b'alice' in rsp.body, rsp
    # the image built the web assets
    rsp = await browser.fetch('/static/css/web.css')
    assert rsp.code == 200 and len(rsp.body) > 10000, rsp
    rsp = await browser.fetch('/api/messages', method='POST', body=json.dumps({'text':'hi'}))
    assert rsp.code == 201, rsp


async def still_logged_in(browser):
    rsp = await browser.fetch('/')
    assert rsp.code == 200 and b'alice' in rsp.body, rsp
    rsp = await browser.fetch('/api/messages')
    assert [m['text'] for m in json.loads(rsp.body)['data']] == ['hi'], rsp.body


def check_web(tmp):
    project = generate(tmp, '--namespace', 'skunk', '--with', 'auth,docker,nginx,sqlite', 'Web')
    # files that must stay out of the image
    data = os.path.join(project, 'skunk', 'web', 'data')
    with open(os.path.join(data, 'web.users'), 'w') as fp:
        fp.write('eve:planted\n')
    with open(os.path.join(data, 'web.ini.local'), 'w') as fp:
        fp.write('[web]\n')

    port = free_port()
    stack = Stack(project, 'web', PORT=str(port))
    try:
        step('build web')
        stack.check('up', '--detach', '--build')
        stack.healthy()

        step('users')
        stack.check('run', '--rm', '-T', 'web', '--add-user', 'alice', input='secret\n')
        browser = Browser(port)
        asyncio.run(log_in(browser))

        step('container')
        assert stack.exec('id', '-u') == '1000'
        modes = stack.exec('stat', '-c', '%n %a', '/data/web.users', '/data/web.sessions')
        assert modes.split() == ['/data/web.users', '600', '/data/web.sessions', '600'], modes
        out = stack.compose('exec', '-T', 'web', 'touch', '/usr/x')
        assert out.returncode != 0, 'the root filesystem is writable'
        # no layer of the image has the local files, or the source tree
        names = stack.layer_files()
        assert any(name.endswith('/skunk/web/data/web.ini') for name in names), 'package not installed'
        leaked = [name for name in names if name.endswith(('web.users', 'web.ini.local', 'src/package.json'))]
        assert not leaked, leaked

        step('nginx')
        # the container prints a site for nginx on the host, which passes everything
        # to the port compose publishes
        site = stack.check('run', '--rm', '-T', 'web', '--nginx', 'web.example.com', '--port', str(port))
        assert 'server_name web.example.com;' in site and f'server 127.0.0.1:{port};' in site, site
        assert 'alias' not in site, site

        step('restart')
        stack.check('restart')
        stack.healthy()
        asyncio.run(still_logged_in(browser))
        code = stack.stop()
        assert code == '0', code
    finally:
        stack.down()


def check_service(tmp):
    project = generate(tmp, '--without', 'web', '--with', 'docker,sqlite', 'Worker')
    stack = Stack(project, 'worker')
    try:
        step('build service')
        stack.check('up', '--detach', '--build')
        stack.logs('Worker is running')
        assert stack.exec('ls', '/data') == 'worker.db'
        code = stack.stop()
        assert code == '0', code
        assert 'Terminating Worker on SIGTERM' in stack.compose('logs').stdout
    finally:
        stack.down()


def main():
    out = subprocess.run(['docker', 'compose', 'version'], capture_output=True, text=True)
    assert out.returncode == 0, f'docker compose is needed:\n{out.stderr}'

    with tempfile.TemporaryDirectory() as tmp:
        check_web(tmp)
        check_service(tmp)

    print('ok')
    return 0


if '__main__' == __name__:
    sys.exit(main())
