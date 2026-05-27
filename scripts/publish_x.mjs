#!/usr/bin/env node
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { execFile } from "node:child_process";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const DEFAULT_OUTPUT_DIR = path.join(ROOT, "x-drafts");
const DEFAULT_PROFILE_DIR = path.join(os.homedir(), ".hermes", "x-chrome-profile");
const COMPOSE_URL = "https://x.com/compose/post";
const HOME_URL = "https://x.com/home";
const DEFAULT_CDP_PORT = "9222";

function usage() {
  return [
    "Usage: node scripts/publish_x.mjs --date YYYY-MM-DD [options]",
    "",
    "Options:",
    "  --date YYYY-MM-DD       Daily brief date to publish.",
    "  --output-dir PATH       Draft output root. Defaults to x-drafts.",
    "  --profile-dir PATH      Chrome profile dir. Defaults to ~/.hermes/x-chrome-profile.",
    "  --dry-run               Upload and fill the post, but do not click Post.",
    "  --headless              Run Chrome headless.",
    "  --login-wait SECONDS    Wait for manual login before failing. Defaults to 0.",
    "  --help                  Show this help.",
  ].join("\n");
}

function parseArgs(argv) {
  const args = {
    date: "",
    outputDir: DEFAULT_OUTPUT_DIR,
    profileDir: process.env.X_CHROME_PROFILE_DIR || DEFAULT_PROFILE_DIR,
    dryRun: false,
    headless: false,
    loginWaitMs: 0,
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
    } else if (arg === "--profile-dir") {
      args.profileDir = argv[++index] || "";
    } else if (arg === "--dry-run") {
      args.dryRun = true;
    } else if (arg === "--headless") {
      args.headless = true;
    } else if (arg === "--login-wait") {
      args.loginWaitMs = Number(argv[++index] || "0") * 1000;
    } else {
      throw new Error(`不支持的参数：${arg}`);
    }
  }

  if (!args.date) {
    throw new Error("X 发布失败：缺少 --date。");
  }
  return args;
}

async function pathExists(target) {
  try {
    await fs.access(target);
    return true;
  } catch {
    return false;
  }
}

function normalizePostText(value) {
  return value.replace(/\s+/g, " ").trim();
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function cdpPort() {
  return process.env.X_CHROME_DEBUG_PORT || DEFAULT_CDP_PORT;
}

async function cdpEndpoint() {
  const configured = process.env.X_CHROME_CDP_URL;
  if (configured) return configured;

  const port = cdpPort();
  try {
    const response = await fetch(`http://127.0.0.1:${port}/json/version`, { signal: AbortSignal.timeout(1000) });
    if (!response.ok) return "";
    const payload = await response.json();
    return payload.webSocketDebuggerUrl ? `http://127.0.0.1:${port}` : "";
  } catch {
    return "";
  }
}

async function waitForCdpEndpoint(timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const endpoint = await cdpEndpoint();
    if (endpoint) return endpoint;
    await sleep(500);
  }
  return "";
}

async function openRealChrome(args) {
  if (process.platform !== "darwin") return "";

  await new Promise((resolve, reject) => {
    execFile(
      "/usr/bin/open",
      [
        "-na",
        "Google Chrome",
        "--args",
        `--user-data-dir=${args.profileDir}`,
        `--remote-debugging-port=${cdpPort()}`,
        "--no-first-run",
        "--no-default-browser-check",
        HOME_URL,
      ],
      (error) => {
        if (error) reject(error);
        else resolve();
      },
    );
  });

  return waitForCdpEndpoint(15000);
}

async function openCdpTarget(endpoint, url) {
  const response = await fetch(`${endpoint}/json/new?${encodeURIComponent(url)}`, { method: "PUT" });
  if (!response.ok) {
    throw new Error(`CDP 新建页面失败：HTTP ${response.status}`);
  }
  return response.json();
}

async function cdpPageTarget(endpoint) {
  const response = await fetch(`${endpoint}/json/list`);
  if (!response.ok) {
    throw new Error(`CDP 页面列表读取失败：HTTP ${response.status}`);
  }
  const targets = await response.json();
  const existing = targets.find((target) => target.type === "page" && target.url.includes("x.com"));
  return existing || openCdpTarget(endpoint, HOME_URL);
}

