var socket = io();

let PREFIXES = [];
let historyContext = null;
let categoryData = Array.isArray(window.initialCategoryData)
  ? window.initialCategoryData
  : [];
window.currentNavInfo = window.currentNavInfo || null;
const DEFAULT_THEME = "auto";
const DEFAULT_ACCENT = "emerald";
const DEFAULT_RELATIVE_TIME = "today";
const RELATIVE_TIME_KEY = "chapterRelativeTime";
const RELATIVE_TIME_OPTIONS = ["off", "today", "week", "month", "always"];
let activeModalCount = 0;
let categoryReorderQueue = Promise.resolve();
let currentRelativeTime =
  (typeof localStorage !== "undefined" &&
    localStorage.getItem(RELATIVE_TIME_KEY)) ||
  DEFAULT_RELATIVE_TIME;
if (!RELATIVE_TIME_OPTIONS.includes(currentRelativeTime)) {
  currentRelativeTime = DEFAULT_RELATIVE_TIME;
}

function updateBodyModalState(delta) {
  activeModalCount = Math.max(0, activeModalCount + delta);
  if (activeModalCount > 0) {
    document.body?.classList.add("modal-open");
  } else {
    document.body?.classList.remove("modal-open");
  }
}

function showModalElement(element) {
  if (element && element.classList.contains("hidden")) {
    element.classList.remove("hidden");
    updateBodyModalState(1);
  }
}

function hideModalElement(element) {
  if (element && !element.classList.contains("hidden")) {
    element.classList.add("hidden");
    updateBodyModalState(-1);
  }
}

function applyThemePreference(mode) {
  const root = document.documentElement;
  const target = mode || DEFAULT_THEME;
  if (!root) return target;
  if (target === "auto") {
    root.removeAttribute("data-theme");
    localStorage.removeItem("chapterTheme");
  } else {
    root.setAttribute("data-theme", target);
    localStorage.setItem("chapterTheme", target);
  }
  return target;
}

function applyAccentPreference(accent) {
  const root = document.documentElement;
  const value = accent || DEFAULT_ACCENT;
  if (!root) return value;
  root.setAttribute("data-accent", value);
  localStorage.setItem("chapterAccent", value);
  return value;
}

function markActiveAccent(accent) {
  document.querySelectorAll(".accent-swatch").forEach((btn) => {
    if (!btn) return;
    btn.classList.toggle("active", btn.dataset.accent === accent);
  });
}

function parseTimestampValue(raw) {
  if (!raw) return null;
  const trimmed = raw.trim();
  if (!trimmed || trimmed.toLowerCase() === "unknown") return null;
  let parsed = moment(
    trimmed,
    [moment.ISO_8601, "YYYY/MM/DD HH:mm:ss", "YYYY/MM/DD HH:mm", "YYYY/MM/DD"],
    true
  );
  if (!parsed.isValid()) {
    parsed = moment(new Date(trimmed));
  }
  return parsed.isValid() ? parsed : null;
}

function formatTimestampForPreference(absolute, fallback, mode) {
  const safeMode = RELATIVE_TIME_OPTIONS.includes(mode)
    ? mode
    : DEFAULT_RELATIVE_TIME;
  const baseLabel = fallback || absolute || "Unknown";
  const parsed = parseTimestampValue(absolute);
  const absoluteLabel = absolute || (parsed ? parsed.format("YYYY/MM/DD") : "");
  if (!parsed) {
    return {
      label: safeMode === "off" && absolute ? absolute : baseLabel,
      isRelative: false,
      reference: absoluteLabel,
    };
  }
  const now = moment();
  const yesterday = now.clone().subtract(1, "day");
  const diffDays = Math.abs(now.diff(parsed, "days"));
  const sameDayLabel = parsed.isSame(now, "day")
    ? "Today"
    : parsed.isSame(yesterday, "day")
    ? "Yesterday"
    : null;
  const result = {
    label: baseLabel,
    isRelative: false,
    reference: absoluteLabel,
  };
  switch (safeMode) {
    case "off":
      result.label = absolute || parsed.format("YYYY/MM/DD");
      break;
    case "today":
      if (sameDayLabel) {
        result.label = sameDayLabel;
        result.isRelative = true;
        break;
      }
      result.label = absolute || parsed.format("YYYY/MM/DD");
      break;
    case "week":
      if (sameDayLabel) {
        result.label = sameDayLabel;
        result.isRelative = true;
      } else if (diffDays < 7) {
        result.label = parsed.fromNow();
        result.isRelative = true;
      } else {
        result.label = absolute || parsed.format("YYYY/MM/DD");
      }
      break;
    case "month":
      if (sameDayLabel) {
        result.label = sameDayLabel;
        result.isRelative = true;
      } else if (diffDays < 31) {
        result.label = parsed.fromNow();
        result.isRelative = true;
      } else {
        result.label = absolute || parsed.format("YYYY/MM/DD");
      }
      break;
    case "always":
      if (sameDayLabel) {
        result.label = sameDayLabel;
        result.isRelative = true;
      } else {
        result.label = parsed.fromNow();
        result.isRelative = true;
      }
      break;
    default:
      result.label = baseLabel;
  }
  return result;
}

function updateRelativeTimestamps(root = document) {
  if (!root) return;
  root.querySelectorAll(".timestamp-text").forEach((container) => {
    const label = container.querySelector(".timestamp-label");
    if (!label) return;
    const absolute =
      container.dataset.timestamp || container.dataset.absolute || "";
    const fallback = container.dataset.defaultLabel || label.textContent || "";
    const {
      label: display,
      isRelative,
      reference,
    } = formatTimestampForPreference(absolute, fallback, currentRelativeTime);
    label.textContent = display;
    const tooltip = container.querySelector(".timestamp-tooltiptext");
    if (!tooltip) return;
    if (reference) {
      tooltip.textContent = reference;
    }
    const shouldShow = isRelative && Boolean(reference);
    tooltip.classList.toggle("tooltip-hidden", !shouldShow);
    tooltip.setAttribute("aria-hidden", shouldShow ? "false" : "true");
  });
}

function markActiveRelativeTime(mode) {
  document
    .querySelectorAll('input[name="relativeTimeMode"]')
    .forEach((radio) => {
      radio.checked = radio.value === mode;
    });
}

function applyRelativeTimePreference(mode, options = {}) {
  const normalized = RELATIVE_TIME_OPTIONS.includes(mode)
    ? mode
    : DEFAULT_RELATIVE_TIME;
  currentRelativeTime = normalized;
  if (!options.skipPersist) {
    localStorage.setItem(RELATIVE_TIME_KEY, normalized);
  }
  markActiveRelativeTime(normalized);
  if (!options.skipUpdate) {
    updateRelativeTimestamps();
  }
  return normalized;
}

