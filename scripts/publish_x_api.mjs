#!/usr/bin/env node
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const DEFAULT_OUTPUT_DIR = path.join(ROOT, "x-drafts");
const DEFAULT_TOKEN_PATH = path.join(os.homedir(), ".hermes", "x-api-token.json");

function usage() {
  return [
    "Usage: node scripts/publish_x_api.mjs --date YYYY-MM-DD [options]",
    "",
    "Options:",
    "  --date YYYY-MM-DD       Daily brief date to publish.",
    "  --output-dir PATH       Draft output root. Defaults to x-drafts.",
    "  --token-path PATH       X API token path. Defaults to ~/.hermes/x-api-token.json.",
    "  --dry-run               Validate credentials and files, but do not upload or post.",
    "  --help                  Show this help.",
  ].join("\n");
}

function parseArgs(argv) {
  const args = {
    date: "",
    outputDir: DEFAULT_OUTPUT_DIR,
    tokenPath: process.env.X_TOKEN_PATH || DEFAULT_TOKEN_PATH,
    dryRun: false,
  };

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === "--help" || arg === "-h") {
      console.log(usage());
      process.exit(0);
    }
    if (arg === "--date") {
      args.date = argv[++index] || "";
    } else if (arg === "--output-dir") {
      args.outputDir = argv[++index] || "";
    } else if (arg === "--token-path") {
      args.tokenPath = argv[++index] || "";
    } else if (arg === "--dry-run") {
      args.dryRun = true;
    } else {
      throw new Error(`不支持的参数：${arg}`);
    }
  }

  if (!args.date) {
    throw new Error("X API 发布失败：缺少 --date。");
  }
  return args;
}

