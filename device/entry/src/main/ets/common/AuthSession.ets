import { common } from '@kit.AbilityKit';
import { preferences } from '@kit.ArkData';
import { clearSessionToken, setSessionToken } from './BackendClient';

const STORE_NAME: string = 'youjustlead_auth';
const TOKEN_KEY: string = 'session_token';

/** 启动时恢复服务端会话令牌；密码始终不保存。 */
export async function restoreSession(context: common.UIAbilityContext): Promise<string> {
  try {
    const store: preferences.Preferences = await preferences.getPreferences(context, STORE_NAME);
    const saved: preferences.ValueType = await store.get(TOKEN_KEY, '');
    const token: string = typeof saved === 'string' ? saved : '';
    setSessionToken(token);
    return token;
  } catch (error) {
    clearSessionToken();
    return '';
  }
}

/** 会话令牌保存在应用私有偏好中，供下次启动恢复。 */
export async function persistSession(context: common.UIAbilityContext, token: string): Promise<void> {
  try {
    const store: preferences.Preferences = await preferences.getPreferences(context, STORE_NAME);
    await store.put(TOKEN_KEY, token);
    await store.flush();
  } catch (error) {
    const reason = error as Error;
    throw new Error(`无法保存登录状态：${reason.message}`);
  }
}

/** 登出时同时删除服务端会话与本地缓存。 */
export async function forgetSession(context: common.UIAbilityContext): Promise<void> {
  clearSessionToken();
  try {
    const store: preferences.Preferences = await preferences.getPreferences(context, STORE_NAME);
    await store.delete(TOKEN_KEY);
    await store.flush();
  } catch (error) {
    // 本地删除失败不应重新把已撤销的服务端令牌放回内存。
  }
}