function renderCategoryNav(categories = categoryData) {
  const list = document.getElementById("categoryNavList");
  if (!list || !Array.isArray(categories)) {
    return;
  }
  categoryData = categories;
  const current = getCurrentCategory();
  const visibleCategories = categories.filter(
    (cat) => cat && cat.include_in_nav
  );
  const hasCurrentVisible = visibleCategories.some(
    (cat) => cat?.name === current
  );
  const fallbackInfo =
    window.currentNavInfo && window.currentNavInfo.name === current
      ? window.currentNavInfo
      : null;
  const renderList = hasCurrentVisible
    ? visibleCategories
    : [
        ...visibleCategories,
        ...(fallbackInfo ? [{ ...fallbackInfo, include_in_nav: true }] : []),
      ];
  const existingLinks = new Map(
    Array.from(list.querySelectorAll(".category-nav__item[data-category]")).map(
      (link) => [link.dataset.category, link]
    )
  );
  const renderedNames = new Set();
  let insertIndex = 0;

  renderList.forEach((cat) => {
    const name = cat.name;
    if (!name) return;
    renderedNames.add(name);

    let link = existingLinks.get(name);
    if (!link) {
      link = document.createElement("a");
      link.className = "category-nav__item";
      link.dataset.category = name;

      const newLabel = document.createElement("span");
      newLabel.className = "category-nav__label";
      link.appendChild(newLabel);

      const newCount = document.createElement("span");
      newCount.className = "category-nav__count";
      link.appendChild(newCount);

      list.appendChild(link);
    }

    const targetUrl = name === "main" ? "/" : `/${name}`;
    link.href = targetUrl;
    link.classList.toggle("active", name === current);

    let label = link.querySelector(".category-nav__label");
    if (!label) {
      label = document.createElement("span");
      label.className = "category-nav__label";
      link.insertBefore(label, link.firstChild);
    }
    label.textContent = cat.display_name || name;

    let count = link.querySelector(".category-nav__count");
    if (!count) {
      count = document.createElement("span");
      count.className = "category-nav__count";
      link.appendChild(count);
    }
    count.id = `navCount-${name}`;
    count.textContent = cat.unsaved_count ?? 0;

    // Keep DOM order in sync without removing nodes unnecessarily
    const targetNode = list.children[insertIndex];
    if (targetNode !== link) {
      list.insertBefore(link, targetNode ?? null);
    }
    insertIndex += 1;
  });

  existingLinks.forEach((link, name) => {
    if (!renderedNames.has(name)) {
      link.remove();
    }
  });
}

function setPrefixesFromCategories(categories) {
  const names = Array.isArray(categories)
    ? categories
        .map((c) => (typeof c === "string" ? c : c.name))
        .filter(Boolean)
    : [];
  PREFIXES = names.filter((name) => name !== "main").map((name) => `/${name}`);
}

const initialThemeChoice =
  localStorage.getItem("chapterTheme") || DEFAULT_THEME;
const initialAccentChoice =
  localStorage.getItem("chapterAccent") || DEFAULT_ACCENT;
applyThemePreference(initialThemeChoice);
applyAccentPreference(initialAccentChoice);
markActiveAccent(initialAccentChoice);

async function loadPrefixes() {
  const response = await fetch("/api/categories");
  const categories = await response.json();
  if (Array.isArray(categories)) {
    categoryData = categories;
    renderCategoryNav(categoryData);
  }
  setPrefixesFromCategories(categories);
}

if (Array.isArray(categoryData) && categoryData.length > 0) {
  setPrefixesFromCategories(categoryData);
}

loadPrefixes();
renderCategoryNav(categoryData);
setPrefixesFromCategories(categoryData);

async function refreshCategoriesFromServer() {
  const response = await fetch("/api/categories");
  if (!response.ok) {
    throw new Error("Failed to load categories");
  }
  const data = await response.json();
  if (Array.isArray(data)) {
    categoryData = data;
    renderCategoryNav(categoryData);
    renderCategoryManagerList();
    setPrefixesFromCategories(data);
  }
  return data;
}

function actionPath(action) {
  const prefix =
    PREFIXES.find((p) => window.location.pathname.startsWith(p)) || "";
  return `${prefix}/${action}`.replace("//", "/");
}

// ===== Overlay Controls =====
function showSpinner(message = "Loading...") {
  const overlay = document.getElementById("overlay");
  document.getElementById("statusMessage").innerText = message;
  overlay.classList.add("show");
}

function hideSpinner() {
  const overlay = document.getElementById("overlay");
  overlay.classList.remove("show");
}

// ===== Progress updates via WebSocket =====
function getCurrentCategory() {
  return document.body?.dataset.category || "main";
}

function subscribeToCategoryChannel() {
  if (!socket || typeof socket.emit !== "function") return;
  socket.emit("subscribe_category", { category: getCurrentCategory() });
}

socket.on("connect", () => {
  subscribeToCategoryChannel();
});

if (socket.connected) {
  subscribeToCategoryChannel();
}

socket.on("update_progress", function (data) {
  const targetCategory = data?.category || "main";
  if (targetCategory !== getCurrentCategory()) {
    return;
  }
  showSpinner(`Updating... ${data.current}/${data.total}`);
  const fill = document.getElementById("progressFill");
  const percent = (data.current / data.total) * 100;
  fill.style.width = percent + "%";
});

socket.on("update_complete", function (data) {
  const targetCategory = data?.category || "main";
  if (targetCategory !== getCurrentCategory()) {
    return;
  }
  refreshChapterTables()
    .catch((error) =>
      console.error("Error refreshing chapters after scheduled update:", error)
    )
    .finally(() => hideSpinner());
});

// ===== AJAX functions =====
function updateChapter(url) {
  showSpinner("Updating chapter...");
  const path = actionPath("update");
  fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url: url, timestamp: new Date().toISOString() }),
  })
    .then((response) => response.json())
    .then(() => refreshChapterTables())
    .catch((error) => {
      console.error("Error updating chapter:", error);
    })
    .finally(() => hideSpinner());
}

function recheckChapter(url) {
  showSpinner("Rechecking chapter...");
  const path = actionPath("recheck");
  fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url: url }),
  })
    .then((response) => response.json())
    .then(() => refreshChapterTables())
    .catch((error) => {
      console.error("Error rechecking chapter:", error);
    })
    .finally(() => hideSpinner());
}

function addLink() {
  const name = document.getElementById("newName").value;
  const url = document.getElementById("newUrl").value;
  if (!name || !url) return alert("Please enter both name and URL.");

  showSpinner("Adding link...");
  const path = actionPath("add");
  fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, url }),
  })
    .then((response) => response.json())
    .then(() => refreshChapterTables())
    .catch((error) => console.error("Error adding link:", error))
    .finally(() => hideSpinner());
}

function removeLink() {
  const url = document.getElementById("removeUrl").value;
  if (!confirm("Are you sure you want to remove this link?")) return;

  const path = actionPath("remove");
  fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  })
    .then((response) => response.json())
    .then((data) =>
      data.status === "success"
        ? refreshChapterTables().catch((err) =>
            console.error("Error refreshing chapters after removal:", err)
          )
        : alert("Failed to remove link.")
    );
}

function removeLinkByUrl(url) {
  if (!confirm("Are you sure you want to remove this link?")) return;
  const path = actionPath("remove");
  fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  })
    .then((r) => r.json())
    .then((data) => {
      if (data.status === "success")
        refreshChapterTables().catch((err) =>
          console.error("Error refreshing chapters after removal:", err)
        );
      else alert("Failed to remove link.");
    })
    .catch((err) => {
      console.error("Error removing link:", err);
      alert("Error removing link.");
    });
}

function toggleFavorite(url, container) {
  const isFavorite = container.dataset.favorite === "true";
  const nextState = !isFavorite;
  container.dataset.favorite = nextState.toString();
  showSpinner(isFavorite ? "Removing favorite…" : "Marking favorite…");
  const path = actionPath("favorite");
  fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, favorite: !isFavorite }),
  })
    .then((response) => response.json())
    .then(() => refreshChapterTables())
    .catch((error) => {
      console.error("Error toggling favorite:", error);
    })
    .finally(() => hideSpinner());
}