function connectCdp(webSocketDebuggerUrl) {
  const ws = new WebSocket(webSocketDebuggerUrl);
  let nextId = 0;
  const pending = new Map();

  ws.addEventListener("message", (event) => {
    const raw = typeof event.data === "string" ? event.data : Buffer.from(event.data).toString("utf8");
    const message = JSON.parse(raw);
    if (!message.id || !pending.has(message.id)) return;
    const { resolve, reject, timer } = pending.get(message.id);
    pending.delete(message.id);
    clearTimeout(timer);
    if (message.error) {
      reject(new Error(JSON.stringify(message.error)));
    } else {
      resolve(message.result);
    }
  });

  function send(method, params = {}, timeoutMs = 30000) {
    const id = ++nextId;
    ws.send(JSON.stringify({ id, method, params }));
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        if (pending.delete(id)) reject(new Error(`CDP timeout: ${method}`));
      }, timeoutMs);
      pending.set(id, { resolve, reject, timer });
    });
  }

  return new Promise((resolve, reject) => {
    ws.addEventListener("open", () => resolve({ ws, send, close: () => ws.close() }), { once: true });
    ws.addEventListener("error", reject, { once: true });
  });
}

async function connectRealChrome(args, startIfNeeded) {
  let endpoint = await cdpEndpoint();
  if (!endpoint && startIfNeeded) {
    endpoint = await openRealChrome(args);
  }
  if (!endpoint) return null;

  const target = await cdpPageTarget(endpoint);
  const cdp = await connectCdp(target.webSocketDebuggerUrl);
  await cdp.send("Runtime.enable");
  await cdp.send("Page.enable");
  await cdp.send("DOM.enable");
  return cdp;
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
    throw new Error(`X 发布失败：没有找到图片 ${cardsDir}`);
  }
  if (cards.length > 4) {
    throw new Error(`X 发布失败：单条 Post 最多 4 张图片，当前有 ${cards.length} 张。`);
  }

  const body = (await fs.readFile(postPath, "utf8")).trim();
  if (!body) {
    throw new Error(`X 发布失败：正文为空 ${postPath}`);
  }
  return { draftDir, cards, body };
}

async function cdpEval(cdp, expression, awaitPromise = true, timeoutMs = 30000) {
  const result = await cdp.send(
    "Runtime.evaluate",
    {
      expression,
      awaitPromise,
      returnByValue: true,
    },
    timeoutMs,
  );
  if (result.exceptionDetails) {
    throw new Error(JSON.stringify(result.exceptionDetails));
  }
  return result.result?.value;
}

async function cdpWaitFor(cdp, expression, timeoutMs, message) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const matched = await cdpEval(cdp, expression).catch(() => false);
    if (matched) return;
    await sleep(500);
  }
  throw new Error(message);
}

async function cdpNavigate(cdp, url) {
  await cdp.send("Page.navigate", { url }, 60000);
  await cdpWaitFor(cdp, "document.readyState !== 'loading'", 60000, `页面加载超时：${url}`);
  await sleep(1000);
}

async function cdpBodyText(cdp) {
  return cdpEval(cdp, "document.body?.innerText || ''").catch(() => "");
}

async function cdpLocation(cdp) {
  return cdpEval(cdp, "location.href").catch(() => "");
}

async function cdpEnsureLoggedIn(cdp, loginWaitMs) {
  await cdpNavigate(cdp, HOME_URL);

  const firstDeadline = Date.now() + 15000;
  while (Date.now() < firstDeadline) {
    const text = await cdpBodyText(cdp);
    const url = await cdpLocation(cdp);
    if (looksLoggedIn(text)) {
      return;
    }
    if (looksLikeLogin(url, text)) {
      break;
    }
    await sleep(500);
  }

  if (loginWaitMs <= 0) {
    throw new Error("X 发布失败：Chrome 发布档案未登录。请先用 --login-wait 300 手动登录一次。");
  }

  const deadline = Date.now() + loginWaitMs;
  while (Date.now() < deadline) {
    const text = await cdpBodyText(cdp);
    if (looksLoggedIn(text)) {
      return;
    }
    await sleep(1000);
  }
  throw new Error("X 发布失败：等待登录超时。");
}

