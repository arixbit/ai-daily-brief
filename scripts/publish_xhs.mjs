#!/usr/bin/env node
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const DEFAULT_OUTPUT_DIR = path.join(ROOT, "xhs-drafts");
const DEFAULT_PROFILE_DIR = path.join(os.homedir(), ".hermes", "xhs-chrome-profile");
const PUBLISH_URL = "https://creator.xiaohongshu.com/publish/publish?source=official&from=menu&target=image";
const NOTE_MANAGER_URL = "https://creator.xiaohongshu.com/new/note-manager";
const XHS_FALLBACK_TITLE = "AI 日报";
const XHS_COLLECTION = "AI 日报";
const XHS_CONTENT_DECLARATION = "笔记含AI合成内容";

function usage() {
  return [
    "Usage: node scripts/publish_xhs.mjs --date YYYY-MM-DD [options]",
    "",
    "Options:",
    "  --date YYYY-MM-DD       Daily brief date to publish.",
    "  --output-dir PATH       Draft output root. Defaults to xhs-drafts.",
    "  --profile-dir PATH      Chrome profile dir. Defaults to ~/.hermes/xhs-chrome-profile.",
    "  --dry-run               Upload and fill the note, but do not click publish.",
    "  --headless              Run Chrome headless. Not recommended for first login.",
    "  --login-wait SECONDS    Wait for manual login before failing. Defaults to 0.",
    "  --help                  Show this help.",
  ].join("\n");
}