function formatDateTime(value) {
  if (!value) return "Unknown";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function configureRelativeTime() {
  moment.relativeTimeRounding(Math.floor);
  moment.relativeTimeThreshold("s", 60);
  moment.relativeTimeThreshold("m", 60);
  moment.relativeTimeThreshold("h", 24);
  moment.relativeTimeThreshold("d", 31);
  moment.relativeTimeThreshold("M", 12);
}

function updateLastUpdateTooltip(value) {
  const tooltip = document.getElementById("lastUpdateTooltip");
  if (!tooltip) return;
  if (!value) {
    tooltip.textContent = "Never";
    return;
  }
  const relativeTime = moment(value).fromNow();
  tooltip.textContent =
    relativeTime === "Invalid date" ? "Never" : relativeTime;
}

function setupDomainTooltips(root = document) {
  if (!root) return;
  root.querySelectorAll(".domain-tooltip").forEach((link) => {
    try {
      const urlObj = new URL(link.href);
      let hostname = urlObj.hostname;
      if (hostname.startsWith("www.")) hostname = hostname.slice(4);
      link.parentElement.querySelector(".tooltiptext").textContent = hostname;
    } catch (e) {
      link.parentElement.querySelector(".tooltiptext").textContent =
        "Invalid URL";
    }
  });
}

function setupFloatingTooltips(root = document) {
  if (!root) return;
  root.querySelectorAll(".table-tooltip").forEach((trigger) => {
    if (trigger.dataset.floatingTooltipInitialized === "true") return;
    const tip = trigger.querySelector(".tooltiptext");
    if (!tip) return;
    trigger.dataset.floatingTooltipInitialized = "true";
    let floating = null;

    const showFloating = () => {
      floating = tip.cloneNode(true);
      floating.classList.add("floating");
      floating.style.position = "absolute";
      floating.style.visibility = "hidden";
      document.body.appendChild(floating);

      trigger.classList.add("has-floating");

      const rect = trigger.getBoundingClientRect();
      const fRect = floating.getBoundingClientRect();
      const gap = 6;
      let top = rect.top + window.scrollY - fRect.height - gap;
      let left = rect.left + window.scrollX + rect.width / 2 - fRect.width / 2;

      const pad = 8;
      const maxLeft =
        window.scrollX +
        document.documentElement.clientWidth -
        fRect.width -
        pad;
      left = Math.max(window.scrollX + pad, Math.min(left, maxLeft));

      if (top < window.scrollY + pad) {
        top = rect.bottom + window.scrollY + gap;
      }

      floating.style.top = `${top}px`;
      floating.style.left = `${left}px`;
      floating.style.visibility = "visible";
    };

    const hideFloating = () => {
      if (floating) {
        floating.remove();
        floating = null;
        trigger.classList.remove("has-floating");
      }
    };

    trigger.addEventListener("mouseenter", showFloating);
    trigger.addEventListener("mouseleave", hideFloating);
    trigger.addEventListener("focusin", showFloating);
    trigger.addEventListener("focusout", hideFloating);
    window.addEventListener("scroll", hideFloating, { passive: true });
    window.addEventListener("resize", hideFloating);
  });
}

const attachErrorTooltip = (trigger) => {
  const tip = trigger.querySelector(".tooltiptext.error-tooltiptext");
  if (!tip) return;

  const floating = tip.cloneNode(true);
  floating.classList.remove("tooltiptext");
  floating.classList.add("floating-error-tooltip");
  floating.style.position = "absolute";
  document.body.appendChild(floating);

  const positionFloating = () => {
    const rect = trigger.getBoundingClientRect();
    const fRect = floating.getBoundingClientRect();
    const gap = 6;
    let top = rect.top + window.scrollY - fRect.height - gap;
    let left = rect.left + window.scrollX + rect.width / 2 - fRect.width / 2;
    const pad = 8;
    const maxLeft =
      window.scrollX + document.documentElement.clientWidth - fRect.width - pad;
    left = Math.max(window.scrollX + pad, Math.min(left, maxLeft));

    if (top < window.scrollY + pad) {
      top = rect.bottom + window.scrollY + gap;
    }

    floating.style.top = `${top}px`;
    floating.style.left = `${left}px`;
  };

  const showFloating = () => {
    positionFloating();
    floating.style.visibility = "visible";
    floating.style.opacity = "1";
  };

  const hideFloating = () => {
    floating.style.visibility = "hidden";
    floating.style.opacity = "0";
  };

  trigger.addEventListener("mouseenter", showFloating);
  trigger.addEventListener("mouseleave", hideFloating);
  trigger.addEventListener("focusin", showFloating);
  trigger.addEventListener("focusout", hideFloating);
  window.addEventListener("scroll", hideFloating, { passive: true });
  window.addEventListener("resize", () => {
    positionFloating();
    hideFloating();
  });
};

function attachErrorTooltips(root = document) {
  if (!root) return;
  root
    .querySelectorAll(".tooltip.timestamp-text.error-timestamp")
    .forEach(attachErrorTooltip);
}

const attachTimestampTooltip = (trigger) => {
  if (!trigger || trigger.dataset.timestampTooltipInitialized === "true")
    return;
  const tip = trigger.querySelector(".timestamp-tooltiptext");
  if (!tip) return;
  trigger.dataset.timestampTooltipInitialized = "true";
  tip.classList.add("timestamp-tooltip-detached");

  let floating = null;

  const ensureFloating = () => {
    if (floating) return;
    floating = tip.cloneNode(true);
    floating.classList.remove("timestamp-tooltiptext");
    floating.classList.add("floating-timestamp-tooltip");
    floating.style.position = "absolute";
    floating.style.visibility = "hidden";
    floating.style.opacity = "0";
    document.body.appendChild(floating);
  };

  const positionFloating = () => {
    if (!floating) return;
    const rect = trigger.getBoundingClientRect();
    const fRect = floating.getBoundingClientRect();
    const gap = 6;
    let top = rect.bottom + window.scrollY + gap;
    let left = rect.left + window.scrollX + rect.width / 2 - fRect.width / 2;
    const pad = 8;
    const maxLeft =
      window.scrollX + document.documentElement.clientWidth - fRect.width - pad;
    left = Math.max(window.scrollX + pad, Math.min(left, maxLeft));
    const viewportHeight =
      window.innerHeight || document.documentElement.clientHeight;
    const maxTop =
      window.scrollY +
      viewportHeight -
      fRect.height -
      pad;
    if (top > maxTop) {
      top = rect.top + window.scrollY - fRect.height - gap;
    }
    if (top < window.scrollY + pad) {
      top = window.scrollY + pad;
    }
    floating.style.top = `${top}px`;
    floating.style.left = `${left}px`;
  };

  const showFloating = () => {
    if (
      !tip ||
      tip.classList.contains("tooltip-hidden") ||
      tip.getAttribute("aria-hidden") === "true"
    ) {
      hideFloating();
      return;
    }
    const text = tip.textContent?.trim();
    if (!text) {
      hideFloating();
      return;
    }
    ensureFloating();
    floating.textContent = text;
    positionFloating();
    floating.style.visibility = "visible";
    floating.style.opacity = "1";
  };

  const hideFloating = () => {
    if (!floating) return;
    floating.style.visibility = "hidden";
    floating.style.opacity = "0";
  };

  trigger.addEventListener("mouseenter", showFloating);
  trigger.addEventListener("mouseleave", hideFloating);
  trigger.addEventListener("focusin", showFloating);
  trigger.addEventListener("focusout", hideFloating);
  window.addEventListener("scroll", hideFloating, { passive: true });
  window.addEventListener("resize", () => {
    positionFloating();
    hideFloating();
  });
};

function attachTimestampTooltips(root = document) {
  if (!root) return;
  root.querySelectorAll(".tooltip.timestamp-text").forEach((trigger) => {
    attachTimestampTooltip(trigger);
  });
}

function attachMenuToggle(toggle) {
  if (toggle.dataset.menuInitialized === "true") {
    return;
  }
  toggle.dataset.menuInitialized = "true";
  toggle.addEventListener("click", function (e) {
    e.stopPropagation();

    document
      .querySelectorAll(".menu-actions.active")
      .forEach((m) => m.remove());

    const container = this.closest(".menu-container");
    const url = container.dataset.url;
    const menu = container.querySelector(".menu-actions");

    const clone = menu.cloneNode(true);
    clone.classList.add("active");
    clone.style.position = "absolute";
    clone.style.visibility = "hidden";
    document.body.appendChild(clone);

    const rect = this.getBoundingClientRect();
    const cloneRect = clone.getBoundingClientRect();
    const top = rect.top + window.scrollY - cloneRect.height;
    const left =
      rect.left + window.scrollX + rect.width / 2 - cloneRect.width / 2;
    clone.style.top = `${top}px`;
    clone.style.left = `${left}px`;
    clone.style.visibility = "visible";

    const editBtn = clone.querySelector("button.edit");
    const favoriteBtn = clone.querySelector("button.favorite");
    const recheckBtn = clone.querySelector("button.recheck");
    const historyBtn = clone.querySelector("button.history");
    const deleteBtn = clone.querySelector("button.danger");

    if (editBtn)
      editBtn.addEventListener("click", (ev) => {
        ev.stopPropagation();
        editChapter(url);
        clone.remove();
      });
    if (recheckBtn)
      recheckBtn.addEventListener("click", (ev) => {
        ev.stopPropagation();
        recheckChapter(url);
        clone.remove();
      });
    if (favoriteBtn)
      favoriteBtn.addEventListener("click", (ev) => {
        ev.stopPropagation();
        toggleFavorite(url, container);
        clone.remove();
      });
    if (historyBtn)
      historyBtn.addEventListener("click", (ev) => {
        ev.stopPropagation();
        const supportsFree = container.dataset.supportsFree === "true";
        viewHistory(url, supportsFree);
        clone.remove();
      });
    if (deleteBtn)
      deleteBtn.addEventListener("click", (ev) => {
        ev.stopPropagation();
        removeLinkByUrl(url);
        clone.remove();
      });

    const closeMenu = () => {
      clone.remove();
      document.removeEventListener("click", closeMenu);
    };
    setTimeout(() => document.addEventListener("click", closeMenu), 0);

    clone.addEventListener("mouseleave", () => clone.remove());
  });
}

function initRowEnhancements(root = document) {
  if (!root) return;
  setupDomainTooltips(root);
  setupFloatingTooltips(root);
  attachErrorTooltips(root);
  attachTimestampTooltips(root);
  root
    .querySelectorAll(".menu-toggle")
    .forEach((toggle) => attachMenuToggle(toggle));
  updateRelativeTimestamps(root);
}

async function refreshChapterTables() {
  const category = getCurrentCategory();
  const response = await fetch(
    `/api/chapters?category=${encodeURIComponent(category)}`
  );
  if (!response.ok) {
    throw new Error("Unable to refresh chapters");
  }
  const payload = await response.json();
  const newBadge = document.getElementById("newChaptersBadge");
  const newContent = document.getElementById("newChaptersContent");
  const sameBadge = document.getElementById("sameChaptersBadge");
  const sameContent = document.getElementById("sameChaptersContent");
  if (newBadge) newBadge.textContent = payload.differences.count;
  if (newContent) {
    newContent.innerHTML = payload.differences.html;
    initRowEnhancements(newContent);
  }
  if (sameBadge) sameBadge.textContent = payload.same_data.count;
  if (sameContent) {
    sameContent.innerHTML = payload.same_data.html;
    initRowEnhancements(sameContent);
  }
  if (payload.nav && Array.isArray(payload.nav.categories)) {
    if (payload.nav.current) {
      window.currentNavInfo = payload.nav.current;
    }
    renderCategoryNav(payload.nav.categories);
  }
  updateLastUpdateTooltip(payload.last_full_update);
  return payload;
}

function renderCategoryManagerList() {
  const container = document.getElementById("categoryManagerList");
  if (!container) return;
  container.innerHTML = "";
  categoryData.forEach((cat) =>
    container.appendChild(buildCategoryRow(cat, false))
  );
  updateCategoryReorderControls();
}

function getExistingCategoryRows() {
  const container = document.getElementById("categoryManagerList");
  if (!container) return [];
  return Array.from(container.querySelectorAll(".category-table__row")).filter(
    (row) => row.dataset.mode !== "new"
  );
}

function updateCategoryReorderControls() {
  const rows = getExistingCategoryRows();
  rows.forEach((row, index) => {
    const upBtn = row.querySelector(".category-move-btn.up");
    const downBtn = row.querySelector(".category-move-btn.down");
    if (upBtn) upBtn.disabled = index === 0;
    if (downBtn) downBtn.disabled = index === rows.length - 1;
  });
  const container = document.getElementById("categoryManagerList");
  if (!container) return;
  container
    .querySelectorAll(
      '.category-table__row[data-mode="new"] .category-move-btn'
    )
    .forEach((btn) => {
      btn.disabled = true;
    });
}

function buildCategoryOrderPayload() {
  return getExistingCategoryRows()
    .map((row) => (row.dataset.originalName || "").trim().toLowerCase())
    .filter(Boolean);
}

function enqueueCategoryReorder(order) {
  if (!Array.isArray(order) || order.length < 2) {
    return;
  }
  categoryReorderQueue = categoryReorderQueue
    .catch(() => {})
    .then(() => persistCategoryOrder(order));
}

async function persistCategoryOrder(order) {
  if (!Array.isArray(order) || order.length < 2) {
    return;
  }
  try {
    const res = await fetch("/api/categories/reorder", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ order }),
    });
    const data = await res.json();
    if (!res.ok || data.status !== "success") {
      throw new Error(data.error || "Unable to reorder categories");
    }
    if (Array.isArray(data.categories)) {
      categoryData = data.categories;
      renderCategoryNav(categoryData);
      setPrefixesFromCategories(categoryData);
    }
  } catch (err) {
    console.error(err);
    alert(err.message || "Unable to reorder categories.");
  } finally {
    updateCategoryReorderControls();
  }
}

