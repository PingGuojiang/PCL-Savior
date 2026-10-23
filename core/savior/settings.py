"""Small atomic per-user settings and managed-download registry."""
import json
import os
import tempfile
from pathlib import Path

from .github_service import ServiceError


class SettingsStore:
    def __init__(self, root=None):
        self.root = Path(root) if root else Path(os.environ.get('APPDATA', Path.home() / 'AppData' / 'Roaming')) / 'PCL Savior'

    def _read(self, name, default):
        path = self.root / name
        if not path.exists():
            return default
        try:
            value = json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(value, type(default)):
                raise ValueError('wrong structure')
            return value
        except (OSError, ValueError) as exc:
            raise ServiceError('settings_read', 'Unable to read local settings or download registry.') from exc

    def _write(self, name, value):
        temporary = None
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.root, prefix=name + '.', suffix='.tmp', delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(value, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.root / name)
        except OSError as exc:
            raise ServiceError('settings_write', 'Unable to save local settings or download registry.') from exc
        finally:
            if temporary and temporary.exists():
                temporary.unlink()

    def get(self):
        defaults = {'theme': 'system', 'paths': {'PCL': '', 'HMCL': '', 'PCL_CE': ''}, 'download_directory': str(Path.home() / 'Downloads' / 'PCL Savior'), 'update_repo': ''}
        saved = self._read('settings.json', {})
        defaults.update(saved)
        self._validate(defaults)
        return defaults

    def _validate(self, value):
        if value.get('theme') not in ('system', 'light', 'dark'):
            raise ServiceError('invalid_settings', 'Unknown theme.')
        paths = value.get('paths')
        if not isinstance(paths, dict) or set(paths) != {'PCL', 'HMCL', 'PCL_CE'} or any(not isinstance(p, str) for p in paths.values()):
            raise ServiceError('invalid_settings', 'Launcher paths must be text.')
        if not isinstance(value.get('download_directory'), str) or not isinstance(value.get('update_repo'), str):
            raise ServiceError('invalid_settings', 'Settings paths and repository must be text.')

    def save(self, changes):
        if not isinstance(changes, dict) or set(changes) - {'theme', 'paths', 'download_directory', 'update_repo'}:
            raise ServiceError('invalid_settings', 'Unknown settings fields.')
        value = self.get()
        value.update(changes)
        self._validate(value)
        self._write('settings.json', value)
        return value

    def downloads(self):
        return self._read('downloads.json', [])

    def record_download(self, item):
        records = [r for r in self.downloads() if r.get('local_path') != item['local_path']]
        records.append(item)
        self._write('downloads.json', records)

    def remove_download(self, path):
        self._write('downloads.json', [r for r in self.downloads() if r.get('local_path') != path])

    def pending_deletions(self):
        return self._read('deletions.json', [])

    def begin_delete(self, item):
        self._write('deletions.json', self.pending_deletions() + [item])

    def finish_delete(self, tombstone):
        self._write('deletions.json', [item for item in self.pending_deletions() if item.get('tombstone') != tombstone])
