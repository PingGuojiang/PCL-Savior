"""Official GitHub release discovery and verified, explicitly managed downloads."""
import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path


class ServiceError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


REPOSITORIES = {'PCL': 'Meloong-Git/PCL', 'HMCL': 'HMCL-dev/HMCL', 'PCL_CE': 'PCL-Community/PCL-CE'}
ALLOWED_HOSTS = {'github.com', 'objects.githubusercontent.com', 'release-assets.githubusercontent.com', 'api.github.com'}


def validate_asset_url(url):
    if not isinstance(url, str):
        raise ServiceError('invalid_url', 'Download URL must be HTTPS on an official GitHub host.')
    try:
        parsed = urllib.parse.urlsplit(url)
        valid = parsed.scheme == 'https' and parsed.hostname in ALLOWED_HOSTS and parsed.port in (None, 443) and not parsed.username and not parsed.password and not parsed.fragment
    except ValueError:
        valid = False
    if not valid:
        raise ServiceError('invalid_url', 'Download URL must be HTTPS on an official GitHub host.')
    return url


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_asset_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _semver(value):
    match = re.fullmatch(r'v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?', value)
    if not match:
        raise ServiceError('invalid_version', 'Version must use semantic versioning, such as 1.2.3-beta.1.')
    pre = match[4]
    parts = pre.split('.') if pre else []
    if any(not p or (p.isdigit() and len(p) > 1 and p[0] == '0') for p in parts):
        raise ServiceError('invalid_version', 'Invalid semantic version prerelease.')
    return tuple(map(int, match.groups()[:3])), parts


def version_is_newer(candidate, current):
    main_a, pre_a = _semver(candidate)
    main_b, pre_b = _semver(current)
    if main_a != main_b:
        return main_a > main_b
    if not pre_a or not pre_b:
        return bool(pre_b) and not pre_a
    for a, b in zip(pre_a, pre_b):
        if a == b:
            continue
        if a.isdigit() and b.isdigit():
            return int(a) > int(b)
        if a.isdigit() != b.isdigit():
            return not a.isdigit()
        return a > b
    return len(pre_a) > len(pre_b)


def _sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _rename_exclusive(source, target):
    if os.name == 'nt':
        os.rename(source, target)
    else:
        os.link(source, target)
        source.unlink()


