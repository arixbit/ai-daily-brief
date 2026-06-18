const archiveList = document.querySelector("#archiveList");
const newsList = document.querySelector("#newsList");
const emptyState = document.querySelector("#emptyState");
const updatedAt = document.querySelector("#updatedAt");
const briefDate = document.querySelector("#briefDate");
const briefTitle = document.querySelector("#briefTitle");
const briefCount = document.querySelector("#briefCount");

const dateFormatter = new Intl.DateTimeFormat("zh-CN", {
  year: "numeric",
  month: "long",
  day: "numeric",
});

const archiveDateFormatter = new Intl.DateTimeFormat("zh-CN", {
  month: "long",
  day: "numeric",
});

const timeFormatter = new Intl.DateTimeFormat("zh-CN", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
});

function formatDate(value) {
  const date = new Date(`${value}T00:00:00`);
  return Number.isNaN(date.getTime()) ? value : dateFormatter.format(date);
}

function formatArchiveDate(value) {
  const date = new Date(`${value}T00:00:00`);
  return Number.isNaN(date.getTime()) ? value : archiveDateFormatter.format(date);
}

function formatTime(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "时间未知" : timeFormatter.format(date);
}

function setActiveDate(date) {
  document.querySelectorAll(".archive-link").forEach((link) => {
    const isActive = link.dataset.date === date;
    link.classList.toggle("active", isActive);
    if (isActive) {
      link.setAttribute("aria-current", "date");
    } else {
      link.removeAttribute("aria-current");
    }
  });
}

function getToday() {
  const d = new Date();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${mm}-${dd}`;
}

function buildMonths(days) {
  const map = new Map();
  for (const day of days) {
    const monthKey = day.date.slice(0, 7);
    if (!map.has(monthKey)) {
      map.set(monthKey, []);
    }
    map.get(monthKey).push(day);
  }
  const monthLabels = {
    "01": "1月", "02": "2月", "03": "3月", "04": "4月",
    "05": "5月", "06": "6月", "07": "7月", "08": "8月",
    "09": "9月", "10": "10月", "11": "11月", "12": "12月",
  };
  return Array.from(map.entries())
    .sort(([a], [b]) => b.localeCompare(a))
    .map(([month, entries]) => ({
      month,
      label: `${month.slice(0, 4)}年${monthLabels[month.slice(5)] || ""}`,
      total: entries.reduce((sum, d) => sum + d.count, 0),
      days: entries,
    }));
}

function renderArchive(days, months) {
  archiveList.innerHTML = "";
  const today = getToday();
  const currentMonth = today.slice(0, 7);
  const groups = months && months.length
    ? months
    : buildMonths(days);

  for (const group of groups) {
    const isCurrentMonth = group.month === currentMonth;

    const container = document.createElement("div");
    container.className = "month-group";

    const header = document.createElement("button");
    header.className = "month-header";
    header.setAttribute("aria-expanded", String(isCurrentMonth));
    header.type = "button";

    const arrow = document.createElement("span");
    arrow.className = "month-arrow";
    arrow.setAttribute("aria-hidden", "true");
    arrow.textContent = isCurrentMonth ? "▼" : "▶";

    const label = document.createElement("span");
    label.className = "month-label";
    label.textContent = group.label;

    const total = document.createElement("span");
    total.className = "month-total";
    total.textContent = `${group.total} 条`;

    header.append(arrow, label, total);

    const body = document.createElement("div");
    body.className = "month-body";
    if (!isCurrentMonth) {
      body.classList.add("collapsed");
    }

    for (const day of group.days) {
      const link = document.createElement("a");
      link.href = `#${day.date}`;
      link.dataset.date = day.date;
      link.className = "archive-link";
      link.title = day.date;

      const date = document.createElement("span");
      date.className = "archive-date";
      date.textContent = formatArchiveDate(day.date);

      const count = document.createElement("span");
      count.className = "archive-count";
      count.textContent = `${day.count} 条`;

      link.append(date, count);
      body.append(link);
    }

    header.addEventListener("click", () => {
      const expanded = header.getAttribute("aria-expanded") === "true";
      header.setAttribute("aria-expanded", String(!expanded));
      arrow.textContent = expanded ? "▶" : "▼";
      body.classList.toggle("collapsed", !!expanded);
    });

    container.append(header, body);
    archiveList.append(container);
  }
}

