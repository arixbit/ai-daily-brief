#!/usr/bin/env node
import fs from "node:fs/promises";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";
import { createHash, randomBytes } from "node:crypto";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const DEFAULT_REDIRECT_URI = "http://127.0.0.1:8787/callback";
const DEFAULT_TOKEN_PATH = path.join(os.homedir(), ".hermes", "x-api-token.json");
const SCOPES = ["tweet.read", "tweet.write", "users.read", "media.write", "offline.access"];

function usage() {
  return [
    "Usage: node scripts/x_api_auth.mjs [options]",
    "",
    "Options:",
    "  --redirect-uri URL      OAuth callback URL. Defaults to http://127.0.0.1:8787/callback.",
    "  --token-path PATH       Token output path. Defaults to ~/.hermes/x-api-token.json.",
    "  --no-open               Print the auth URL without opening a browser.",
    "  --help                  Show this help.",
  ].join("\n");
}

function parseArgs(argv) {
  const args = {
    redirectUri: process.env.X_REDIRECT_URI || DEFAULT_REDIRECT_URI,
    tokenPath: process.env.X_TOKEN_PATH || DEFAULT_TOKEN_PATH,
    openBrowser: true,
  };

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === "--help" || arg === "-h") {
      console.log(usage());
      process.exit(0);
    }
    if (arg === "--redirect-uri") {
      args.redirectUri = argv[++index] || "";
    } else if (arg === "--token-path") {
      args.tokenPath = argv[++index] || "";
    } else if (arg === "--no-open") {
      args.openBrowser = false;
    } else {
      throw new Error(`不支持的参数：${arg}`);
    }
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

function base64Url(buffer) {
  return Buffer.from(buffer).toString("base64").replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

function pkceChallenge(verifier) {
  return base64Url(createHash("sha256").update(verifier).digest());
}

function openUrl(url) {
  const command = process.platform === "darwin" ? "open" : process.platform === "win32" ? "cmd" : "xdg-open";
  const args = process.platform === "win32" ? ["/c", "start", "", url] : [url];
  const child = spawn(command, args, { stdio: "ignore", detached: true });
  child.unref();
}

function listenForCode(redirectUri, expectedState) {
  const parsed = new URL(redirectUri);
  if (!["127.0.0.1", "localhost"].includes(parsed.hostname)) {
    throw new Error("X 授权失败：redirect URI 必须指向 127.0.0.1 或 localhost，方便本地接收授权码。");
  }

  return new Promise((resolve, reject) => {
    const server = http.createServer((req, res) => {
      const requestUrl = new URL(req.url || "/", redirectUri);
      if (requestUrl.pathname !== parsed.pathname) {
        res.writeHead(404);
        res.end("Not found");
        return;
      }

      const error = requestUrl.searchParams.get("error");
      const code = requestUrl.searchParams.get("code");
      const state = requestUrl.searchParams.get("state");

      if (error) {
        res.writeHead(400, { "Content-Type": "text/plain; charset=utf-8" });
        res.end(`X authorization failed: ${error}`);
        server.close();
        reject(new Error(`X 授权失败：${error}`));
        return;
      }

      if (!code || state !== expectedState) {
        res.writeHead(400, { "Content-Type": "text/plain; charset=utf-8" });
        res.end("Invalid OAuth callback.");
        server.close();
        reject(new Error("X 授权失败：回调缺少 code 或 state 不匹配。"));
        return;
      }

      res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
      res.end("<h1>X authorization complete</h1><p>You can close this tab.</p>");
      server.close();
      resolve(code);
    });

    server.on("error", reject);
    server.listen(Number(parsed.port || 80), parsed.hostname);
  });
}

async function exchangeCode({ clientId, clientSecret, code, codeVerifier, redirectUri }) {
  const body = new URLSearchParams({
    grant_type: "authorization_code",
    code,
    redirect_uri: redirectUri,
    code_verifier: codeVerifier,
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
    throw new Error(`X 授权失败：token exchange ${response.status} ${JSON.stringify(json)}`);
  }
  return json;
}

async function writeToken(tokenPath, payload) {
  await fs.mkdir(path.dirname(tokenPath), { recursive: true });
  await fs.writeFile(tokenPath, JSON.stringify(payload, null, 2), { encoding: "utf8", mode: 0o600 });
  await fs.chmod(tokenPath, 0o600).catch(() => {});
}

async function main() {
  await loadDotEnv();
  const args = parseArgs(process.argv.slice(2));
  const clientId = process.env.X_CLIENT_ID;
  const clientSecret = process.env.X_CLIENT_SECRET || "";
  if (!clientId) {
    throw new Error("X 授权失败：请先在 .env 设置 X_CLIENT_ID。");
  }

  const state = base64Url(randomBytes(24));
  const codeVerifier = base64Url(randomBytes(64));
  const params = new URLSearchParams({
    response_type: "code",
    client_id: clientId,
    redirect_uri: args.redirectUri,
    scope: SCOPES.join(" "),
    state,
    code_challenge: pkceChallenge(codeVerifier),
    code_challenge_method: "S256",
  });

  const codePromise = listenForCode(args.redirectUri, state);
  const authUrl = `https://x.com/i/oauth2/authorize?${params.toString()}`;
  console.log(`Open this URL to authorize X API access:\n${authUrl}\n`);
  if (args.openBrowser) openUrl(authUrl);

  const code = await codePromise;
  const token = await exchangeCode({
    clientId,
    clientSecret,
    code,
    codeVerifier,
    redirectUri: args.redirectUri,
  });

  await writeToken(args.tokenPath, {
    client_id: clientId,
    redirect_uri: args.redirectUri,
    scope: token.scope || SCOPES.join(" "),
    token_type: token.token_type,
    access_token: token.access_token,
    refresh_token: token.refresh_token,
    expires_at: Date.now() + Number(token.expires_in || 7200) * 1000,
  });
  console.log(`X API token saved: ${args.tokenPath}`);
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(1);
});