async function cdpProfileUrl(cdp) {
  const configured = process.env.X_USERNAME || process.env.X_HANDLE;
  if (configured) {
    return `https://x.com/${configured.replace(/^@/, "")}`;
  }

  const href = await cdpEval(cdp, `
    (() => {
      const links = Array.from(document.querySelectorAll("a[href]"));
      const profile = links.find((link) => {
        const label = \`\${link.getAttribute("aria-label") || ""} \${link.textContent || ""}\`;
        const pathname = new URL(link.href, location.href).pathname;
        return /Profile|个人资料/.test(label) && /^\\/[A-Za-z0-9_]+$/.test(pathname);
      });
      if (profile) return profile.href;

      const account = links.find((link) => {
        const label = \`\${link.getAttribute("aria-label") || ""} \${link.textContent || ""}\`;
        const pathname = new URL(link.href, location.href).pathname;
        return /@[A-Za-z0-9_]+/.test(label) && /^\\/[A-Za-z0-9_]+$/.test(pathname);
      });
      return account ? account.href : "";
    })()
  `).catch(() => "");

  return href || HOME_URL;
}

async function cdpAlreadyPublished(cdp, draft) {
  const target = await cdpProfileUrl(cdp);
  await cdpNavigate(cdp, target);
  await sleep(1500);
  const text = normalizePostText(await cdpBodyText(cdp));
  return text.includes(normalizePostText(draft.body));
}

async function cdpFillEditor(cdp, text) {
  await cdpWaitFor(
    cdp,
    `Boolean(document.querySelector('[data-testid="tweetTextarea_0"], div[role="textbox"][contenteditable="true"]'))`,
    60000,
    "X 发布失败：找不到发帖正文输入框。",
  );
  await cdpEval(cdp, `
    (() => {
      const editors = [
        ...document.querySelectorAll('[data-testid="tweetTextarea_0"]'),
        ...document.querySelectorAll('div[role="textbox"][contenteditable="true"]')
      ];
      const editor = editors.find((el) => {
        const rect = el.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
      }) || editors[0];
      if (!editor) throw new Error("editor not found");
      editor.focus();
      const selection = getSelection();
      const range = document.createRange();
      range.selectNodeContents(editor);
      selection.removeAllRanges();
      selection.addRange(range);
      return true;
    })()
  `);
  await cdp.send("Input.insertText", { text });
}

async function cdpUploadImages(cdp, cards) {
  const doc = await cdp.send("DOM.getDocument", { depth: -1, pierce: true });
  const inputs = await cdp.send("DOM.querySelectorAll", {
    nodeId: doc.root.nodeId,
    selector: 'input[type="file"]',
  });
  if (!inputs.nodeIds?.length) {
    throw new Error("X 发布失败：找不到图片上传控件。");
  }
  await cdp.send("DOM.setFileInputFiles", {
    nodeId: inputs.nodeIds[0],
    files: cards,
  });
  await cdpWaitFor(
    cdp,
    `
      (() => {
        const text = document.body?.innerText || "";
        if (/Uploading|正在上传|处理中/.test(text)) return false;
        const images = document.querySelectorAll(
          '[data-testid="attachments"] img, [data-testid^="media-"] img, img[src^="blob:"]'
        );
        return images.length >= ${cards.length};
      })()
    `,
    120000,
    "X 发布失败：图片上传等待超时。",
  );
}

async function cdpCompose(cdp, draft) {
  await cdpNavigate(cdp, COMPOSE_URL);
  await cdpFillEditor(cdp, draft.body);
  await cdpUploadImages(cdp, draft.cards);
}

async function cdpWriteDebug(cdp, name) {
  const debugDir = path.join(DEFAULT_OUTPUT_DIR, "debug");
  await fs.mkdir(debugDir, { recursive: true });
  const screenshotPath = path.join(debugDir, `${name}.png`);
  const htmlPath = path.join(debugDir, `${name}.html`);
  const screenshot = await cdp.send("Page.captureScreenshot", { format: "png" }).catch(() => null);
  if (screenshot?.data) {
    await fs.writeFile(screenshotPath, Buffer.from(screenshot.data, "base64"));
  }
  const html = await cdpEval(cdp, "document.documentElement.outerHTML").catch(() => "");
  await fs.writeFile(htmlPath, html, "utf8").catch(() => {});
  return { screenshotPath, htmlPath };
}