class GitHubService:
    def __init__(self, store, transport=None):
        self.store = store
        self.transport = transport or urllib.request.build_opener(SafeRedirect()).open
        self._recover_deletions()

    def _recover_deletions(self):
        for item in self.store.pending_deletions():
            target = Path(item.get('target', '')).resolve()
            tombstone = Path(item.get('tombstone', '')).resolve()
            digest = item.get('sha256', '')
            if tombstone.parent != target.parent or not re.fullmatch(re.escape('.' + target.name + '.') + r'[0-9a-f]{32}\.delete-pending', tombstone.name) or target.suffix.lower() not in ('.exe', '.jar') or not re.fullmatch(r'[0-9a-f]{64}', digest):
                raise ServiceError('invalid_delete_journal', 'Deletion recovery record is invalid; no files were changed.')
            if not tombstone.exists():
                self.store.finish_delete(str(tombstone))
                continue
            if tombstone.is_symlink() or _sha256(tombstone) != digest:
                raise ServiceError('delete_recovery_required', 'A pending deletion file has changed; recovery was stopped.')
            managed = any(r.get('local_path') == str(target) for r in self.store.downloads())
            try:
                if managed:
                    _rename_exclusive(tombstone, target)
                else:
                    tombstone.unlink()
                self.store.finish_delete(str(tombstone))
            except OSError:
                # Keep the durable journal and preserved bytes for the next run.
                continue

    def _open(self, url, binary=False):
        validate_asset_url(url)
        request = urllib.request.Request(url, headers={'User-Agent': 'PCL-Savior/1', 'Accept': 'application/octet-stream' if binary else 'application/vnd.github+json'})
        try:
            response = self.transport(request, timeout=30)
            if hasattr(response, 'geturl'):
                validate_asset_url(response.geturl())
            return response
        except urllib.error.HTTPError as exc:
            code = 'rate_limited' if exc.code in (403, 429) else 'not_found' if exc.code == 404 else 'network_error'
            raise ServiceError(code, 'GitHub request failed. Open the official page or try again later.') from exc
        except (OSError, urllib.error.URLError) as exc:
            raise ServiceError('network_error', 'Unable to connect to GitHub.') from exc

    def _json(self, url):
        with self._open(url) as response:
            try:
                value = json.loads(response.read(8 * 1024 * 1024 + 1))
            except (ValueError, UnicodeError) as exc:
                raise ServiceError('invalid_response', 'GitHub returned invalid JSON.') from exc
            return value, response.headers

    def releases(self, launcher, page=1, filter='all'):
        if launcher not in REPOSITORIES or type(page) is not int or not 1 <= page <= 10000 or filter not in ('all', 'stable', 'preview', 'local'):
            raise ServiceError('invalid_request', 'Invalid release query.')
        repo = REPOSITORIES[launcher]
        official = 'https://meloong.com/pcl' if launcher == 'PCL' else f'https://github.com/{repo}/releases'
        if filter == 'local':
            return {'items': self._local_items(launcher), 'next_page': None, 'official_url': official}
        data, headers = self._json(f'https://api.github.com/repos/{repo}/releases?per_page=20&page={page}')
        if not isinstance(data, list):
            raise ServiceError('invalid_response', 'GitHub release list is invalid.')
        try:
            latest, _ = self._json(f'https://api.github.com/repos/{repo}/releases/latest')
            latest_tag = latest.get('tag_name')
        except ServiceError as exc:
            if exc.code != 'not_found':
                raise
            latest_tag = None
        items = []
        downloads = self.store.downloads()
        for release in data:
            if release.get('draft') or filter == 'stable' and release.get('prerelease') or filter == 'preview' and not release.get('prerelease'):
                continue
            assets = []
            for asset in release.get('assets', []):
                name = asset.get('name', '')
                lower = name.lower()
                allowed = lower.endswith(('.exe', '.jar')) if launcher == 'HMCL' else lower.endswith('.exe')
                if launcher == 'PCL_CE':
                    allowed = allowed and ('x64' in lower or 'amd64' in lower) and 'arm64' not in lower
                if allowed:
                    item = {'id': asset.get('id'), 'name': name, 'size': asset.get('size', 0), 'url': asset.get('browser_download_url', ''), 'digest': asset.get('digest')}
                    local = next((r for r in downloads if r.get('launcher') == launcher and r.get('tag') == release.get('tag_name') and Path(r.get('local_path', '')).name == name and Path(r.get('local_path', '')).is_file()), None)
                    if local:
                        item.update(local_path=local['local_path'], sha256=self._managed_current_digest(local), original_sha256=local['sha256'])
                    assets.append(item)
            items.append({'tag': release.get('tag_name', ''), 'published_at': release.get('published_at'), 'prerelease': bool(release.get('prerelease')), 'notes': release.get('body') or '', 'url': release.get('html_url', official), 'assets': assets, 'latest': release.get('tag_name') == latest_tag})
        next_page = None
        for entry in headers.get('Link', '').split(','):
            if 'rel="next"' in entry:
                match = re.search(r'<([^>]+)>', entry)
                if match:
                    parsed = urllib.parse.urlsplit(match[1])
                    values = urllib.parse.parse_qs(parsed.query).get('page', [])
                    if parsed.scheme == 'https' and parsed.netloc == 'api.github.com' and parsed.path == f'/repos/{repo}/releases' and values and values[0].isdigit() and int(values[0]) > page:
                        next_page = int(values[0])
        return {'items': items, 'next_page': next_page, 'official_url': official}

    def _local_items(self, launcher):
        return [{'tag': r.get('tag', ''), 'published_at': r.get('published_at'), 'prerelease': r.get('prerelease', False), 'notes': '', 'url': '', 'assets': [{'id': None, 'name': Path(r['local_path']).name, 'size': Path(r['local_path']).stat().st_size, 'url': '', 'digest': 'sha256:' + r['sha256'], 'local_path': r['local_path'], 'sha256': self._managed_current_digest(r), 'original_sha256': r['sha256']}], 'latest': False} for r in self.store.downloads() if r.get('launcher') == launcher and Path(r.get('local_path', '')).is_file()]

    def _managed_current_digest(self, record):
        target = Path(record['local_path'])
        current = _sha256(target)
        original = record['sha256'].lower()
        if current == original:
            return current
        from .common import load_backup_state
        from .launcher import RULES, inspect_launcher
        from .models import PatchError
        for rule, _, _ in RULES:
            try:
                state = load_backup_state(target, rule)
                if state and state.phase == 'installed' and state.original_sha256.lower() == original and state.patched_sha256.lower() == current and Path(state.backup).is_file() and _sha256(state.backup) == original:
                    inspection = inspect_launcher(target)
                    if getattr(inspection.status, 'value', inspection.status) == 'patched' and inspection.rule_id == rule:
                        return current
            except (OSError, PatchError):
                continue
        # Preserve the expected original hash, so the UI cannot authorize an
        # arbitrary local modification merely by refreshing the catalogue.
        return original

    def download(self, launcher, tag, asset, directory, cancel_file=None, progress=None):
        if launcher not in REPOSITORIES or not isinstance(asset, dict) or not isinstance(tag, str):
            raise ServiceError('invalid_request', 'Invalid download request.')
        name = asset.get('name', '')
        if not isinstance(name, str) or not name or name != Path(name).name or re.search(r'[<>:"/\\|?*\x00-\x1f]', name) or name.endswith(('.', ' ')) or name.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}:
            raise ServiceError('invalid_path', 'Invalid download filename.')
        if not name.lower().endswith(('.exe', '.jar')):
            raise ServiceError('invalid_asset', 'Asset must be a launcher executable or JAR.')
        url = validate_asset_url(asset.get('url'))
        size = asset.get('size')
        if type(size) is not int or size < 0:
            raise ServiceError('invalid_asset', 'Invalid asset size.')
        digest = asset.get('digest')
        if digest and (not isinstance(digest, str) or not re.fullmatch(r'sha256:[0-9a-fA-F]{64}', digest)):
            raise ServiceError('invalid_digest', 'Unsupported official asset digest.')
        if not isinstance(directory, str):
            raise ServiceError('invalid_path', 'Download directory must be text.')
        if not directory.strip():
            directory = self.store.get()['download_directory']
        if not directory.strip():
            directory = str(Path.home() / 'Downloads' / 'PCL Savior')
        destination = Path(directory).expanduser().resolve()
        destination.mkdir(parents=True, exist_ok=True)
        target = destination / name
        partial = destination / ('.' + Path(name).stem + '.part' + Path(name).suffix)
        if target.exists() or partial.exists():
            raise ServiceError('already_exists', 'Download destination already exists.')
        def check_cancel():
            if cancel_file and Path(cancel_file).exists():
                raise ServiceError('cancelled', 'Download cancelled.')
        created = False
        try:
            check_cancel()
            with self._open(url, True) as response, partial.open('xb') as output:
                created = True
                received = 0
                hasher = hashlib.sha256()
                while True:
                    check_cancel()
                    chunk = response.read(128 * 1024)
                    if not chunk:
                        break
                    received += len(chunk)
                    if received > size:
                        raise ServiceError('size_mismatch', 'Downloaded file exceeds official size.')
                    output.write(chunk)
                    hasher.update(chunk)
                    if progress:
                        progress({'received': received, 'total': size, 'percent': round(received * 100 / size, 1) if size else 0})
                output.flush()
                os.fsync(output.fileno())
            if received != size:
                raise ServiceError('size_mismatch', 'Downloaded file size differs from official size.')
            actual = hasher.hexdigest()
            if digest and actual != digest.split(':')[1].lower():
                raise ServiceError('digest_mismatch', 'Downloaded file failed its official SHA-256 check.')
            from .launcher import inspect_launcher
            from .protocol import inspection_data
            inspection = inspection_data(inspect_launcher(partial))
            known_names = {'PCL': {'PCL', 'PCL2'}, 'HMCL': {'HMCL'}, 'PCL_CE': {'PCL-CE', 'PCL CE', 'PCL_CE', 'PCL2 CE'}}
            if inspection.get('launcher_name') not in known_names[launcher]:
                raise ServiceError('unrecognized_launcher', 'Downloaded file is not a recognized launcher.')
            check_cancel()
            # Windows rename fails when the destination exists. POSIX rename
            # replaces, so use an exclusive hard link on that platform.
            _rename_exclusive(partial, target)
            record = {'local_path': str(target), 'sha256': actual, 'launcher': launcher, 'tag': tag}
            try:
                self.store.record_download(record)
            except Exception:
                target.unlink()
                raise
            return {'path': str(target), 'sha256': actual, 'inspection': inspection}
        finally:
            if created and partial.exists():
                partial.unlink()

    def delete(self, path, expected_sha256):
        target = Path(path).resolve()
        record = next((r for r in self.store.downloads() if r.get('local_path') == str(target)), None)
        if not record or not isinstance(expected_sha256, str) or not re.fullmatch('[0-9a-fA-F]{64}', expected_sha256):
            raise ServiceError('unmanaged_file', 'Only a recorded download with a matching SHA-256 may be deleted.')
        if any(part.lower() in ('.minecraft', 'backup', 'backups') for part in target.parts) or target.suffix.lower() not in ('.exe', '.jar'):
            raise ServiceError('protected_path', 'This path is protected.')
        if target.is_symlink() or not target.is_file() or self._managed_current_digest(record) != expected_sha256.lower() or _sha256(target) != expected_sha256.lower():
            raise ServiceError('file_changed', 'Downloaded file is missing or has changed.')
        tombstone = target.with_name('.' + target.name + '.' + uuid.uuid4().hex + '.delete-pending')
        self.store.begin_delete({'target': str(target), 'tombstone': str(tombstone), 'sha256': expected_sha256.lower()})
        try:
            _rename_exclusive(target, tombstone)
            if _sha256(tombstone) != expected_sha256.lower():
                raise ServiceError('file_changed', 'Downloaded file changed during deletion.')
            self.store.remove_download(str(target))
        except Exception:
            if tombstone.exists():
                try:
                    _rename_exclusive(tombstone, target)
                except OSError as exc:
                    raise ServiceError('delete_recovery_required', 'Deletion was stopped. The original file is preserved at ' + str(tombstone) + '; the current destination was not overwritten.') from exc
            self.store.finish_delete(str(tombstone))
            raise
        pending = False
        try:
            tombstone.unlink()
            self.store.finish_delete(str(tombstone))
        except (OSError, ServiceError):
            pending = True
        return {'deleted': True, 'path': str(target), 'cleanup_pending': pending, 'recovery_path': str(tombstone) if pending else None}

    def update(self, repo, current_version):
        if not repo:
            return {'configured': False, 'update_available': False}
        if not isinstance(repo, str) or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo):
            raise ServiceError('invalid_repository', 'Update repository must be owner/name.')
        _semver(current_version)
        latest, _ = self._json(f'https://api.github.com/repos/{repo}/releases/latest')
        return {'configured': True, 'update_available': version_is_newer(latest.get('tag_name', ''), current_version), 'version': latest.get('tag_name'), 'url': latest.get('html_url'), 'notes': latest.get('body') or ''}
