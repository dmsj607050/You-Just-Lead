/**
 * 托管后端连接配置。
 *
 * 换地址或换令牌只改这个文件，其他代码不受影响。
 */

/**
 * 云端 API 根地址。账号、项目与积分都通过该 HTTPS 服务访问。
 */
export const BASE_URL: string = 'https://nucrobot.online/yjl-cloud';

/**
 * 本地/局域网旧接口令牌。托管云端使用用户登录后取得的 Bearer 会话令牌，不在此写入共享密钥。
 */
export const ACCESS_TOKEN: string = '';

/** 连接超时（毫秒）。 */
export const CONNECT_TIMEOUT_MS: number = 5000;

/** 读取超时（毫秒）。 */
export const READ_TIMEOUT_MS: number = 15000;

/** Agent 问答的超时（毫秒）。Agent 会做多轮工具调用，需要给足时间。 */
export const AGENT_TIMEOUT_MS: number = 180000;