function moveCategoryRow(row, direction) {
  if (!row || row.dataset.mode === "new") return;
  const container = document.getElementById("categoryManagerList");
  if (!container) return;
  const rows = getExistingCategoryRows();
  const currentIndex = rows.indexOf(row);
  if (currentIndex === -1) return;
  const targetIndex = direction === "up" ? currentIndex - 1 : currentIndex + 1;
  if (targetIndex < 0 || targetIndex >= rows.length) return;
  const targetRow = rows[targetIndex];
  if (direction === "up") {
    container.insertBefore(row, targetRow);
  } else {
    container.insertBefore(
      row,
      targetRow.nextElementSibling ? targetRow.nextElementSibling : null
    );
  }
  updateCategoryReorderControls();
  const order = buildCategoryOrderPayload();
  enqueueCategoryReorder(order);
}

function hasRowChanged(row) {
  const slug = row.querySelector(".category-input-slug")?.value.trim() || "";
  const display =
    row.querySelector(".category-input-display")?.value.trim() || "";
  const interval =
    row.querySelector(".category-input-interval")?.value.trim() || "1";
  const include = row.querySelector(".category-input-include")?.checked;
  const payload = {
    name: slug.toLowerCase(),
    display_name: display,
    update_interval_hours: interval,
    include_in_nav: include,
  };
  const originalName = row.dataset.originalName || slug;
  const originalDisplay = row.dataset.originalDisplay || "";
  const originalInterval = row.dataset.originalInterval || "1";
  const originalInclude =
    row.dataset.originalInclude === undefined
      ? "true"
      : row.dataset.originalInclude;
  return (
    row.dataset.mode === "new" ||
    payload.name !== originalName ||
    payload.display_name !== originalDisplay ||
    String(payload.update_interval_hours) !== originalInterval ||
    String(payload.include_in_nav) !== originalInclude
  );
}

