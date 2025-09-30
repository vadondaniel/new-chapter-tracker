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
socket.on("update_progress", function (data) {
  showSpinner(`Updating... ${data.current}/${data.total}`);
  const fill = document.getElementById("progressFill");
  const percent = (data.current / data.total) * 100;
  fill.style.width = percent + "%";
});

socket.on("update_complete", function () {
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
function toggleSection(header) {
  header.classList.toggle("collapsed");
  const content = header.closest(".table-header").nextElementSibling;
  content.classList.toggle("collapsed");
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
      const recheckBtn = clone.querySelector("button.recheck");
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

// Example handler for edit (you can adjust to your logic)
function editChapter(url) {
  alert("Edit clicked for " + url);
}