async function cdpClickPostButton(cdp) {
  const clicked = await cdpEval(cdp, `
    (() => {
      const visible = (button) => {
        const rect = button.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0 && rect.top >= 0 && rect.top < window.innerHeight;
      };
      const enabled = (button) => !button.disabled && button.getAttribute("aria-disabled") !== "true";
      const byTestId = [
        ...document.querySelectorAll('button[data-testid="tweetButton"], button[data-testid="tweetButtonInline"]')
      ].filter((button) => visible(button) && enabled(button));
      const byText = [...document.querySelectorAll("button")]
        .filter((button) => /^(Post|发布|发帖|发送)$/.test((button.innerText || "").trim()))
        .filter((button) => visible(button) && enabled(button))
        .filter((button) => button.getBoundingClientRect().left > window.innerWidth * 0.35);
      const button = byTestId[0] || byText.sort((a, b) => b.getBoundingClientRect().top - a.getBoundingClientRect().top)[0];
      if (!button) return false;
      button.click();
      return true;
    })()
  `);
  if (!clicked) {
    throw new Error("X 发布失败：找不到可点击的 Post 按钮。");
  }
}

async function cdpWaitForPublishCompletion(cdp) {
  await cdpWaitFor(
    cdp,
    `
      (() => {
        const text = document.body?.innerText || "";
        const sent = /Your post was sent|Your Post was sent|你的帖子已发送|帖子已发送|已发布|已发送/.test(text);
        const editorVisible = Boolean([...document.querySelectorAll('[data-testid="tweetTextarea_0"]')].find((el) => {
          const rect = el.getBoundingClientRect();
          return rect.width > 0 && rect.height > 0;
        }));
        return sent || (!location.href.includes("/compose/post") && !editorVisible);
      })()
    `,
    90000,
    "X 发布失败：点击发布后没有看到发送成功状态。",
  );
}

async function publishWithCdp(args, draft) {
  const cdp = await connectRealChrome(args, true);
  if (!cdp) {
    throw new Error("X 发布失败：无法打开或连接真实 Chrome 调试端口。请确认没有普通 Chrome 占用 x-chrome-profile，并重试 --browser。");
  }

  try {
    await cdpEnsureLoggedIn(cdp, args.loginWaitMs);
    if (await cdpAlreadyPublished(cdp, draft)) {
      console.log(`X 已存在：${draft.cards.length} 张。`);
      return;
    }
    await cdpCompose(cdp, draft);

    if (args.dryRun) {
      const debug = await cdpWriteDebug(cdp, "x-dry-run");
      console.log(`X 待发布：${draft.cards.length} 张。截图：${debug.screenshotPath}`);
      return;
    }

    await cdpClickPostButton(cdp);
    await cdpWaitForPublishCompletion(cdp);
    console.log(`X 已发布：${draft.cards.length} 张。`);
  } catch (error) {
    const debug = await cdpWriteDebug(cdp, "x-publish-debug").catch(() => null);
    const detail = error instanceof Error ? error.message : String(error);
    if (debug) {
      throw new Error(`${detail} 截图：${debug.screenshotPath}，HTML：${debug.htmlPath}`);
    }
    throw error;
  } finally {
    cdp.close();
  }
}

async function bodyText(page) {
  return page.locator("body").innerText({ timeout: 5000 }).catch(() => "");
}

async function hasComposer(page) {
  return (await page.locator("[data-testid='tweetTextarea_0'], div[role='textbox'][contenteditable='true']").count()) > 0;
}

function looksLikeLogin(url, text) {
  return url.includes("/i/flow/login")
    || url.includes("/login")
    || /正在发生|登录|Log in|Sign in|注册|Create account|使用手机继续|电子邮箱或用户名|邮箱或用户名|Continue with Google|使用 Apple 继续/.test(text);
}

function looksLoggedIn(text) {
  return /What’s happening\?|What's happening\?|Home timeline|Your Home Timeline|Account menu|Post text|有什么新鲜事|主页时间线|账号菜单/.test(text);
}