async function loadDotEnv() {
  const envPath = path.join(ROOT, ".env");
  let text = "";
  try {
    text = await fs.readFile(envPath, "utf8");
  } catch {
    return;
  }
  for (const line of text.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#") || !trimmed.includes("=")) continue;
    const index = trimmed.indexOf("=");
    const key = trimmed.slice(0, index).trim();
    const value = trimmed.slice(index + 1).trim().replace(/^['"]|['"]$/g, "");
    if (!(key in process.env)) process.env[key] = value;
  }
}

async function readDraft(args) {
  const draftDir = path.join(args.outputDir, `${args.date}-kami-x`);
  const cardsDir = path.join(draftDir, "cards");
  const postPath = path.join(draftDir, "post.md");

  const names = await fs.readdir(cardsDir);
  const cards = names
    .filter((name) => name.endsWith(".png"))
    .sort()
    .map((name) => path.join(cardsDir, name));
  if (cards.length === 0) {
    throw new Error(`X API 发布失败：没有找到图片 ${cardsDir}`);
  }
  if (cards.length > 4) {
    throw new Error(`X API 发布失败：单条 Post 最多 4 张图片，当前有 ${cards.length} 张。`);
  }

  for (const card of cards) {
    const stat = await fs.stat(card);
    if (stat.size > 5 * 1024 * 1024) {
      throw new Error(`X API 发布失败：图片超过 5 MB：${card}`);
    }
  }

  const body = (await fs.readFile(postPath, "utf8")).trim();
  if (!body) {
    throw new Error(`X API 发布失败：正文为空 ${postPath}`);
  }
  return { draftDir, cards, body };
}

async function readToken(tokenPath) {
  try {
    return JSON.parse(await fs.readFile(tokenPath, "utf8"));
  } catch {
    throw new Error(`X API 发布失败：没有 token。请先运行 node scripts/x_api_auth.mjs 进行授权。`);
  }
}

async function writeToken(tokenPath, token) {
  await fs.mkdir(path.dirname(tokenPath), { recursive: true });
  await fs.writeFile(tokenPath, JSON.stringify(token, null, 2), { encoding: "utf8", mode: 0o600 });
  await fs.chmod(tokenPath, 0o600).catch(() => {});
}

async function refreshTokenIfNeeded(tokenPath, token) {
  if (Number(token.expires_at || 0) > Date.now() + 120000) return token;
  if (!token.refresh_token) {
    throw new Error("X API 发布失败：access token 已过期且没有 refresh token，请重新运行授权脚本。");
  }

  const clientId = process.env.X_CLIENT_ID || token.client_id;
  const clientSecret = process.env.X_CLIENT_SECRET || "";
  if (!clientId) {
    throw new Error("X API 发布失败：刷新 token 需要 X_CLIENT_ID。");
  }

  const body = new URLSearchParams({
    refresh_token: token.refresh_token,
    grant_type: "refresh_token",
  });
  const headers = { "Content-Type": "application/x-www-form-urlencoded" };
  if (clientSecret) {
    headers.Authorization = `Basic ${Buffer.from(`${clientId}:${clientSecret}`).toString("base64")}`;
  } else {
    body.set("client_id", clientId);
  }

  const response = await fetch("https://api.x.com/2/oauth2/token", {
    method: "POST",
    headers,
    body,
  });
  const json = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(`X API 发布失败：刷新 token ${response.status} ${JSON.stringify(json)}`);
  }

  const next = {
    ...token,
    token_type: json.token_type,
    access_token: json.access_token,
    refresh_token: json.refresh_token || token.refresh_token,
    scope: json.scope || token.scope,
    expires_at: Date.now() + Number(json.expires_in || 7200) * 1000,
  };
  await writeToken(tokenPath, next);
  return next;
}

async function apiFetch(url, { token, method = "GET", headers = {}, body } = {}) {
  const response = await fetch(url, {
    method,
    headers: {
      Authorization: `Bearer ${token.access_token}`,
      ...headers,
    },
    body,
  });
  const text = await response.text();
  const json = text ? JSON.parse(text) : {};
  if (!response.ok) {
    if (response.status === 402 && json.title === "CreditsDepleted") {
      throw new Error(
        "X API 发布失败：开发者账户 credits 已用尽。请在 X Developer Console 充值 API credits 后重试同一条命令。",
      );
    }
    throw new Error(`X API ${method} ${url} failed: ${response.status} ${JSON.stringify(json)}`);
  }
  return json;
}

async function validateToken(token) {
  return apiFetch("https://api.x.com/2/users/me", { token });
}

async function uploadImage(token, filePath) {
  const data = await fs.readFile(filePath);
  const form = new FormData();
  form.append("media", new Blob([data], { type: "image/png" }), path.basename(filePath));
  form.append("media_category", "tweet_image");
  form.append("media_type", "image/png");

  const json = await apiFetch("https://api.x.com/2/media/upload", {
    token,
    method: "POST",
    body: form,
  });
  const id = json.data?.id || json.data?.media_id_string || json.media_id_string;
  if (!id) {
    throw new Error(`X API 发布失败：上传图片没有返回 media id：${JSON.stringify(json)}`);
  }
  return String(id);
}

async function createPost(token, text, mediaIds) {
  return apiFetch("https://api.x.com/2/tweets", {
    token,
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      text,
      media: { media_ids: mediaIds },
    }),
  });
}

async function main() {
  await loadDotEnv();
  const args = parseArgs(process.argv.slice(2));
  const draft = await readDraft(args);
  let token = await readToken(args.tokenPath);
  token = await refreshTokenIfNeeded(args.tokenPath, token);
  const user = await validateToken(token);

  if (args.dryRun) {
    console.log(`X API 待发布：@${user.data?.username || "unknown"}，${draft.cards.length} 张。`);
    return;
  }

  const mediaIds = [];
  for (const card of draft.cards) {
    mediaIds.push(await uploadImage(token, card));
  }
  const post = await createPost(token, draft.body, mediaIds);
  const id = post.data?.id;
  const username = user.data?.username;
  const url = id && username ? `https://x.com/${username}/status/${id}` : "";
  console.log(`X API 已发布：${id || JSON.stringify(post.data)}${url ? ` ${url}` : ""}`);
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(1);
});