function buildCategoryRow(cat, isNew) {
  const row = document.createElement("tr");
  row.className = "category-table__row";
  if (isNew) {
    row.classList.add("new-row");
  }
  row.dataset.mode = isNew ? "new" : "existing";
  row.dataset.originalName = cat?.name || "";
  row.dataset.originalDisplay = cat?.display_name || "";
  row.dataset.originalInterval = String(cat?.update_interval_hours || 1);
  row.dataset.originalInclude = String(
    cat?.include_in_nav === undefined ? true : !!cat.include_in_nav
  );
  const reorderCell = document.createElement("td");
  reorderCell.className = "category-table__reorder";
  const reorderControls = document.createElement("div");
  reorderControls.className = "category-reorder-controls";
  const moveUpBtn = document.createElement("button");
  moveUpBtn.type = "button";
  moveUpBtn.className = "category-move-btn up";
  moveUpBtn.innerHTML = '<i class="fas fa-chevron-up"></i>';
  moveUpBtn.addEventListener("click", () => moveCategoryRow(row, "up"));
  const moveDownBtn = document.createElement("button");
  moveDownBtn.type = "button";
  moveDownBtn.className = "category-move-btn down";
  moveDownBtn.innerHTML = '<i class="fas fa-chevron-down"></i>';
  moveDownBtn.addEventListener("click", () => moveCategoryRow(row, "down"));
  reorderControls.appendChild(moveUpBtn);
  reorderControls.appendChild(moveDownBtn);
  reorderCell.appendChild(reorderControls);
  if (isNew) {
    reorderCell.classList.add("category-reorder-disabled");
    moveUpBtn.disabled = true;
    moveDownBtn.disabled = true;
    reorderCell.title = "Save category to reorder";
  }

  const slugCell = document.createElement("td");
  const slugInput = document.createElement("input");
  slugInput.type = "text";
  slugInput.value = cat?.name || "";
  slugInput.placeholder = "identifier";
  slugInput.setAttribute("aria-label", "Category ID");
  slugInput.className = "category-input-slug";
  const isMain = (cat?.name || "").toLowerCase() === "main";
  slugInput.disabled = !isNew && isMain;
  slugCell.appendChild(slugInput);

  const displayCell = document.createElement("td");
  const displayInput = document.createElement("input");
  displayInput.type = "text";
  displayInput.value = cat?.display_name || "";
  displayInput.placeholder = "Display name";
  displayInput.className = "category-input-display";
  displayInput.setAttribute("aria-label", "Display name");
  displayCell.appendChild(displayInput);

  const intervalCell = document.createElement("td");
  const intervalInput = document.createElement("input");
  intervalInput.type = "number";
  intervalInput.min = "1";
  intervalInput.step = "1";
  intervalInput.value = cat?.update_interval_hours || 1;
  intervalInput.className = "category-input-interval";
  intervalInput.setAttribute("aria-label", "Update interval (hours)");
  intervalCell.appendChild(intervalInput);

  const includeCell = document.createElement("td");
  includeCell.className = "category-table__toggle";
  const includeWrapper = document.createElement("label");
  includeWrapper.className =
    "checkbox-field category-checkbox table-tooltip tooltip-top";
  const includeInput = document.createElement("input");
  includeInput.type = "checkbox";
  includeInput.checked =
    isNew || cat?.include_in_nav === undefined ? true : !!cat.include_in_nav;
  includeInput.className = "category-input-include";
  includeInput.setAttribute("aria-label", "Show in navigation");
  const includeIndicator = document.createElement("span");
  includeIndicator.className = "custom-checkbox";
  includeIndicator.setAttribute("aria-hidden", "true");
  const includeTooltip = document.createElement("span");
  includeTooltip.className = "tooltiptext";
  includeTooltip.textContent = "Show in navigation";
  includeWrapper.appendChild(includeInput);
  includeWrapper.appendChild(includeIndicator);
  includeWrapper.appendChild(includeTooltip);
  includeCell.appendChild(includeWrapper);

  const actionsCell = document.createElement("td");
  const actionsWrapper = document.createElement("div");
  actionsWrapper.className = "category-table__actions";
  const saveBtn = document.createElement("button");
  saveBtn.type = "button";
  saveBtn.innerHTML = '<i class="fas fa-save"></i>';
  saveBtn.classList.add("category-save-btn", "table-tooltip", "tooltip-top");
  saveBtn.disabled = !isNew;
  const saveTooltip = document.createElement("span");
  saveTooltip.className = "tooltiptext";
  saveTooltip.textContent = "Save";
  saveBtn.appendChild(saveTooltip);
  const deleteBtn = document.createElement("button");
  deleteBtn.type = "button";
  deleteBtn.innerHTML = '<i class="fas fa-trash"></i>';
  deleteBtn.classList.add("danger", "table-tooltip", "tooltip-top");
  const deleteTooltip = document.createElement("span");
  deleteTooltip.className = "tooltiptext";
  deleteTooltip.textContent = "Delete";
  deleteBtn.appendChild(deleteTooltip);
  if (!isNew && isMain) {
    deleteBtn.disabled = true;
    deleteBtn.classList.add("disabled");
    deleteBtn.title = "Main category cannot be removed";
  }

  saveBtn.addEventListener("click", () => saveCategoryRow(row));
  deleteBtn.addEventListener("click", () => deleteCategoryRow(row));

  const inputs = [slugInput, displayInput, intervalInput, includeInput].filter(
    Boolean
  );
  inputs.forEach((input) => {
    input.addEventListener("input", () => {
      saveBtn.disabled = !hasRowChanged(row);
    });
    input.addEventListener("change", () => {
      saveBtn.disabled = !hasRowChanged(row);
    });
  });
  actionsWrapper.appendChild(saveBtn);
  actionsWrapper.appendChild(deleteBtn);
  actionsCell.appendChild(actionsWrapper);

  row.appendChild(reorderCell);
  row.appendChild(slugCell);
  row.appendChild(displayCell);
  row.appendChild(intervalCell);
  row.appendChild(includeCell);
  row.appendChild(actionsCell);
  return row;
}

async function saveCategoryRow(row) {
  const slug = row.querySelector(".category-input-slug")?.value.trim() || "";
  const display = row.querySelector(".category-input-display")?.value.trim();
  const intervalValue =
    row.querySelector(".category-input-interval")?.value.trim() || "1";
  const includeFlag = row.querySelector(".category-input-include")?.checked;

  if (!slug) {
    alert("Category ID is required.");
    return;
  }

  const payload = {
    name: slug.toLowerCase(),
    display_name: display,
    update_interval_hours: intervalValue,
    include_in_nav: includeFlag,
  };
  const isNew = row.dataset.mode === "new";
  const originalName = row.dataset.originalName || slug;
  const originalDisplay = row.dataset.originalDisplay || "";
  const originalInterval = row.dataset.originalInterval || "1";
  const originalInclude =
    row.dataset.originalInclude === undefined
      ? "true"
      : row.dataset.originalInclude;
  const url = isNew
    ? "/api/categories"
    : `/api/categories/${encodeURIComponent(originalName)}`;
  const method = isNew ? "POST" : "PUT";
  const saveBtn = row.querySelector(".category-save-btn");

  if (!hasRowChanged(row)) {
    if (saveBtn) saveBtn.disabled = true;
    return;
  }

  try {
    if (saveBtn) saveBtn.disabled = true;
    const res = await fetch(url, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok || data.status !== "success") {
      throw new Error(data.error || "Unable to save category");
    }
    await refreshCategoriesFromServer();
  } catch (err) {
    console.error(err);
    alert(err.message || "Unable to save category.");
  } finally {
    if (saveBtn) saveBtn.disabled = true;
  }
}

