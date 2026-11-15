"""Build reproducible, allowlisted source and web bundles without local settings."""
from __future__ import annotations

import hashlib
import sys
import tomllib
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cc_up import __version__


def release_files() -> tuple[list[Path], list[Path]]:
    files = [ROOT / name for name in (
        '.gitignore', '.gitattributes', 'README.md', 'CHANGELOG.md', 'THIRD_PARTY_NOTICES.md',
        'LICENSE', 'pyproject.toml', 'netlify.toml', 'cc_up_launcher.py', 'CC-Up.pyw', '立即同步.cmd',
        'cloudflare/package.json', 'cloudflare/package-lock.json', 'cloudflare/wrangler.jsonc',
        'cloudflare/dashboard-schema.sql', '.github/workflows/ci.yml',
    )]
    for pattern in ('cc_up/*.py', 'tools/*.py', 'tools/*.mjs', 'tools/test/*.test.mjs', 'tests/*.py',
                    'cloudflare/src/*.mjs', 'cloudflare/test/*.mjs', 'cloudflare/migrations/*.sql', 'docs/*.md'):
        files.extend(ROOT.glob(pattern))
    # An explicit web list prevents stray generated files or credentials entering a release.
    frontend = [ROOT / 'frontend' / name for name in (
        'index.html', '_headers', 'README.md', 'assets/app.mjs', 'assets/core.mjs',
        'assets/demo.mjs', 'assets/styles.css', 'assets/favicon.svg',
    )]
    files.extend(frontend)
    files.extend(ROOT.glob('frontend/test/*.test.mjs'))
    missing = [path.relative_to(ROOT).as_posix() for path in files if not path.is_file()]
    if missing:
        raise ValueError('缺少打包文件：' + '、'.join(missing))
    version = tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))['project']['version']
    if version != __version__:
        raise ValueError('pyproject.toml 与 cc_up/__init__.py 的版本不一致。')
    return sorted(set(files)), sorted(frontend)


def write_archive(output: Path, files: list[Path], base: Path, prefix: str = '') -> None:
    temporary = output.with_suffix('.zip.tmp')
    try:
        with ZipFile(temporary, 'w', ZIP_DEFLATED) as archive:
            for path in files:
                info = ZipInfo(prefix + path.relative_to(base).as_posix(), date_time=(1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                info.compress_type = ZIP_DEFLATED
                archive.writestr(info, path.read_bytes())
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    files, frontend = release_files()
    output_dir = ROOT / 'dist'
    output_dir.mkdir(exist_ok=True)
    outputs = [output_dir / f'CC-Up-{__version__}.zip', output_dir / 'CC-Up-Web.zip']
    write_archive(outputs[0], files, ROOT, 'CC-Up/')
    write_archive(outputs[1], frontend, ROOT / 'frontend')
    sums = []
    for output in outputs:
        sums.append(hashlib.sha256(output.read_bytes()).hexdigest() + '  ' + output.name)
        print(f'已生成：{output}（{output.stat().st_size:,} 字节）')
    (output_dir / 'SHA256SUMS.txt').write_text('\n'.join(sums) + '\n', encoding='utf-8', newline='\n')
    print('已生成 SHA256SUMS.txt。')


if __name__ == '__main__':
    main()