function renderBrief(payload) {
  briefDate.textContent = formatDate(payload.date);
  briefTitle.textContent = payload.title;
  briefCount.textContent = `${payload.items.length} 条资讯`;
  document.title = `${payload.title} · AI 每日简报`;
  newsList.innerHTML = "";
  emptyState.hidden = payload.items.length > 0;

  for (const item of payload.items) {
    const row = document.createElement("li");
    row.className = "news-item";

    const rank = document.createElement("span");
    rank.className = "rank";
    rank.textContent = String(item.rank).padStart(2, "0");

    const content = document.createElement("article");

    const title = document.createElement("h3");
    if (item.url) {
      const titleLink = document.createElement("a");
      titleLink.href = item.url;
      titleLink.target = "_blank";
      titleLink.rel = "noopener noreferrer";
      titleLink.textContent = item.title_cn || item.title || "未命名资讯";
      title.append(titleLink);
    } else {
      title.textContent = item.title_cn || item.title || "未命名资讯";
    }

    const summary = document.createElement("p");
    summary.className = "summary";
    summary.textContent = item.summary_cn || "暂无摘要。";

    const why = document.createElement("p");
    why.className = "why";
    why.textContent = item.why_it_matters_cn || "暂无影响说明。";

    const tags = document.createElement("div");
    tags.className = "tags";
    for (const tag of item.tags || []) {
      const tagEl = document.createElement("span");
      tagEl.className = "tag";
      tagEl.textContent = tag;
      tags.append(tagEl);
    }

    const source = document.createElement("p");
    source.className = "source-line";
    const sourceLabel = document.createElement("span");
    sourceLabel.className = "source-label";
    sourceLabel.textContent = "来源";
    const sourceName = document.createElement("span");
    sourceName.textContent = item.source || "未知来源";
    const dot = document.createElement("span");
    dot.textContent = "·";
    const published = document.createElement("span");
    published.textContent = formatTime(item.published_at);
    source.append(sourceLabel, sourceName, dot, published);
    if (item.url) {
      const original = document.createElement("a");
      original.href = item.url;
      original.target = "_blank";
      original.rel = "noopener noreferrer";
      original.textContent = "原文";
      source.append(dot.cloneNode(true), original);
    }

    content.append(title, summary, why, tags, source);
    row.append(rank, content);
    newsList.append(row);
  }

  setActiveDate(payload.date);
}

async function loadBrief(path) {
  const response = await fetch(path, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`无法加载 ${path}`);
  }
  renderBrief(await response.json());
}

async function boot() {
  const manifestResponse = await fetch("data/manifest.json", { cache: "no-store" });
  const manifest = await manifestResponse.json();
  const days = manifest.days || [];

  updatedAt.textContent = manifest.updated_at
    ? `更新于 ${formatTime(manifest.updated_at)}`
    : "等待首次生成";

  const months = manifest.months || [];
  renderArchive(days, months);

  if (days.length === 0) {
    briefTitle.textContent = "暂无简报";
    briefCount.textContent = "";
    emptyState.hidden = false;
    return;
  }

  const fromHash = decodeURIComponent(window.location.hash.replace("#", ""));
  let selected;
  if (fromHash) {
    selected = days.find((day) => day.date === fromHash) || days[0];
  } else {
    selected = days.find((day) => day.date === getToday()) || days[0];
  }
  await loadBrief(selected.path);

  window.addEventListener("hashchange", async () => {
    const date = decodeURIComponent(window.location.hash.replace("#", ""));
    const day = days.find((candidate) => candidate.date === date);
    if (day) {
      await loadBrief(day.path);
    }
  });
}

boot().catch((error) => {
  briefTitle.textContent = "加载失败";
  briefCount.textContent = "";
  emptyState.hidden = false;
  emptyState.textContent = error.message;
});
