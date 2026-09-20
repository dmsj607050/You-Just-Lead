/**
 * 本地后端连接配置。
 *
 * 换地址或换令牌只改这个文件，其他代码不受影响。
 */

/**
 * 后端根地址。
 *
 * 默认走回环地址，适用于 HAP 与后端在同一台机器上运行的情况。
 * 若通过 hdc 端口转发把设备端口映射到主机，这里同样保持回环地址不变。
 */
export const BASE_URL: string = 'http://127.0.0.1:8765';

/**
 * 共享令牌，需与后端启动时的 YJL_API_TOKEN 一致。
 *
 * 后端绑定回环地址时不校验令牌，保持空字符串即可。
 * 仅当改用局域网地址访问（后端以 --host 0.0.0.0 启动）时，才需要在本机填写自己的令牌；
 * 该值属于本地调试凭据，请勿提交到版本库。
 */
export const ACCESS_TOKEN: string = '';

/** 连接超时（毫秒）。 */
export const CONNECT_TIMEOUT_MS: number = 5000;

/** 读取超时（毫秒）。 */
export const READ_TIMEOUT_MS: number = 15000;

/** Agent 问答的超时（毫秒）。Agent 会做多轮工具调用，需要给足时间。 */
export const AGENT_TIMEOUT_MS: number = 180000;
