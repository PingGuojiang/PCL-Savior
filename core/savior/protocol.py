"""One request per hidden worker; stdout is exclusively UTF-8 JSON Lines."""
import dataclasses
import enum
import json
import sys
from pathlib import Path

from .github_service import GitHubService, ServiceError
from .settings import SettingsStore
from .models import PatchError


def _plain(value):
    if dataclasses.is_dataclass(value):
        return {field.name: _plain(getattr(value, field.name)) for field in dataclasses.fields(value) if field.name not in ('edits', 'raw_edits', 'patches')}
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items() if key not in ('edits', 'raw_edits', 'patches')}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def inspection_data(value):
    result = _plain(value)
    if not isinstance(result, dict):
        raise ServiceError('invalid_inspection', 'Launcher inspection returned an invalid result.')
    fields = ('launcher_name', 'file_version', 'assembly_version', 'sha256', 'size', 'status', 'message', 'rule_id', 'backup_available')
    if isinstance(result.get('status'), str):
        result['status'] = result['status'].upper()
    return {field: result.get(field, False if field == 'backup_available' else None) for field in fields}


def dispatch(request, progress, store=None):
    command = request['command']
    service = GitHubService(store or SettingsStore())
    if command in ('inspect', 'patch', 'restore'):
        from .launcher import inspect_launcher, apply_launcher_patch, restore_launcher_backup
        path = request.get('path')
        if not isinstance(path, str) or not path:
            raise ServiceError('invalid_path', 'A launcher path is required.')
        if command == 'inspect':
            return inspection_data(inspect_launcher(path))
        operation = apply_launcher_patch if command == 'patch' else restore_launcher_backup
        return inspection_data(operation(path, expected_sha256=request.get('expected_sha256')))
    if command == 'releases':
        return service.releases(request.get('launcher'), request.get('page', 1), request.get('filter', 'all'))
    if command == 'download':
        return service.download(request.get('launcher'), request.get('tag'), request.get('asset'), request.get('directory'), request.get('cancel_file'), progress)
    if command == 'delete':
        return service.delete(request.get('path'), request.get('expected_sha256'))
    if command == 'settings':
        action = request.get('action', 'get')
        if action == 'get':
            return service.store.get()
        if action == 'save':
            return service.store.save(request.get('preferences', request.get('values', request.get('settings'))))
        raise ServiceError('invalid_request', 'Unknown settings action.')
    if command == 'update':
        return service.update(request.get('repo', service.store.get()['update_repo']), request.get('current_version', '0.0.0'))
    raise ServiceError('unknown_command', 'Unknown worker command.')


def serve(source=None, destination=None):
    source = source or sys.stdin
    destination = destination or sys.stdout
    request_id = ''
    def emit(kind, data):
        destination.write(json.dumps({'protocol': 1, 'id': request_id, 'type': kind, 'data': _plain(data)}, ensure_ascii=False, allow_nan=False) + '\n')
        destination.flush()
    try:
        line = source.readline(1024 * 1024 + 1)
        if not line or len(line) > 1024 * 1024:
            raise ServiceError('invalid_request', 'Request is empty or too large.')
        request = json.loads(line)
        if isinstance(request, dict) and isinstance(request.get('id'), str):
            request_id = request['id'][:200]
        if not isinstance(request, dict) or type(request.get('protocol')) is not int or request.get('protocol') != 1 or not isinstance(request.get('id'), str) or not request['id'] or len(request['id']) > 200 or not isinstance(request.get('command'), str):
            raise ServiceError('invalid_request', 'Unsupported protocol or invalid request envelope.')
        result = dispatch(request, lambda data: emit('progress', data))
        emit('result', result)
        return 0
    except ServiceError as exc:
        emit('error', {'code': exc.code, 'message': exc.message})
    except PatchError as exc:
        emit('error', {'code': 'patch_failed', 'message': str(exc)})
    except (ValueError, TypeError, KeyError):
        emit('error', {'code': 'invalid_request', 'message': 'Request or service response is invalid.'})
    except Exception as exc:
        # Exception text can contain signed download URLs; never echo it.
        print('Worker failure: ' + type(exc).__name__, file=sys.stderr)
        code = getattr(exc, 'code', 'operation_failed')
        emit('error', {'code': str(getattr(code, 'value', code)), 'message': 'The operation could not be completed. Check the launcher path and try again.'})
    return 1
