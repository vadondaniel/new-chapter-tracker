var socket = io();

let PREFIXES = [];

async function loadPrefixes() {
  const response = await fetch("/api/categories");
  const categories = await response.json();
  PREFIXES = categories.map(c => `/${c}`);
}

loadPrefixes()

function actionPath(action) {
  const prefix = PREFIXES.find(p => window.location.pathname.startsWith(p)) || "";
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