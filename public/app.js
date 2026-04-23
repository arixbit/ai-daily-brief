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

function formatTime(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : timeFormatter.format(date);
}

function setActiveDate(date) {
  document.querySelectorAll(".archive-link").forEach((link) => {
    link.classList.toggle("active", link.dataset.date === date);
  });
}

function renderArchive(days) {
  archiveList.innerHTML = "";
  for (const day of days) {
    const link = document.createElement("a");
    link.href = `#${day.date}`;
    link.dataset.date = day.date;
    link.className = "archive-link";

    const date = document.createElement("span");
    date.textContent = day.date;
    const count = document.createElement("span");
    count.textContent = `${day.count} 条`;

    link.append(date, count);
    archiveList.append(link);
  }
}

function renderBrief(payload) {
  briefDate.textContent = formatDate(payload.date);
  briefTitle.textContent = payload.title;
  briefCount.textContent = `${payload.items.length} 条资讯`;
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
    title.textContent = item.title_cn || item.title;

    const summary = document.createElement("p");
    summary.className = "summary";
    summary.textContent = item.summary_cn;

    const why = document.createElement("p");
    why.className = "why";
    why.textContent = item.why_it_matters_cn;

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
    const sourceName = document.createElement("span");
    sourceName.textContent = item.source;
    const dot = document.createElement("span");
    dot.textContent = "·";
    const published = document.createElement("span");
    published.textContent = formatTime(item.published_at);
    const original = document.createElement("a");
    original.href = item.url;
    original.target = "_blank";
    original.rel = "noopener noreferrer";
    original.textContent = "原文";
    source.append(sourceName, dot, published, dot.cloneNode(true), original);

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

  renderArchive(days);

  if (days.length === 0) {
    briefTitle.textContent = "暂无简报";
    briefCount.textContent = "";
    emptyState.hidden = false;
    return;
  }

  const fromHash = decodeURIComponent(window.location.hash.replace("#", ""));
  const selected = days.find((day) => day.date === fromHash) || days[0];
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