async function deleteCategoryRow(row) {
  const isNew = row.dataset.mode === "new";
  if (isNew) {
    row.remove();
    return;
  }
  const name = row.dataset.originalName;
  if (!name || name === "main") {
    return;
  }
  if (!confirm(`Delete category "${name}"? This removes its links.`)) {
    return;
  }
  try {
    const res = await fetch(`/api/categories/${encodeURIComponent(name)}`, {
      method: "DELETE",
    });
    const data = await res.json();
    if (!res.ok || data.status !== "success") {
      throw new Error(data.error || "Unable to delete category");
    }
    await refreshCategoriesFromServer();
  } catch (err) {
    console.error(err);
    alert(err.message || "Unable to delete category.");
  }
}

function hideHistoryModal() {
  const backdrop = document.getElementById("historyModalBackdrop");
  if (!backdrop) return;
  hideModalElement(backdrop);
}

function openHistoryModal(data, supportsFree) {
  const backdrop = document.getElementById("historyModalBackdrop");
  if (!backdrop) return;
  historyContext = {
    url: data.url,
    supportsFree: Boolean(supportsFree),
  };
  const title = document.getElementById("historyModalTitle");
  const addedAt = document.getElementById("historyAddedAt");
  const lastAttempt = document.getElementById("historyLastAttempt");
  const freqPill = document.getElementById("historyFrequencyPill");
  const freePill = document.getElementById("historyFreeOnlyPill");
  const list = document.getElementById("historyList");

  if (title) title.textContent = data.name || data.url || "Link history";
  if (addedAt) addedAt.textContent = formatDateTime(data.added_at);
  if (lastAttempt) lastAttempt.textContent = formatDateTime(data.last_attempt);
  if (freqPill)
    freqPill.textContent = data.update_frequency
      ? `Every ${data.update_frequency} day${
          data.update_frequency === 1 ? "" : "s"
        }`
      : "Frequency unknown";
  if (freePill) {
    if (supportsFree) {
      freePill.style.display = "inline-flex";
      freePill.textContent = data.free_only ? "Free only" : "Include paid";
    } else {
      freePill.style.display = "none";
    }
  }
  if (list) {
    list.textContent = "";
    if (!Array.isArray(data.history) || data.history.length === 0) {
      const empty = document.createElement("p");
      empty.className = "history-empty";
      empty.textContent = "No historical chapters recorded yet.";
      list.appendChild(empty);
    } else {
      data.history.forEach((entry) => {
        const entryEl = document.createElement("div");
        entryEl.className = "history-entry";
        const isCurrent =
          data.last_saved &&
          data.last_saved !== "N/A" &&
          entry.last_found === data.last_saved;
        if (isCurrent) entryEl.classList.add("current");

        const titleEl = document.createElement("div");
        titleEl.className = "history-entry__title";
        titleEl.textContent = entry.last_found || "No chapter data";

        const metaEl = document.createElement("div");
        metaEl.className = "history-entry__meta";
        const timestampEl = document.createElement("span");
        timestampEl.textContent = entry.timestamp || "Date unknown";
        const retrievedEl = document.createElement("span");
        retrievedEl.textContent = `Fetched: ${formatDateTime(
          entry.retrieved_at
        )}`;
        metaEl.appendChild(timestampEl);
        metaEl.appendChild(retrievedEl);

        const contentEl = document.createElement("div");
        contentEl.className = "history-entry__content";
        contentEl.appendChild(titleEl);
        contentEl.appendChild(metaEl);

        const actionsEl = document.createElement("div");
        actionsEl.className = "history-entry__actions";
        const deleteWrapper = document.createElement("div");
        deleteWrapper.className = "table-tooltip";
        const deleteBtn = document.createElement("button");
        deleteBtn.className =
          "history-entry__action history-entry__action--delete";
        const tooltip = document.createElement("span");
        tooltip.className = "tooltiptext";
        const locked = entry.is_latest || isCurrent;
        if (locked) {
          deleteBtn.innerHTML = '<i class="fas fa-lock"></i>';
          tooltip.textContent = entry.is_latest ? "Latest" : "Saved";
        } else {
          deleteBtn.innerHTML = '<i class="fas fa-trash"></i>';
          tooltip.textContent = "Delete";
          deleteBtn.addEventListener("click", (ev) => {
            ev.stopPropagation();
            if (
              confirm(
                "Delete this historical chapter entry? This cannot be undone."
              )
            ) {
              deleteHistoryEntry(entry.entry_id);
            }
          });
        }
        deleteBtn.disabled = locked;
        deleteWrapper.appendChild(deleteBtn);
        deleteWrapper.appendChild(tooltip);
        actionsEl.appendChild(deleteWrapper);

        entryEl.appendChild(contentEl);
        entryEl.appendChild(actionsEl);

        entryEl.dataset.entryId = entry.entry_id || "";
        entryEl.classList.toggle("is-clickable", !isCurrent);
        if (!isCurrent) {
          entryEl.addEventListener("click", () =>
            saveHistoryEntry(entry.entry_id)
          );
        } else {
          entryEl.removeAttribute("title");
        }
        list.appendChild(entryEl);
      });
    }
    setupFloatingTooltips(list);
  }

  showModalElement(backdrop);
}

async function fetchHistory(url) {
  const path = actionPath("history");
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.status || "Unable to load history");
  }
  return payload;
}

async function refreshHistoryModal() {
  if (!historyContext) return;
  try {
    const data = await fetchHistory(historyContext.url);
    openHistoryModal(data, historyContext.supportsFree);
  } catch (error) {
    console.error("Error refreshing history:", error);
    alert("Unable to refresh history.");
  }
}

async function performHistoryAction(action, payload, spinnerMessage) {
  if (!historyContext) return;
  showSpinner(spinnerMessage);
  try {
    const response = await fetch(actionPath(action), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: historyContext.url, ...payload }),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || data.status || "Unable to perform action");
    }
    await refreshHistoryModal();
    await refreshChapterTables().catch((error) =>
      console.error("Error refreshing chapters after history action:", error)
    );
  } catch (error) {
    console.error("Error performing history action:", error);
    alert("Unable to perform history action.");
  } finally {
    hideSpinner();
  }
}

function saveHistoryEntry(entryId) {
  if (!entryId) return;
  performHistoryAction(
    "history/set_saved",
    { entry_id: entryId },
    "Saving history entry..."
  );
}

function deleteHistoryEntry(entryId) {
  if (!entryId) return;
  performHistoryAction(
    "history/delete",
    { entry_id: entryId },
    "Deleting history entry..."
  );
}

function viewHistory(url, supportsFree) {
  historyContext = {
    url,
    supportsFree: Boolean(supportsFree),
  };
  showSpinner("Loading history...");
  fetchHistory(url)
    .then((data) => openHistoryModal(data, supportsFree))
    .catch((error) => {
      console.error("Error loading history:", error);
      alert("Unable to load history.");
    })
    .finally(() => hideSpinner());
}

function forceUpdate() {
  showSpinner("Fully updating database...");
  const path = actionPath("force_update");
  fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  })
    .then((response) => response.json())
    .catch((error) => {
      console.error("Error forcing update:", error);
      hideSpinner();
    });
}

// ===== On page load =====
window.onload = function () {
  if (update_in_progress) {
    showSpinner("Update in progress...");
  } else {
    hideSpinner();
  }
};

// ===== Collapse Tables =====
const SECTION_STATE_PREFIX = "chapter-tracker-sections";

