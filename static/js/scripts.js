var socket = io();

let PREFIXES = [];

async function loadPrefixes() {
  const response = await fetch("/api/categories");
  const categories = await response.json();
  PREFIXES = categories.map((c) => `/${c}`);
}

loadPrefixes();

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
const getCurrentCategory = () =>
  document.body?.dataset.category || "main";

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
  hideSpinner();
  location.reload();
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
    .then((data) => hideSpinner())
    .then(() => location.reload())
    .catch((error) => {
      console.error("Error updating chapter:", error);
      hideSpinner();
    });
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
    .then((data) => hideSpinner())
    .then(() => location.reload())
    .catch((error) => {
      console.error("Error rechecking chapter:", error);
      hideSpinner();
    });
}

function addLink() {
  const name = document.getElementById("newName").value;
  const url = document.getElementById("newUrl").value;
  if (!name || !url) return alert("Please enter both name and URL.");

  const path = actionPath("add");
  fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, url }),
  })
    .then((response) => response.json())
    .then(() => location.reload())
    .catch((error) => console.error("Error adding link:", error));
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
        ? location.reload()
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
      if (data.status === "success") location.reload();
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
    .then(() => hideSpinner())
    .then(() => location.reload())
    .catch((error) => {
      console.error("Error toggling favorite:", error);
      hideSpinner();
    });
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

function hideHistoryModal() {
  const backdrop = document.getElementById("historyModalBackdrop");
  if (!backdrop) return;
  backdrop.classList.add("hidden");
}

function openHistoryModal(data, supportsFree) {
  const backdrop = document.getElementById("historyModalBackdrop");
  if (!backdrop) return;
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
      ? `Every ${data.update_frequency} day${data.update_frequency === 1 ? "" : "s"}`
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
        retrievedEl.textContent = `Fetched: ${formatDateTime(entry.retrieved_at)}`;
        metaEl.appendChild(timestampEl);
        metaEl.appendChild(retrievedEl);

        entryEl.appendChild(titleEl);
        entryEl.appendChild(metaEl);
        list.appendChild(entryEl);
      });
    }
  }

  backdrop.classList.remove("hidden");
}

