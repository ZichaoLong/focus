import preferences from '@ohos.data.preferences';
import { asset } from '@kit.AssetStoreKit';
import { url, util } from '@kit.ArkTS';
import { common } from '@kit.AbilityKit';
import { BusinessError } from '@kit.BasicServicesKit';
import { webview } from '@kit.ArkWeb';

export class Site {
  id: string = '';
  name: string = '';
  origin: string = '';
  sso: boolean = false;
}

export class Login {
  origin: string = '';
  realm: string = '';
  user: string = '';
  password: string = '';
}

export function siteOrigin(address: string): string {
  const parsed = new url.URL(address);
  const local = parsed.protocol === 'http:' && ['127.0.0.1', 'localhost', '[::1]'].includes(parsed.hostname);
  if ((!local && parsed.protocol !== 'https:') || !parsed.hostname || parsed.username || parsed.password) {
    throw new Error('远程入口需要 HTTPS；HTTP 仅支持本机回环地址');
  }
  return parsed.origin;
}

export function focusRoot(address: string, origin: string): boolean {
  try { return siteOrigin(address) === origin && new url.URL(address).pathname === '/'; }
  catch { return false; }
}

export function httpsOrigin(address: string): string {
  try {
    const origin = siteOrigin(address);
    return origin.startsWith('https://') ? origin : '';
  } catch { return ''; }
}

export function sitePrefs(context: common.UIAbilityContext): preferences.Preferences {
  return preferences.getPreferencesSync(context, { name: 'instances' });
}

function key(id: string): asset.AssetMap {
  const map: asset.AssetMap = new Map();
  map.set(asset.Tag.ALIAS, new util.TextEncoder().encodeInto('focus.basic.' + id));
  return map;
}

export async function savedLogin(site: Site, realm: string): Promise<Login | undefined> {
  const query = key(site.id);
  query.set(asset.Tag.RETURN_TYPE, asset.ReturnType.ALL);
  try {
    const rows = await asset.query(query);
    if (!rows.length) return undefined;
    const text = util.TextDecoder.create('utf-8').decodeToString(rows[0].get(asset.Tag.SECRET) as Uint8Array);
    const entry = JSON.parse(text) as Login;
    return entry.realm === realm && entry.origin === site.origin ? entry : undefined;
  } catch (err) {
    if ((err as BusinessError).code === asset.ErrorCode.NOT_FOUND) return undefined;
    throw new Error((err as BusinessError).message);
  }
}

export async function rememberLogin(site: Site, login: Login): Promise<void> {
  const record = key(site.id);
  record.set(asset.Tag.ACCESSIBILITY, asset.Accessibility.DEVICE_UNLOCKED);
  record.set(asset.Tag.CONFLICT_RESOLUTION, asset.ConflictResolution.OVERWRITE);
  record.set(asset.Tag.SECRET, new util.TextEncoder().encodeInto(JSON.stringify(login)));
  await asset.add(record);
}

export async function forgetLogin(site: Site): Promise<void> {
  try { await asset.remove(key(site.id)); }
  catch (err) {
    if ((err as BusinessError).code !== asset.ErrorCode.NOT_FOUND) throw new Error((err as BusinessError).message);
  }
}

export async function forgetSite(context: common.UIAbilityContext, site: Site): Promise<void> {
  await forgetLogin(site);
  const prefs = sitePrefs(context);
  prefs.deleteSync('thread.' + site.id);
  await prefs.flush();
  webview.WebStorage.deleteOrigin(site.origin);
  // Host-only root cookies, including HttpOnly Focus sessions. Cookie names are
  // enumerated to expire them; values never cross into preferences or the bridge.
  for (const cookie of webview.WebCookieManager.fetchCookieSync(site.origin + '/').split(';')) {
    const name = cookie.split('=')[0].trim();
    if (name) webview.WebCookieManager.configCookieSync(site.origin + '/', name + '=; Path=/; Max-Age=0; HttpOnly' + (site.origin.startsWith('https://') ? '; Secure' : ''));
  }
}

export function basicRealm(header: string): string | undefined {
  const match = /^Basic\s+realm=(?:"((?:[^"\\]|\\.)*)"|([^\s,]+))(?:\s*,\s*charset="?UTF-8"?)?\s*$/i.exec(header.trim());
  if (!match) return undefined;
  const realm = match[1] === undefined ? match[2] : match[1].replace(/\\(.)/g, '$1');
  return realm.length <= 512 ? realm : undefined;
}