function getSectionStorageKey() {
  const category = document.body?.dataset.category || "main";
  return `${SECTION_STATE_PREFIX}-${category}`;
}

function readSectionStates() {
  if (typeof window === "undefined" || !window.localStorage) return {};
  try {
    const stored = window.localStorage.getItem(getSectionStorageKey());
    return stored ? JSON.parse(stored) : {};
  } catch (err) {
    console.warn("Unable to read section state:", err);
    return {};
  }
}

function persistSectionState(sectionId, collapsed) {
  if (!sectionId || typeof window === "undefined" || !window.localStorage) {
    return;
  }
  try {
    const key = getSectionStorageKey();
    const state = readSectionStates();
    state[sectionId] = collapsed;
    window.localStorage.setItem(key, JSON.stringify(state));
  } catch (err) {
    console.warn("Unable to persist section state:", err);
  }
}

function applyCollapseState(
  header,
  content,
  collapsed,
  disableAnimation = false
) {
  if (disableAnimation) {
    content.classList.add("no-transition");
    if (header) header.classList.add("no-transition");
  }
  if (collapsed) content.classList.add("collapsed");
  else content.classList.remove("collapsed");
  if (disableAnimation)
    requestAnimationFrame(() => {
      content.classList.remove("no-transition");
      if (header) header.classList.remove("no-transition");
    });
}

function toggleSection(header) {
  const content = header.closest(".table-header").nextElementSibling;
  if (!content) return;
  const collapsed = !content.classList.contains("collapsed");
  applyCollapseState(header, content, collapsed);
  const sectionId = header.dataset.section;
  persistSectionState(sectionId, collapsed);
}

document.addEventListener("DOMContentLoaded", function () {
  configureRelativeTime();
  const initialLastUpdate = document.body?.dataset.lastUpdate || null;
  updateLastUpdateTooltip(initialLastUpdate);

  const savedSectionStates = readSectionStates();
  document.querySelectorAll(".table-header h2.toggle").forEach((header) => {
    const sectionId = header.dataset.section;
    if (!sectionId) return;
    const content = header.closest(".table-header").nextElementSibling;
    if (!content) return;
    if (!(sectionId in savedSectionStates)) return;
    const shouldCollapse = !!savedSectionStates[sectionId];
    applyCollapseState(header, content, shouldCollapse, true);
  });

  initRowEnhancements(document);

  // ===== Keep-floating-tooltips-clean =====
  // remove all floating clones and restore originals
  function hideAllFloatingTooltips() {
    document
      .querySelectorAll(".tooltiptext.floating")
      .forEach((n) => n.remove());
    document
      .querySelectorAll(".table-tooltip.has-floating")
      .forEach((t) => t.classList.remove("has-floating"));
    document.querySelectorAll(".floating-error-tooltip").forEach((n) => {
      n.style.visibility = "hidden";
      n.style.opacity = "0";
    });
    document.querySelectorAll(".floating-timestamp-tooltip").forEach((n) => {
      n.style.visibility = "hidden";
      n.style.opacity = "0";
    });
  }

  // Throttled mousemove check: if pointer is not over a tooltip trigger, hide clones.
  (function () {
    let scheduled = false;
    document.addEventListener(
      "mousemove",
      (ev) => {
        if (scheduled) return;
        scheduled = true;
        requestAnimationFrame(() => {
          scheduled = false;
          const el = document.elementFromPoint(ev.clientX, ev.clientY);
          let isTooltipArea = false;
          if (el) {
            isTooltipArea =
              el.closest(".table-tooltip") ||
              el.closest(".tooltip.timestamp-text") ||
              el.closest(".tooltiptext.error-tooltiptext") ||
              el.closest(".floating-error-tooltip") ||
              el.closest(".menu-actions") ||
              el.closest(".menu-toggle");
          }
          if (!el || !isTooltipArea) {
            hideAllFloatingTooltips();
          }
        });
      },
      { passive: true }
    );

    ["pointerdown", "click", "auxclick", "scroll", "resize"].forEach((ev) =>
      document.addEventListener(ev, hideAllFloatingTooltips, { passive: true })
    );
    document.addEventListener("visibilitychange", hideAllFloatingTooltips);
    window.addEventListener("pagehide", hideAllFloatingTooltips);
    window.addEventListener("beforeunload", hideAllFloatingTooltips);
    window.addEventListener("blur", hideAllFloatingTooltips);
  })();
});

