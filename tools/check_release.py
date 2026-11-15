"""Offline release checks: syntax, links, tests, archive content, and checksums."""
from __future__ import annotations

import ast
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.build_release import __version__, main as build_release, release_files


def run(*command: str) -> None:
    subprocess.run(command, cwd=ROOT, check=True)


def main() -> int:
    files, frontend = release_files()
    package = json.loads((ROOT / 'cloudflare/package.json').read_text(encoding='utf-8'))
    lock = json.loads((ROOT / 'cloudflare/package-lock.json').read_text(encoding='utf-8'))
    if package['devDependencies'] != lock['packages']['']['devDependencies']:
        raise ValueError('Worker 依赖声明与 package-lock.json 不一致。')
    credentials = re.compile(
        r'(?:sk-(?:proj-|ant-)?[A-Za-z0-9_-]{24,}|gh[pousr]_[A-Za-z0-9]{30,}'
        r'|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'
        r'|(?:SYNC_TOKEN|CC_UP_TOKEN)\s*[:=]\s*[\"\x27][A-Za-z0-9_-]{32,128}[\"\x27])'
    )
    for path in files:
        if credentials.search(path.read_text(encoding='utf-8')):
            raise ValueError(f'发现疑似凭据，请检查：{path.relative_to(ROOT)}')
        if path.suffix in ('.py', '.pyw'):
            ast.parse(path.read_text(encoding='utf-8'), filename=str(path), feature_version=(3, 11))
        elif path.suffix == '.mjs':
            run('node', '--check', str(path))
        if path.suffix == '.md':
            for target in re.findall(r'\]\(([^\s)]+)(?:\s+[^)]*)?\)', path.read_text(encoding='utf-8')):
                link = urlsplit(target.strip('<>'))
                if not link.scheme and link.path and not (path.parent / unquote(link.path)).is_file():
                    raise ValueError(f'文档链接无效：{path.relative_to(ROOT)} → {target}')
    print('源文件语法、文档链接、版本、依赖锁文件和常见凭据检查通过。', flush=True)
    run(sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v')
    tests = sorted(str(path) for pattern in ('frontend/test/*.test.mjs', 'cloudflare/test/*.test.mjs', 'tools/test/*.test.mjs')
                   for path in ROOT.glob(pattern))
    run('node', '--test', *tests)
    build_release()
    expected = [(ROOT / 'dist' / f'CC-Up-{__version__}.zip', files, ROOT, 'CC-Up/'),
                (ROOT / 'dist/CC-Up-Web.zip', frontend, ROOT / 'frontend', '')]
    first_hashes = []
    for output, included, base, prefix in expected:
        first_hashes.append(hashlib.sha256(output.read_bytes()).hexdigest())
        with ZipFile(output) as archive:
            if archive.testzip() is not None:
                raise ValueError(f'压缩包损坏：{output.name}')
            names = [prefix + path.relative_to(base).as_posix() for path in included]
            if archive.namelist() != names:
                raise ValueError(f'压缩包清单不一致：{output.name}')
            for path, name in zip(included, names):
                if archive.read(name) != path.read_bytes():
                    raise ValueError(f'压缩包内容过时：{name}')
    build_release()
    for (output, *_), checksum in zip(expected, first_hashes):
        if hashlib.sha256(output.read_bytes()).hexdigest() != checksum:
            raise ValueError(f'重复构建结果不一致：{output.name}')
    manifest = ''.join(checksum + '  ' + item[0].name + '\n' for item, checksum in zip(expected, first_hashes))
    if (ROOT / 'dist/SHA256SUMS.txt').read_text(encoding='utf-8') != manifest:
        raise ValueError('发布包 SHA-256 校验清单不一致。')
    print('发布包内容、SHA-256 和重复构建检查通过。')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print('发布检查失败：' + str(error), file=sys.stderr)
        raise SystemExit(1)