async function ensureLoggedIn(page, loginWaitMs) {
  await page.goto(HOME_URL, { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.waitForLoadState("networkidle", { timeout: 15000 }).catch(() => {});
  const text = await bodyText(page);
  if (looksLoggedIn(text)) {
    return;
  }

  if (loginWaitMs > 0) {
    await page.waitForFunction(
      () => {
        const text = document.body?.innerText || "";
        return /What’s happening\?|What's happening\?|Home timeline|Your Home Timeline|Account menu|Post text|有什么新鲜事|主页时间线|账号菜单/.test(text);
      },
      undefined,
      { timeout: loginWaitMs },
    );
    return;
  }

  throw new Error("X 发布失败：Chrome 发布档案未登录。请先用 --login-wait 300 手动登录一次。");
}

async function profileUrl(page) {
  const configured = process.env.X_USERNAME || process.env.X_HANDLE;
  if (configured) {
    return `https://x.com/${configured.replace(/^@/, "")}`;
  }

  const href = await page.evaluate(() => {
    const links = Array.from(document.querySelectorAll("a[href]"));
    const profile = links.find((link) => {
      const label = `${link.getAttribute("aria-label") || ""} ${link.textContent || ""}`;
      const pathname = new URL(link.href, location.href).pathname;
      return /Profile|个人资料/.test(label) && /^\/[A-Za-z0-9_]+$/.test(pathname);
    });
    if (profile) return profile.href;

    const account = links.find((link) => {
      const label = `${link.getAttribute("aria-label") || ""} ${link.textContent || ""}`;
      const pathname = new URL(link.href, location.href).pathname;
      return /@[A-Za-z0-9_]+/.test(label) && /^\/[A-Za-z0-9_]+$/.test(pathname);
    });
    return account ? account.href : "";
  }).catch(() => "");

  return href || HOME_URL;
}

async function alreadyPublished(page, draft) {
  const target = await profileUrl(page);
  await page.goto(target, { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.waitForLoadState("networkidle", { timeout: 15000 }).catch(() => {});
  await page.waitForTimeout(1500);
  const text = normalizePostText(await bodyText(page));
  return text.includes(normalizePostText(draft.body));
}

async function editorLocator(page) {
  const locators = [
    page.locator("[data-testid='tweetTextarea_0']").first(),
    page.locator("div[role='textbox'][contenteditable='true']").first(),
    page.getByRole("textbox").first(),
  ];
  for (const locator of locators) {
    if ((await locator.count().catch(() => 0)) === 0) continue;
    if (await locator.isVisible({ timeout: 3000 }).catch(() => false)) return locator;
  }
  throw new Error("X 发布失败：找不到发帖正文输入框。");
}

async function fillEditor(page, text) {
  const editor = await editorLocator(page);
  await editor.click({ timeout: 15000 });
  await page.keyboard.press(process.platform === "darwin" ? "Meta+A" : "Control+A").catch(() => {});
  await page.keyboard.press("Backspace").catch(() => {});
  await page.keyboard.insertText(text);
}

async function uploadImages(page, cards) {
  const fileInputs = page.locator("input[type='file']");
  if ((await fileInputs.count().catch(() => 0)) === 0) {
    throw new Error("X 发布失败：找不到图片上传控件。");
  }
  await fileInputs.first().setInputFiles(cards);

  await page.waitForFunction(
    (count) => {
      const uploadingText = document.body?.innerText || "";
      if (/Uploading|正在上传|处理中/.test(uploadingText)) return false;
      const images = document.querySelectorAll(
        "[data-testid='attachments'] img, [data-testid^='media-'] img, img[src^='blob:']",
      );
      return images.length >= count;
    },
    cards.length,
    { timeout: 120000 },
  );
}

async function clickPostButton(page) {
  const selectors = [
    "button[data-testid='tweetButton']",
    "button[data-testid='tweetButtonInline']",
  ];
  for (const selector of selectors) {
    const button = page.locator(selector).first();
    if ((await button.count().catch(() => 0)) === 0) continue;
    if (!(await button.isVisible({ timeout: 3000 }).catch(() => false))) continue;
    await page.waitForFunction(
      (value) => {
        const node = document.querySelector(value);
        return node && !node.disabled && node.getAttribute("aria-disabled") !== "true";
      },
      selector,
      { timeout: 30000 },
    );
    await button.click({ timeout: 15000 });
    return;
  }

  const roleButton = page.getByRole("button", { name: /Post|发布|发帖|发送/ }).last();
  await roleButton.waitFor({ state: "visible", timeout: 15000 });
  await roleButton.click({ timeout: 15000 });
}

async function waitForPublishCompletion(page) {
  await page.waitForFunction(
    () => {
      const text = document.body?.innerText || "";
      return /Your Post was sent|帖子已发送|已发布|已发送/.test(text)
        || (!location.href.includes("/compose/post") && !document.querySelector("[data-testid='tweetTextarea_0']"));
    },
    undefined,
    { timeout: 90000 },
  );
}

async function writeDebug(page, name) {
  const debugDir = path.join(DEFAULT_OUTPUT_DIR, "debug");
  await fs.mkdir(debugDir, { recursive: true });
  const screenshotPath = path.join(debugDir, `${name}.png`);
  const htmlPath = path.join(debugDir, `${name}.html`);
  await page.screenshot({ path: screenshotPath, fullPage: true }).catch(() => {});
  await fs.writeFile(htmlPath, await page.content(), "utf8").catch(() => {});
  return { screenshotPath, htmlPath };
}

async function compose(page, draft, loginWaitMs) {
  await ensureLoggedIn(page, loginWaitMs);
  if (await alreadyPublished(page, draft)) {
    return "exists";
  }
  await page.goto(COMPOSE_URL, { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.waitForLoadState("networkidle", { timeout: 15000 }).catch(() => {});
  if (!(await hasComposer(page))) {
    await page.waitForTimeout(2000);
  }
  await fillEditor(page, draft.body);
  await uploadImages(page, draft.cards);
  return "ready";
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const draft = await readDraft(args);
  if (!(await pathExists(args.profileDir))) {
    if (args.loginWaitMs <= 0) {
      throw new Error(`X 发布失败：Chrome 发布档案不存在：${args.profileDir}。请先运行 --browser --login-wait 300 初始化并登录一次。`);
    }
    await fs.mkdir(args.profileDir, { recursive: true });
  }

  if (!args.headless) {
    await publishWithCdp(args, draft);
    return;
  }

  let chromium;
  try {
    ({ chromium } = await import("playwright"));
  } catch {
    throw new Error("X 发布失败：缺少 Playwright 依赖，请先在项目目录运行 npm install。");
  }

  let context;
  try {
    context = await chromium.launchPersistentContext(args.profileDir, {
      channel: "chrome",
      headless: args.headless,
      viewport: { width: 1440, height: 900 },
      args: ["--disable-blink-features=AutomationControlled"],
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    if (/ProcessSingleton|user data directory is already in use|profile.*in use|Target page, context or browser has been closed/i.test(message)) {
      throw new Error("X 发布失败：x-chrome-profile 当前被 Chrome 占用。请关闭刚才登录 X 的 Chrome 窗口后重试。");
    }
    throw error;
  }

  let page;
  try {
    page = context.pages()[0] || await context.newPage();
    page.setDefaultTimeout(20000);
    const state = await compose(page, draft, args.loginWaitMs);
    if (state === "exists") {
      console.log(`X 已存在：${draft.cards.length} 张。`);
      return;
    }

    if (args.dryRun) {
      const debug = await writeDebug(page, "x-dry-run");
      console.log(`X 待发布：${draft.cards.length} 张。截图：${debug.screenshotPath}`);
      return;
    }

    await clickPostButton(page);
    await waitForPublishCompletion(page);
    console.log(`X 已发布：${draft.cards.length} 张。`);
  } catch (error) {
    if (page) {
      const debug = await writeDebug(page, "x-publish-debug");
      const detail = error instanceof Error ? error.message : String(error);
      throw new Error(`${detail} 截图：${debug.screenshotPath}，HTML：${debug.htmlPath}`);
    }
    throw error;
  } finally {
    await context.close();
  }
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(1);
});