function parseArgs(argv) {
  const args = {
    date: "",
    outputDir: DEFAULT_OUTPUT_DIR,
    profileDir: process.env.XHS_CHROME_PROFILE_DIR || DEFAULT_PROFILE_DIR,
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
    throw new Error("小红书发布失败：缺少 --date。");
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

async function readDraft(args) {
  const draftDir = path.join(args.outputDir, `${args.date}-kami-news`);
  const cardsDir = path.join(draftDir, "cards");
  const postPath = path.join(draftDir, "post.md");

  const names = await fs.readdir(cardsDir);
  const cards = names
    .filter((name) => name.endsWith(".png"))
    .sort()
    .map((name) => path.join(cardsDir, name));
  if (cards.length === 0) {
    throw new Error(`小红书发布失败：没有找到图片 ${cardsDir}`);
  }

  const markdown = await fs.readFile(postPath, "utf8");
  const lines = markdown.split(/\r?\n/);
  const titleLine = lines.find((line) => line.startsWith("# "));
  const title = titleLine ? titleLine.replace(/^#\s+/, "").trim() : XHS_FALLBACK_TITLE;
  const body = lines.filter((line) => line !== titleLine).join("\n").trim();
  if (!body) {
    throw new Error(`小红书发布失败：正文为空 ${postPath}`);
  }
  return { draftDir, cards, title, body };
}

async function bodyText(page) {
  return page.locator("body").innerText({ timeout: 5000 }).catch(() => "");
}

async function bodyIncludes(page, needle) {
  return (await bodyText(page)).includes(needle);
}

async function waitForBodyText(page, needle, timeout = 30000) {
  await page.waitForFunction(
    (value) => document.body?.innerText.includes(value),
    needle,
    { timeout },
  );
}

async function clickText(page, text, { exact = true, timeout = 15000 } = {}) {
  const locator = page.getByText(text, { exact }).first();
  await locator.waitFor({ state: "visible", timeout });
  await locator.click({ timeout });
}

async function clickButton(page, name, timeout = 15000) {
  const locator = page.getByRole("button", { name, exact: true }).first();
  await locator.waitFor({ state: "visible", timeout });
  await locator.click({ timeout });
}

async function clickPublishControl(page) {
  await page.evaluate(() => {
    window.scrollTo(0, document.body.scrollHeight);
    for (const element of document.querySelectorAll("*")) {
      if (element.scrollHeight > element.clientHeight + 20) {
        element.scrollTop = element.scrollHeight;
      }
    }
  });
  await page.keyboard.press("End").catch(() => {});
  await page.waitForTimeout(800);

  const customPublish = page.locator("xhs-publish-btn[submit-disabled='false']").first();
  if (await customPublish.isVisible({ timeout: 3000 }).catch(() => false)) {
    const box = await customPublish.boundingBox();
    if (box) {
      const clickX = Math.min(box.x + box.width - 8, box.x + box.width / 2 + 72);
      await page.mouse.click(clickX, box.y + box.height / 2);
      return;
    }
  }

  const clicked = await page.waitForFunction(
    () => {
      const visible = (element) => {
        const rect = element.getBoundingClientRect();
        const style = window.getComputedStyle(element);
        return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none";
      };
      const disabled = (element) => (
        element.hasAttribute("disabled")
        || element.getAttribute("aria-disabled") === "true"
        || /\b(disabled|is-disabled)\b/.test(element.className || "")
      );
      const candidates = [...document.querySelectorAll("xhs-publish-btn, button, [role='button'], div, span")]
        .filter(visible)
        .filter((element) => {
          const label = (element.textContent || "").replace(/\s+/g, "").trim();
          if (element.tagName.toLowerCase() === "xhs-publish-btn") {
            return element.getAttribute("submit-disabled") === "false";
          }
          if (!/^(发布|发布笔记|立即发布)$/.test(label)) return false;
          const rect = element.getBoundingClientRect();
          return label !== "发布笔记" || rect.left > 300;
        })
        .sort((left, right) => {
          const leftButton = left.matches("button, [role='button']") ? 0 : 1;
          const rightButton = right.matches("button, [role='button']") ? 0 : 1;
          if (leftButton !== rightButton) return leftButton - rightButton;
          const leftRect = left.getBoundingClientRect();
          const rightRect = right.getBoundingClientRect();
          return (rightRect.top + rightRect.left / 10) - (leftRect.top + leftRect.left / 10);
        });

      const target = candidates.find((element) => !disabled(element));
      if (!target) return false;
      target.scrollIntoView({ block: "center", inline: "center" });
      if (target.tagName.toLowerCase() === "xhs-publish-btn") {
        const rect = target.getBoundingClientRect();
        const clickX = Math.min(rect.left + rect.width - 8, rect.left + rect.width / 2 + 72);
        document.elementFromPoint(clickX, rect.top + rect.height / 2)?.click();
      } else {
        target.click();
      }
      return true;
    },
    undefined,
    { timeout: 20000 },
  ).catch(() => null);

  if (!clicked) {
    const debugDir = path.join(ROOT, "xhs-drafts");
    await fs.mkdir(debugDir, { recursive: true });
    const screenshotPath = path.join(debugDir, "xhs-publish-button-debug.png");
    const htmlPath = path.join(debugDir, "xhs-publish-button-debug.html");
    await page.screenshot({ path: screenshotPath, fullPage: true }).catch(() => {});
    await fs.writeFile(htmlPath, await page.content(), "utf8").catch(() => {});
    const candidates = await page.evaluate(() => {
      const visible = (element) => {
        const rect = element.getBoundingClientRect();
        const style = window.getComputedStyle(element);
        return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none";
      };
      return [...document.querySelectorAll("xhs-publish-btn, button, [role='button'], div, span")]
        .filter(visible)
        .map((element) => {
          const rect = element.getBoundingClientRect();
          return {
            text: (element.textContent || "").replace(/\s+/g, " ").trim().slice(0, 80),
            tag: element.tagName.toLowerCase(),
            role: element.getAttribute("role") || "",
            disabled: element.hasAttribute("disabled") || element.getAttribute("aria-disabled") === "true",
            left: Math.round(rect.left),
            top: Math.round(rect.top),
            width: Math.round(rect.width),
            height: Math.round(rect.height),
          };
        })
        .filter((item) => /发布|提交|完成|草稿|下一步/.test(item.text))
        .slice(0, 30);
    });
    throw new Error(`小红书发布失败：找不到可点击的发布按钮。截图：${screenshotPath}，HTML：${htmlPath}，候选控件：${JSON.stringify(candidates)}`);
  }
}

async function clickOptionalConfirm(page) {
  await page.waitForTimeout(800);
  const clicked = await page.evaluate(() => {
    const visible = (element) => {
      const rect = element.getBoundingClientRect();
      const style = window.getComputedStyle(element);
      return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none";
    };
    const disabled = (element) => (
      element.hasAttribute("disabled")
      || element.getAttribute("aria-disabled") === "true"
      || /\b(disabled|is-disabled)\b/.test(element.className || "")
    );
    const candidates = [...document.querySelectorAll("button, [role='button'], div, span")]
      .filter(visible)
      .filter((element) => /^(确认发布|继续发布|仍要发布|确认|确定)$/.test((element.textContent || "").trim()))
      .sort((left, right) => {
        const leftRect = left.getBoundingClientRect();
        const rightRect = right.getBoundingClientRect();
        return (rightRect.top + rightRect.left / 10) - (leftRect.top + leftRect.left / 10);
      });

    const target = candidates.find((element) => !disabled(element));
    if (!target) return false;
    target.scrollIntoView({ block: "center", inline: "center" });
    target.click();
    return true;
  });
  if (clicked) await page.waitForTimeout(1200);
  return clicked;
}

async function publishControlDebug(page) {
  return page.evaluate(() => {
    const element = document.querySelector("xhs-publish-btn");
    const describe = (target) => {
      if (!target) return null;
      const rect = target.getBoundingClientRect();
      return {
        tag: target.tagName.toLowerCase(),
        text: (target.textContent || "").replace(/\s+/g, " ").trim().slice(0, 80),
        role: target.getAttribute("role") || "",
        className: String(target.className || "").slice(0, 120),
        left: Math.round(rect.left),
        top: Math.round(rect.top),
        width: Math.round(rect.width),
        height: Math.round(rect.height),
      };
    };
    const rect = element?.getBoundingClientRect();
    const points = rect
      ? [
          ["host-mid", rect.left + rect.width / 2, rect.top + rect.height / 2],
          ["host-mid-plus-72", rect.left + rect.width / 2 + 72, rect.top + rect.height / 2],
          ["screen-publish", 750, 856],
          ["screen-bottom", window.innerWidth / 2 + 30, window.innerHeight - 44],
        ]
      : [];
    return {
      host: describe(element),
      attrs: element ? Object.fromEntries([...element.attributes].map((attr) => [attr.name, attr.value])) : {},
      hasShadowRoot: Boolean(element?.shadowRoot),
      shadowText: element?.shadowRoot?.textContent?.replace(/\s+/g, " ").trim().slice(0, 200) || "",
      points: points.map(([name, x, y]) => ({
        name,
        x: Math.round(x),
        y: Math.round(y),
        stack: document.elementsFromPoint(x, y).slice(0, 6).map(describe),
      })),
    };
  });
}

async function clickNearText(page, text, { exact = true } = {}) {
  const clicked = await page.evaluate(({ needle, exactMatch }) => {
    const visible = (element) => {
      const rect = element.getBoundingClientRect();
      const style = window.getComputedStyle(element);
      return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none";
    };

    const element = [...document.querySelectorAll("span, div, p, label")]
      .find((node) => {
        if (!visible(node)) return false;
        const text = node.textContent?.trim() || "";
        return exactMatch ? text === needle : text.includes(needle);
      });
    if (!element) return false;

    let cursor = element;
    for (let depth = 0; cursor && depth < 5; depth += 1) {
      const control = cursor.querySelector?.("input[type='checkbox'], button, [role='switch']");
      if (control) {
        control.click();
        return true;
      }
      cursor = cursor.parentElement;
    }

    element.click();
    return true;
  }, { needle: text, exactMatch: exact });

  if (!clicked) {
    throw new Error(`找不到可点击文本：${text}`);
  }
}

async function fillWithKeyboard(page, target, value) {
  await target.click({ timeout: 15000 });
  await page.keyboard.press(process.platform === "darwin" ? "Meta+A" : "Control+A");
  await page.keyboard.press("Backspace").catch(() => {});
  await page.keyboard.insertText(value);
}

async function tryFillLocator(page, locator, value, timeout = 1500) {
  if ((await locator.count().catch(() => 0)) === 0) return false;
  const candidate = locator.first();
  if (!(await candidate.isVisible({ timeout }).catch(() => false))) return false;
  try {
    await candidate.fill(value, { timeout: 15000 });
    return true;
  } catch {
    await fillWithKeyboard(page, candidate, value);
    return true;
  }
}

async function fillPlaceholder(page, placeholder, value) {
  const locator = page.getByPlaceholder(new RegExp(placeholder)).first();
  if (await tryFillLocator(page, locator, value, 15000)) return;
  throw new Error(`小红书发布失败：找不到输入框 ${placeholder}`);
}

async function fillBodyEditor(page, value) {
  const placeholderPatterns = ["输入正文描述", "请输入正文描述", "输入正文", "请输入正文", "正文描述", "添加正文", "说点什么"];
  for (const pattern of placeholderPatterns) {
    if (await tryFillLocator(page, page.getByPlaceholder(new RegExp(pattern)).first(), value)) return;
  }

  const explicitEditor = page
    .locator(
      [
        "textarea[placeholder*='正文']",
        "textarea[placeholder*='描述']",
        "[contenteditable='true'][data-placeholder*='正文']",
        "[contenteditable='true'][data-placeholder*='描述']",
        "[contenteditable='true'][aria-label*='正文']",
        "[contenteditable='true'][aria-label*='描述']",
        "[role='textbox'][aria-label*='正文']",
        "[role='textbox'][aria-label*='描述']",
      ].join(", "),
    )
    .first();
  if (await tryFillLocator(page, explicitEditor, value)) return;

  const handle = await page.evaluateHandle(() => {
    const visible = (node) => {
      const rect = node.getBoundingClientRect();
      const style = window.getComputedStyle(node);
      return rect.width > 240 && rect.height > 24 && style.visibility !== "hidden" && style.display !== "none";
    };

    const editableNodes = [...document.querySelectorAll("textarea, [contenteditable='true'], [role='textbox']")];
    const candidates = editableNodes
      .filter(visible)
      .map((node) => {
        const rect = node.getBoundingClientRect();
        const attrs = [
          node.getAttribute("placeholder"),
          node.getAttribute("data-placeholder"),
          node.getAttribute("aria-label"),
          node.textContent,
        ]
          .filter(Boolean)
          .join(" ");
        let score = Math.min(rect.height, 300) + Math.min(rect.width, 700) / 10 + rect.top / 10;
        if (/正文|描述|内容/.test(attrs)) score += 500;
        if (/标题/.test(attrs)) score -= 500;
        return { node, score };
      })
      .sort((left, right) => right.score - left.score);

    return candidates[0]?.node || null;
  });

  const element = handle.asElement();
  if (!element) {
    await handle.dispose();
    throw new Error("小红书发布失败：找不到正文输入框。");
  }

  await fillWithKeyboard(page, element, value);
  await handle.dispose();
}

async function ensureLoggedIn(page, loginWaitMs) {
  const ready = async () => {
    const text = await bodyText(page);
    return text.includes("上传图片") || text.includes("选择文件") || text.includes("上传图文")
      || (await page.locator("input[type='file']").count().catch(() => 0)) > 0;
  };

  if (await ready()) return;
  const waitMs = loginWaitMs > 0 ? loginWaitMs : 20000;
  try {
    await page.waitForFunction(
      () => {
        const text = document.body?.innerText || "";
        return text.includes("上传图片")
          || text.includes("选择文件")
          || text.includes("上传图文")
          || document.querySelector("input[type='file']");
      },
      undefined,
      { timeout: waitMs },
    );
    return;
  } catch {
    // Fall through to a more specific login/page-structure error below.
  }

  const text = await bodyText(page);
  if (/登录|验证码|手机号/.test(text)) {
    throw new Error("小红书发布失败：Chrome 发布档案未登录。请先用 --login-wait 300 手动登录一次。");
  }
  throw new Error("小红书发布失败：未进入创作上传页，可能未登录或页面结构已变化。请先用 --login-wait 300 手动登录一次。");
}

async function uploadImages(page, cards, loginWaitMs) {
  await page.goto(PUBLISH_URL, { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.waitForLoadState("networkidle", { timeout: 15000 }).catch(() => {});
  await ensureLoggedIn(page, loginWaitMs);

  const fileInputs = page.locator("input[type='file']");
  if ((await fileInputs.count()) > 0) {
    await fileInputs.first().setInputFiles(cards);
  } else {
    const chooserPromise = page.waitForEvent("filechooser", { timeout: 15000 });
    const uploadButton = page.getByRole("button", { name: /上传图片|选择文件/ }).first();
    await uploadButton.click({ timeout: 15000 });
    const chooser = await chooserPromise;
    await chooser.setFiles(cards);
  }

  await waitForBodyText(page, `${cards.length}/18`, 120000);
}

async function ensureCollection(page) {
  const text = await bodyText(page);
  if (text.includes(`合集 ${XHS_COLLECTION}`)) return;

  await clickText(page, "选择合集");
  await clickText(page, XHS_COLLECTION);
  await waitForBodyText(page, XHS_COLLECTION);
}

async function ensureOriginalDeclaration(page) {
  if (await bodyIncludes(page, "已声明原创")) return;

  await clickNearText(page, "原创声明");
  await page.waitForTimeout(600);
  if (await bodyIncludes(page, "笔记完成原创声明后")) {
    await clickNearText(page, "我已阅读并同意", { exact: false });
    await clickButton(page, "声明原创");
  }
  await waitForBodyText(page, "已声明原创", 15000);
}

async function ensureContentDeclaration(page) {
  if (await bodyIncludes(page, XHS_CONTENT_DECLARATION)) return;

  await clickText(page, "添加内容类型声明");
  await clickText(page, XHS_CONTENT_DECLARATION);
  await waitForBodyText(page, XHS_CONTENT_DECLARATION, 10000);
}

async function fillNote(page, draft) {
  await fillPlaceholder(page, "填写标题", draft.title || XHS_FALLBACK_TITLE);
  await fillBodyEditor(page, draft.body);
  await page.waitForTimeout(500);

  await ensureCollection(page);
  await ensureOriginalDeclaration(page);
  await ensureContentDeclaration(page);
}

async function hasPublishedInManager(page, title, date, timeout = 0) {
  const deadline = Date.now() + timeout;
  do {
    await page.goto(NOTE_MANAGER_URL, { waitUntil: "domcontentloaded", timeout: 60000 });
    await page.waitForLoadState("networkidle", { timeout: 15000 }).catch(() => {});
    const text = await bodyText(page);
    if (text.includes(title)) {
      return true;
    }
    if (Date.now() >= deadline) break;
    await page.waitForTimeout(5000);
  } while (true);
  return false;
}

async function verifyPublishedInManager(page, title, date) {
  if (await hasPublishedInManager(page, title, date, 90000)) return;
  throw new Error(`小红书发布状态未确认：笔记管理中没有找到 ${title}。`);
}

async function ensureNotAlreadyPublished(page, title, date) {
  if (await hasPublishedInManager(page, title, date)) {
    console.log(`小红书已存在：${title}。`);
    return false;
  }
  return true;
}

async function waitForPublishCompletion(page, title, date) {
  const completion = await page.waitForFunction(
    () => {
      const text = document.body?.innerText || "";
      return /发布成功|提交成功|审核中/.test(text) || location.href.includes("note-manager");
    },
    undefined,
    { timeout: 90000 },
  ).catch(() => null);

  if (completion) return;
  const debugDir = path.join(ROOT, "xhs-drafts");
  await fs.mkdir(debugDir, { recursive: true });
  const screenshotPath = path.join(debugDir, "xhs-publish-completion-debug.png");
  const htmlPath = path.join(debugDir, "xhs-publish-completion-debug.html");
  await page.screenshot({ path: screenshotPath, fullPage: true }).catch(() => {});
  await fs.writeFile(htmlPath, await page.content(), "utf8").catch(() => {});
  if (await hasPublishedInManager(page, title, date, 30000)) return;
  throw new Error(`小红书发布失败：点击发布后没有看到成功、审核中或笔记管理跳转。截图：${screenshotPath}，HTML：${htmlPath}`);
}

async function publish(page, title, cardCount, date, dryRun) {
  if (dryRun) {
    if (process.env.XHS_DEBUG_PUBLISH_CONTROL === "1") {
      console.log(JSON.stringify(await publishControlDebug(page), null, 2));
    }
    console.log(`小红书待发布：${title}（${cardCount} 张）。`);
    return;
  }

  await clickPublishControl(page);
  await page.waitForTimeout(1200);
  await clickOptionalConfirm(page);
  await waitForPublishCompletion(page, title, date);
  await verifyPublishedInManager(page, title, date);
  console.log(`小红书已发布：${title}（${cardCount} 张）。`);
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const draft = await readDraft(args);
  if (!(await pathExists(args.profileDir))) {
    await fs.mkdir(args.profileDir, { recursive: true });
  }

  let chromium;
  try {
    ({ chromium } = await import("playwright"));
  } catch {
    throw new Error("小红书发布失败：缺少 Playwright 依赖，请先在项目目录运行 npm install。");
  }

  const context = await chromium.launchPersistentContext(args.profileDir, {
    channel: "chrome",
    headless: args.headless,
    viewport: { width: 1440, height: 900 },
    args: ["--disable-blink-features=AutomationControlled"],
  });

  try {
    const page = context.pages()[0] || await context.newPage();
    page.setDefaultTimeout(20000);
    if (!args.dryRun && !(await ensureNotAlreadyPublished(page, draft.title, args.date))) return;
    await uploadImages(page, draft.cards, args.loginWaitMs);
    await fillNote(page, draft);
    await publish(page, draft.title, draft.cards.length, args.date, args.dryRun);
  } finally {
    await context.close();
  }
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(1);
});
