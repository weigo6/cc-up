// Optional static-site configuration. A published key is readable by every visitor.
import {rmSync, writeFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import {validateEndpoint} from '../frontend/assets/core.mjs';

export function buildWebConfig(env=process.env, target=new URL('../frontend/config.json', import.meta.url), log=console.log) {
  const endpoint=(env.CC_UP_ENDPOINT || '').trim();
  const token=(env.CC_UP_TOKEN || '').trim();
  // Remove previous build output before validation, including when variables are removed.
  rmSync(target, {force:true});
  if (!endpoint && !token) {
    log('未设置 CC_UP_ENDPOINT / CC_UP_TOKEN，网页将保留手动连接入口。');
    return null;
  }
  if (!endpoint) throw new Error('已设置 CC_UP_TOKEN，但缺少 CC_UP_ENDPOINT。');
  if (!token) throw new Error('已设置 CC_UP_ENDPOINT，但缺少 CC_UP_TOKEN。');
  const origin=validateEndpoint(endpoint);
  if (!/^[A-Za-z0-9_-]{32,128}$/.test(token)) {
    throw new Error('CC_UP_TOKEN 须为 32～128 位字母、数字、下划线或短横线。');
  }
  const config={endpoint:origin, token};
  writeFileSync(target, JSON.stringify(config, null, 2)+'\n', 'utf8');
  log('已生成 frontend/config.json。该文件随站点公开，请仅使用 VIEWER_TOKENS 中的只读密钥；访问者能读取全部用量和请求详情。');
  return config;
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  try { buildWebConfig(); }
  catch (error) {
    console.error('config.json 生成失败：'+error.message);
    process.exitCode=1;
  }
}
