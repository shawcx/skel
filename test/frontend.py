#!/usr/bin/env python3
'''build the web assets of a generated project and load its page in headless Chrome

needs make, npm with network access for npm install, and Chrome; set CHROME
to the browser's path if it isn't found
'''

import asyncio
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import urllib.request

import tornado.websocket

from smoke import ROOT, free_port, run, step


PREFIX = '/app'

CHROMES = [
    'google-chrome', 'chrome', 'chromium', 'chromium-browser',
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    r'C:\Program Files\Google\Chrome\Application\chrome.exe',
    r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
    ]


def find_chrome():
    for chrome in [os.environ.get('CHROME')] + CHROMES:
        if chrome and (shutil.which(chrome) or os.path.isfile(chrome)):
            return shutil.which(chrome) or chrome
    raise AssertionError('Chrome not found, set CHROME to its path')


class DevTools:
    '''just enough of the Chrome DevTools Protocol to load a page and inspect it'''

    def __init__(self, ws):
        self.ws = ws
        self.ids = 0
        self.events = []

    @classmethod
    async def connect(cls, profile):
        # with --remote-debugging-port=0 Chrome picks a port and writes it here
        active = os.path.join(profile, 'DevToolsActivePort')
        for _ in range(300):
            try:
                with open(active) as fp:
                    port = int(fp.readline())
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/json') as rsp:
                    targets = json.load(rsp)
                break
            except (OSError,ValueError):
                await asyncio.sleep(0.1)
        else:
            raise AssertionError('Chrome did not start')
        page = next(t for t in targets if t['type'] == 'page')
        ws = await tornado.websocket.websocket_connect(page['webSocketDebuggerUrl'],
            max_message_size=1 << 26)
        return cls(ws)

    async def call(self, method, **params):
        self.ids += 1
        await self.ws.write_message(json.dumps(dict(id=self.ids, method=method, params=params)))
        while True:
            msg = json.loads(await self.ws.read_message())
            if msg.get('id') == self.ids:
                if 'error' in msg:
                    raise AssertionError(f'{method}: {msg["error"]}')
                return msg['result']
            self.events.append(msg)

    async def evaluate(self, expression):
        result = await self.call('Runtime.evaluate', expression=expression,
            awaitPromise=True, returnByValue=True)
        if 'exceptionDetails' in result:
            raise AssertionError(f'{expression}: {result["exceptionDetails"]}')
        return result['result'].get('value')

    def problems(self):
        '''exceptions, console errors and failed requests'''
        for event in self.events:
            method,params = event.get('method'), event.get('params', {})
            if method == 'Runtime.exceptionThrown':
                yield params['exceptionDetails'].get('exception', {}).get('description')
            elif method == 'Runtime.consoleAPICalled' and params['type'] in ('error', 'warning'):
                yield ' '.join(str(a.get('value', a.get('description'))) for a in params['args'])
            elif method == 'Log.entryAdded' and params['entry']['level'] in ('error', 'warning'):
                yield f'{params["entry"]["text"]} {params["entry"].get("url", "")}'