function viewHistory(url, supportsFree) {
  const path = actionPath("history");
  showSpinner("Loading history...");
  fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  })
    .then(async (response) => {
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.status || "Unable to load history");
      }
      return payload;
    })
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
  if (
    !sectionId ||
    typeof window === "undefined" ||
    !window.localStorage
  ) {
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

function toggleSection(header) {
  header.classList.toggle("collapsed");
  const content = header.closest(".table-header").nextElementSibling;
  if (!content) return;
  const collapsed = content.classList.toggle("collapsed");
  const sectionId = header.dataset.section;
  persistSectionState(sectionId, collapsed);
}

document.addEventListener("DOMContentLoaded", function () {
  // show hostname in tooltip (existing)
  document.querySelectorAll(".domain-tooltip").forEach((link) => {
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

  const savedSectionStates = readSectionStates();
  document.querySelectorAll(".table-header h2.toggle").forEach((header) => {
    const sectionId = header.dataset.section;
    if (!sectionId) return;
    const content = header.closest(".table-header").nextElementSibling;
    if (!content) return;
    if (!(sectionId in savedSectionStates)) return;
    const shouldCollapse = !!savedSectionStates[sectionId];
    header.classList.toggle("collapsed", shouldCollapse);
    content.classList.toggle("collapsed", shouldCollapse);
  });

  // --- NEW: floating tooltips for .table-tooltip to avoid clipping by table wrapper ---
  document.querySelectorAll(".table-tooltip").forEach((trigger) => {
    const tip = trigger.querySelector(".tooltiptext");
    if (!tip) return;
    let floating = null;

    const showFloating = () => {
      // clone and append to body
      floating = tip.cloneNode(true);
      floating.classList.add("floating");
      floating.style.position = "absolute";
      floating.style.visibility = "hidden";
      document.body.appendChild(floating);

      // mark trigger so original tooltip is suppressed via CSS
      trigger.classList.add("has-floating");

      // measure
      const rect = trigger.getBoundingClientRect();
      const fRect = floating.getBoundingClientRect();

      // try place above centered
      const gap = 6;
      let top = rect.top + window.scrollY - fRect.height - gap;
      let left = rect.left + window.scrollX + rect.width / 2 - fRect.width / 2;

      // clamp horizontally to viewport with small padding
      const pad = 8;
      const maxLeft =
        window.scrollX +
        document.documentElement.clientWidth -
        fRect.width -
        pad;
      left = Math.max(window.scrollX + pad, Math.min(left, maxLeft));

      // if not enough space above, place below
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
        // restore original tooltip visibility
        trigger.classList.remove("has-floating");
      }
    };

    trigger.addEventListener("mouseenter", showFloating);
    trigger.addEventListener("mouseleave", hideFloating);
    trigger.addEventListener("focusin", showFloating);
    trigger.addEventListener("focusout", hideFloating);
    // remove on resize/scroll to avoid stuck elements
    window.addEventListener("scroll", hideFloating, { passive: true });
    window.addEventListener("resize", hideFloating);
  });

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

  document
    .querySelectorAll(".tooltip.timestamp-text.error-timestamp")
    .forEach(attachErrorTooltip);

  // ===== Keep-floating-tooltips-clean =====
  // remove all floating clones and restore originals
  function hideAllFloatingTooltips() {
    document
      .querySelectorAll(".tooltiptext.floating")
      .forEach((n) => n.remove());
    document
      .querySelectorAll(".table-tooltip.has-floating")
      .forEach((t) => t.classList.remove("has-floating"));
    document
      .querySelectorAll(".floating-error-tooltip")
      .forEach((n) => {
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

  document.querySelectorAll(".menu-toggle").forEach((toggle) => {
    toggle.addEventListener("click", function (e) {
      e.stopPropagation();

      // remove existing menus
      document
        .querySelectorAll(".menu-actions.active")
        .forEach((m) => m.remove());

      const container = this.closest(".menu-container");
      const url = container.dataset.url; // grab the url from original container
      const menu = container.querySelector(".menu-actions");

      // clone menu
      const clone = menu.cloneNode(true);
      clone.classList.add("active");
      clone.style.position = "absolute";
      clone.style.visibility = "hidden"; // hide while measuring
      document.body.appendChild(clone);

      // measure & position
      const rect = this.getBoundingClientRect();
      const cloneRect = clone.getBoundingClientRect();
      const top = rect.top + window.scrollY - cloneRect.height;
      const left =
        rect.left + window.scrollX + rect.width / 2 - cloneRect.width / 2;
      clone.style.top = `${top}px`;
      clone.style.left = `${left}px`;
      clone.style.visibility = "visible";

      // attach button handlers using the url from the original container
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
      const supportsFree = container.dataset.supportsFree === "true";
      if (historyBtn)
        historyBtn.addEventListener("click", (ev) => {
          ev.stopPropagation();
          viewHistory(url, supportsFree);
          clone.remove();
        });
      if (deleteBtn)
        deleteBtn.addEventListener("click", (ev) => {
          ev.stopPropagation();
          removeLinkByUrl(url);
          clone.remove();
        });

      // close on outside click
      const closeMenu = () => {
        clone.remove();
        document.removeEventListener("click", closeMenu);
      };
      setTimeout(() => document.addEventListener("click", closeMenu), 0);

      // close on mouseleave
      clone.addEventListener("mouseleave", () => clone.remove());
    });
  });
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

  function resetModalFields() {
    if (modalName) modalName.value = "";
    if (modalUrl) modalUrl.value = "";
    if (modalFrequency) modalFrequency.value = "";
    if (modalFreeOnly) modalFreeOnly.checked = false;
    if (modalFreeOnlyWrapper) modalFreeOnlyWrapper.classList.remove("hidden");
  }

  function setFreeOnlyVisibility(show) {
    if (!modalFreeOnlyWrapper) return;
    modalFreeOnlyWrapper.classList.toggle("hidden", !show);
  }

  function openAddModal(showFreeOnly = true) {
    const isEditMode = modalAddBtn && modalAddBtn.dataset.mode === "edit";
    if (modalTitle)
      modalTitle.textContent = isEditMode ? "Edit Link" : "Add New Link";
    if (!isEditMode && modalFreeOnly) modalFreeOnly.checked = false;
    setFreeOnlyVisibility(showFreeOnly);
    if (addModal) addModal.classList.remove("hidden");
    setTimeout(() => modalName && modalName.focus(), 50);
  }

  function closeAddModal() {
    if (addModal) addModal.classList.add("hidden");
    resetModalFields();
    if (modalAddBtn) {
      delete modalAddBtn.dataset.mode;
      delete modalAddBtn.dataset.origUrl;
      modalAddBtn.innerHTML = '<i class="fas fa-plus"></i> Add';
    }
    if (modalTitle) modalTitle.textContent = "Add New Link";
  }

  if (floatingBtn) floatingBtn.addEventListener("click", () => openAddModal(true));
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
    const body = isEdit
      ? JSON.stringify({
          original_url: modalAddBtn.dataset.origUrl,
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
        location.reload();
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
    openAddModal(supportsFree);
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
    if (e.key === "Escape" && addModal && !addModal.classList.contains("hidden"))
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