// Floating add modal logic
document.addEventListener("DOMContentLoaded", function () {
  const floatingBtn = document.getElementById("floatingAddBtn");
  const addModal = document.getElementById("addModal");
  const backdrop = document.getElementById("addModalBackdrop");
  const modalName = document.getElementById("modalName");
  const modalUrl = document.getElementById("modalUrl");
  const modalFrequency = document.getElementById("modalFrequency");
  const modalAddBtn = document.getElementById("modalAddBtn");
  const modalCancelBtn = document.getElementById("modalCancelBtn");
  const modalTitle = document.getElementById("addModalTitle");
  const modalFreeOnly = document.getElementById("modalFreeOnly");
  const modalFreeOnlyWrapper = modalFreeOnly
    ? modalFreeOnly.closest(".modal-checkbox")
    : null;
  const modalCategory = document.getElementById("modalCategory");
  const modalCategoryWrapper = document.getElementById("modalCategoryWrapper");

  function populateModalCategoryOptions(selectedValue) {
    if (!modalCategory) return;
    const categories =
      Array.isArray(categoryData) && categoryData.length
        ? categoryData
        : [{ name: getCurrentCategory(), display_name: getCurrentCategory() }];
    modalCategory.innerHTML = "";
    categories.forEach((cat) => {
      if (!cat || !cat.name) return;
      const option = document.createElement("option");
      option.value = cat.name;
      option.textContent = cat.display_name || cat.name;
      modalCategory.appendChild(option);
    });
    if (selectedValue) {
      const match = categories.find((cat) => cat && cat.name === selectedValue);
      if (match) {
        modalCategory.value = selectedValue;
      }
    }
    if (!modalCategory.value && modalCategory.options.length) {
      modalCategory.selectedIndex = 0;
    }
  }

  function toggleCategoryPicker(show, selectedValue) {
    if (!modalCategoryWrapper) return;
    modalCategoryWrapper.classList.toggle("hidden", !show);
    if (show) {
      populateModalCategoryOptions(selectedValue);
    } else if (modalCategory) {
      modalCategory.value = "";
    }
  }

  function resetModalFields() {
    if (modalName) modalName.value = "";
    if (modalUrl) modalUrl.value = "";
    if (modalFrequency) modalFrequency.value = "";
    if (modalFreeOnly) modalFreeOnly.checked = false;
    if (modalFreeOnlyWrapper) modalFreeOnlyWrapper.classList.remove("hidden");
    toggleCategoryPicker(false);
  }

  function setFreeOnlyVisibility(show) {
    if (!modalFreeOnlyWrapper) return;
    modalFreeOnlyWrapper.classList.toggle("hidden", !show);
  }

  function openAddModal(showFreeOnly = true, selectedCategory = null) {
    const isEditMode = modalAddBtn && modalAddBtn.dataset.mode === "edit";
    if (modalTitle)
      modalTitle.textContent = isEditMode ? "Edit Link" : "Add New Link";
    if (!isEditMode && modalFreeOnly) modalFreeOnly.checked = false;
    setFreeOnlyVisibility(showFreeOnly);
    toggleCategoryPicker(isEditMode, selectedCategory || getCurrentCategory());
    showModalElement(addModal);
    setTimeout(() => modalName && modalName.focus(), 50);
  }

  function closeAddModal() {
    hideModalElement(addModal);
    resetModalFields();
    if (modalAddBtn) {
      delete modalAddBtn.dataset.mode;
      delete modalAddBtn.dataset.origUrl;
      modalAddBtn.innerHTML = '<i class="fas fa-plus"></i> Add';
    }
    if (modalTitle) modalTitle.textContent = "Add New Link";
  }

  if (floatingBtn)
    floatingBtn.addEventListener("click", () => openAddModal(true));
  if (backdrop) backdrop.addEventListener("click", closeAddModal);
  if (modalCancelBtn) modalCancelBtn.addEventListener("click", closeAddModal);

  // submit from modal (add or edit)
  async function submitModalAdd() {
    const name = modalName ? modalName.value.trim() : "";
    const url = modalUrl ? modalUrl.value.trim() : "";
    if (!name || !url) return alert("Please enter both name and URL.");
    const freqValue = modalFrequency ? modalFrequency.value.trim() : "";
    const payload = {
      name,
      url,
      free_only: modalFreeOnly ? modalFreeOnly.checked : false,
    };
    if (freqValue) {
      payload.update_frequency = freqValue;
    }
    const isEdit = modalAddBtn && modalAddBtn.dataset.mode === "edit";
    const path = actionPath(isEdit ? "edit" : "add");
    let targetCategory = null;
    if (
      isEdit &&
      modalCategory &&
      modalCategoryWrapper &&
      !modalCategoryWrapper.classList.contains("hidden")
    ) {
      targetCategory = modalCategory.value;
    }
    const body = isEdit
      ? JSON.stringify({
          original_url: modalAddBtn.dataset.origUrl,
          target_category: targetCategory,
          ...payload,
        })
      : JSON.stringify(payload);

    try {
      if (modalAddBtn) modalAddBtn.disabled = true;
      const res = await fetch(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body,
      });
      const data = await res.json();
      if (data.status === "success") {
        closeAddModal();
        refreshChapterTables().catch((error) =>
          console.error("Error refreshing chapters after add/edit:", error)
        );
      } else {
        alert(isEdit ? "Failed to edit link." : "Failed to add link.");
      }
    } catch (err) {
      console.error("Error submitting modal:", err);
      alert("Error submitting.");
    } finally {
      if (modalAddBtn) modalAddBtn.disabled = false;
    }
  }

  if (modalAddBtn) modalAddBtn.addEventListener("click", submitModalAdd);

  // open modal in edit mode for a given url
  window.editChapter = function (url) {
    const container = Array.from(
      document.querySelectorAll(".menu-container")
    ).find((c) => c.dataset.url === url);
    let name = "";
    if (container && container.dataset.name) name = container.dataset.name;
    if (!name) {
      const row = container ? container.closest("tr") : null;
      const titleLink = row ? row.querySelector(".domain-tooltip a") : null;
      if (titleLink) name = titleLink.textContent.trim();
    }

    if (modalName) modalName.value = name || "";
    if (modalUrl) modalUrl.value = url || "";
    if (modalFrequency)
      modalFrequency.value = container?.dataset.updateFrequency || "";
    if (modalFreeOnly)
      modalFreeOnly.checked = container?.dataset.freeOnly === "true";
    if (modalAddBtn) {
      modalAddBtn.dataset.mode = "edit";
      modalAddBtn.dataset.origUrl = url || "";
      modalAddBtn.innerHTML = '<i class="fas fa-save"></i> Save';
    }
    const supportsFree = container?.dataset.supportsFree === "true";
    if (!supportsFree && modalFreeOnly) modalFreeOnly.checked = false;
    const linkCategory = container?.dataset.category || getCurrentCategory();
    openAddModal(supportsFree, linkCategory);
  };

  resetModalFields();

  [modalName, modalUrl, modalFrequency].forEach((el) => {
    if (!el) return;
    el.addEventListener("keydown", function (e) {
      if (e.key === "Enter") {
        e.preventDefault();
        submitModalAdd();
      }
      if (e.key === "Escape") {
        closeAddModal();
      }
    });
  });

  // close modal on Escape from document
  document.addEventListener("keydown", (e) => {
    if (
      e.key === "Escape" &&
      addModal &&
      !addModal.classList.contains("hidden")
    )
      closeAddModal();
  });

  const historyBackdrop = document.getElementById("historyModalBackdrop");
  if (historyBackdrop)
    historyBackdrop.addEventListener("click", (evt) => {
      if (evt.target === historyBackdrop) hideHistoryModal();
    });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") hideHistoryModal();
  });
});

document.addEventListener("DOMContentLoaded", function () {
  const settingsModal = document.getElementById("settingsModal");
  const settingsBackdrop = document.getElementById("settingsModalBackdrop");
  const openSettingsBtn = document.getElementById("openSettingsBtn");
  const closeSettingsBtn = document.getElementById("settingsCloseBtn");
  const openCategoryBtn = document.getElementById("openCategoryManagerBtn");
  const categoryModal = document.getElementById("categoryModal");
  const categoryBackdrop = document.getElementById("categoryModalBackdrop");
  const categoryCloseBtn = document.getElementById("categoryCloseBtn");
  const categoryAddRowBtn = document.getElementById("categoryAddRowBtn");
  const themeRadios = document.querySelectorAll('input[name="themeMode"]');
  const accentButtons = document.querySelectorAll(".accent-swatch");
  const relativeTimeRadios = document.querySelectorAll(
    'input[name="relativeTimeMode"]'
  );

  const storedTheme = localStorage.getItem("chapterTheme") || DEFAULT_THEME;
  const storedAccent = localStorage.getItem("chapterAccent") || DEFAULT_ACCENT;

  function openSettings() {
    showModalElement(settingsModal);
  }

  function closeSettings() {
    hideModalElement(settingsModal);
  }

  openSettingsBtn?.addEventListener("click", openSettings);
  closeSettingsBtn?.addEventListener("click", closeSettings);
  settingsBackdrop?.addEventListener("click", (evt) => {
    if (evt.target === settingsBackdrop) closeSettings();
  });

  themeRadios.forEach((radio) => {
    if (radio.value === storedTheme) {
      radio.checked = true;
    }
    radio.addEventListener("change", () => applyThemePreference(radio.value));
  });

  accentButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      const accent = btn.dataset.accent || DEFAULT_ACCENT;
      markActiveAccent(accent);
      applyAccentPreference(accent);
    });
  });
  markActiveAccent(storedAccent);
  markActiveRelativeTime(currentRelativeTime);
  relativeTimeRadios.forEach((radio) => {
    radio.addEventListener("change", () =>
      applyRelativeTimePreference(radio.value)
    );
  });

  function openCategoryModal() {
    refreshCategoriesFromServer().catch(() => renderCategoryManagerList());
    showModalElement(categoryModal);
  }

  function closeCategoryModal() {
    hideModalElement(categoryModal);
  }

  openCategoryBtn?.addEventListener("click", openCategoryModal);
  categoryCloseBtn?.addEventListener("click", closeCategoryModal);
  categoryBackdrop?.addEventListener("click", (evt) => {
    if (evt.target === categoryBackdrop) closeCategoryModal();
  });

  categoryAddRowBtn?.addEventListener("click", () => {
    const container = document.getElementById("categoryManagerList");
    if (!container) return;
    const row = buildCategoryRow(
      {
        name: "",
        display_name: "",
        update_interval_hours: 1,
        include_in_nav: true,
      },
      true
    );
    container.prepend(row);
    updateCategoryReorderControls();
    row.querySelector(".category-input-slug")?.focus();
  });

  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    if (settingsModal && !settingsModal.classList.contains("hidden")) {
      closeSettings();
    }
    if (categoryModal && !categoryModal.classList.contains("hidden")) {
      closeCategoryModal();
    }
  });
});