async def check_page(profile, port):
    cdp = await DevTools.connect(profile)
    for domain in ('Runtime', 'Log', 'Page'):
        await cdp.call(f'{domain}.enable')
    await cdp.call('Page.navigate', url=f'http://127.0.0.1:{port}{PREFIX}/')

    # the bundle opens the WebSocket once the page is ready
    for _ in range(100):
        if await cdp.evaluate('window.app && app.socket && app.socket.ws.readyState == 1'):
            break
        await asyncio.sleep(0.1)
    else:
        raise AssertionError('the WebSocket did not connect')

    wsurl = await cdp.evaluate('app.socket.wsurl')
    assert wsurl == f'ws://127.0.0.1:{port}{PREFIX}/ws', wsurl

    # Bootstrap is bundled, for the navbar's toggle and scripts in the page
    assert await cdp.evaluate("typeof bootstrap.Collapse == 'function'"), 'Bootstrap is missing'

    # messages from another WebSocket, which the server relays, change the page's collection
    await cdp.evaluate('''app.collection('notes').addEventListener('change',
        (event) => window.changed = event.detail.text)''')
    sender = await tornado.websocket.websocket_connect(wsurl)
    async def receive(message, expression):
        await sender.write_message(json.dumps(message))
        for _ in range(50):
            result = await cdp.evaluate(expression)
            if result:
                return result
            await asyncio.sleep(0.1)
        raise AssertionError(f'{message} did not make {expression} true')
    await receive({'action':'add', 'collection':'notes', 'data':{'id':1, 'text':'hi'}},
        "app.collections.notes.get(1)?.text == 'hi'")
    await receive({'action':'update', 'collection':'notes', 'data':{'id':1, 'text':'bye'}},
        "window.changed == 'bye' && app.collections.notes.size == 1")
    await receive({'action':'delete', 'collection':'notes', 'id':1}, 'app.collections.notes.size == 0')
    sender.close()

    # the messages card posts its form, and lists messages posted elsewhere as they arrive
    items = "[...document.querySelectorAll('#messages li')].map(li => li.textContent)"
    async def until(expression):
        for _ in range(50):
            if await cdp.evaluate(expression):
                return
            await asyncio.sleep(0.1)
        raise AssertionError(f'{expression} is {await cdp.evaluate(items)}')
    await cdp.evaluate('''let form = document.querySelector('#messages form')
        form.elements.text.value = '<b>from the page</b>'
        form.requestSubmit()''')
    await until(f"JSON.stringify({items}) == '[\"<b>from the page</b>\"]'")
    assert await cdp.evaluate("document.querySelector('#messages b') == null"), 'the text became HTML'
    assert await cdp.evaluate("document.querySelector('#messages input').value == ''"), 'the form was not reset'
    request = urllib.request.Request(f'http://127.0.0.1:{port}{PREFIX}/api/messages', method='POST',
        data=json.dumps({'text':'from elsewhere'}).encode())
    urllib.request.urlopen(request).close()
    await until(f"JSON.stringify({items}) == '[\"<b>from the page</b>\",\"from elsewhere\"]'")

    # the stylesheet applies and the icon font loads from the webfonts directory
    margin = await cdp.evaluate('getComputedStyle(document.body).marginTop')
    assert margin == '80px', margin
    fonts = await cdp.evaluate('''document.fonts.load('900 1em "Font Awesome 6 Free"').then(f => f.length)''')
    assert fonts, 'the icon font did not load'

    problems = list(cdp.problems())
    assert not problems, '\n'.join(problems)
    cdp.ws.close()


def main():
    for tool in ('make', 'npm'):
        assert shutil.which(tool), f'{tool} not found'
    chrome = find_chrome()

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        project = os.path.join(tmp, 'front')
        package = os.path.join(project, 'front')
        env = dict(os.environ, PYTHONPATH=project)

        step('generate')
        run(sys.executable, os.path.join(ROOT, 'skel.py'), '--with', 'sqlite', '--output', project, 'Front')
        with open(os.path.join(package, 'data', 'front.ini.local'), 'w') as fp:
            fp.write(f'[front]\nprefix = {PREFIX}\n')

        step('build')
        run('make', '-C', project)
        static = os.path.join(package, 'data', 'static')
        for path in ('js/front.js', 'js/front.js.map', 'css/front.css', 'webfonts/fa-solid-900.woff2'):
            assert os.path.isfile(os.path.join(static, path)), f'{path} was not built'

        # the project's own Makefile targets, also on Windows
        step('make')
        run('make', '-C', project, 'venv')
        out = subprocess.run(['make', '-C', project, 'run', 'ARGS=--version'],
            capture_output=True, text=True)
        assert out.returncode == 0 and '0.1.0' in out.stdout, out
        run('make', '-C', project, 'test')
        run('make', '-C', project, 'dist')
        built = sorted(os.listdir(os.path.join(project, 'dist')))
        assert built == ['front-0.1.0-py3-none-any.whl', 'front-0.1.0.tar.gz'], built
        run('make', '-C', project, 'clean')
        leftover = [p for p in pathlib.Path(project).rglob('__pycache__') if '.venv' not in p.parts]
        assert not leftover, leftover

        step('browser')
        port = free_port()
        profile = os.path.join(tmp, 'chrome')
        # the project's venv has its packages, such as SQLAlchemy for sqlite
        python = os.path.join(project, '.venv', *(['Scripts', 'python.exe'] if os.name == 'nt' else ['bin', 'python']))
        server_log = open(os.path.join(tmp, 'server.log'), 'w+')
        server = subprocess.Popen([python, '-m', 'front', '--port', str(port)],
            env=env, cwd=project, stdout=server_log, stderr=subprocess.STDOUT)
        args = [chrome, '--headless=new', '--remote-debugging-port=0', f'--user-data-dir={profile}',
            '--no-first-run', '--no-default-browser-check', 'about:blank']
        # CI runners may not allow Chrome's sandbox, the page is our own
        if os.environ.get('CI'):
            args.insert(1, '--no-sandbox')
        log = open(os.path.join(tmp, 'chrome.log'), 'w+')
        browser = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT)
        try:
            asyncio.run(check_page(profile, port))
        except:
            for name,output in ((chrome, log), ('front', server_log)):
                output.seek(0)
                print(f'{name} output:\n{output.read()}', file=sys.stderr)
            raise
        finally:
            for proc in (browser, server):
                proc.terminate()
                proc.wait(10)
            log.close()
            server_log.close()

    print('ok')
    return 0


if '__main__' == __name__:
    sys.exit(main())
