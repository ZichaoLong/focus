// Runs only in the site's own management document. No chat bootstrap, writer hint or socket.
import { FOCUS_WEB_ENDPOINTS, type FocusWebEndpointName } from './focusWire.generated';
import {
  decodeFocusDocumentRegistration, decodeFocusUpdateInstallation, decodeFocusUpdatePreparation,
  decodeFocusUpdateStatus, type FocusHttpDecoder,
} from './httpResponseDecoder';

const managementHint = 'focus-mobile.update-client.v1';
const identityHeaders: Record<string, string> = {};

async function request<T>(name: FocusWebEndpointName, decode: FocusHttpDecoder<T>, body?: object, scope?: string): Promise<T> {
  const endpoint = FOCUS_WEB_ENDPOINTS[name];
  const response = await fetch(endpoint.path, {
    method: endpoint.method, credentials: 'same-origin', redirect: 'error', cache: 'no-store',
    headers: body ? { ...identityHeaders, 'Content-Type': 'application/json', ...(scope ? {'X-Focus-Mobile-Records':'1'} : {}) } : identityHeaders,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (response.status === 401 || response.status === 403) throw Object.assign(new Error('请打开此实例完成登录或授权'), { needsEntry: true });
  if (response.status === 404) throw Object.assign(new Error('此服务端未提供批量管理，请在实例设置中查看服务端更新'), { needsEntry: true });
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    const error = new Error(String(detail?.error?.message || `HTTP ${response.status}`).slice(0, 300));
    throw Object.assign(error, {
      rejected: ['update_unavailable', 'invalid_update_preparation'].includes(detail?.error?.code),
      scopeChanged: detail?.error?.code === 'record_scope_changed',
    });
  }
  if (scope && response.headers.get('X-Focus-Mobile-Record-Scope') !== scope)
    throw Object.assign(new Error('离线记录的授权范围已变化'), {scopeChanged: !!response.headers.get('X-Focus-Mobile-Record-Scope')});
  const result = decode(await response.json());
  if (!result) throw new Error('无法验证服务端更新响应');
  return result;
}

export async function runMobileServerUpdate(action: string, body: Record<string, string>) {
  const checking = action === 'record-status';
  const hintKey = checking ? 'focus-mobile.record-check.v1' : managementHint;
  let hint = '';
  try { hint = localStorage.getItem(hintKey) || ''; } catch { /* Optional hint. */ }
  const registration = await request('client_register', decodeFocusDocumentRegistration, {
    resume_client_id: hint, incarnation_id: crypto.randomUUID(),
  }, checking ? body.scope : undefined);
  try { localStorage.setItem(hintKey, registration.client_id); } catch { /* Optional hint. */ }
  identityHeaders['X-Focus-Web-Client'] = registration.client_id;
  identityHeaders['X-Focus-Web-Document'] = registration.document_token;
  identityHeaders['X-Focus-Web-Csrf'] = registration.csrf_token;
  if (checking) {
    const threads: string[] = JSON.parse(body.threads || '[]');
    return request('mobile_record_status', value => {
      const data = value as {scope?: unknown; states?: unknown} | null;
      return data && data.scope === body.scope && Array.isArray(data.states) && data.states.length === threads.length
        && data.states.every(s => ['present','missing','archived','unknown'].includes(s)) ? data : null;
    }, {scope:body.scope,threads});
  }
  if (action === 'status') return request('update_installation', decodeFocusUpdateInstallation);
  if (action === 'prepare') return request('update_prepare_latest', decodeFocusUpdatePreparation, body);
  if (action === 'apply') {
    const before = await request('update_installation', decodeFocusUpdateInstallation);
    if (before.installation_id !== body.installation_id || before.operation.state !== 'ready'
        || before.operation.operation_id !== body.operation_id) throw new Error('已确认的准备记录已更换，请重新检查');
    await request('update_apply', decodeFocusUpdateStatus, { operation_id: body.operation_id, confirmation: body.operation_id });
    return request('update_installation', decodeFocusUpdateInstallation);
  }
  throw new Error('此版本不支持该操作');
}

Object.assign(window, {
  focusUpdateAgent(id: string, action: string, body: Record<string, string>) {
    const reply = (value: object) => Object.assign(window, {focusUpdateReply: JSON.stringify({id, ...value})});
    void runMobileServerUpdate(action, body).then(data => reply({ data }), error => reply({ error: String(error.message || error), needs_entry: error.needsEntry === true, rejected: error.rejected === true, scope_changed: error.scopeChanged === true }));
    return true;
  },
});
