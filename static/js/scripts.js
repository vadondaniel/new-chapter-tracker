var socket = io();

socket.on('update_progress', function(data) {
    document.getElementById('statusMessage').innerText = `Updating... ${data.current}/${data.total}`;
});

socket.on('update_complete', function() {
    hideSpinner();
    location.reload();
});

function showSpinner() {
    console.log("Showing spinner");
    document.getElementById('overlay').style.display = 'flex';
    document.getElementById('spinner').style.display = 'block';
    document.getElementById('statusMessage').style.display = 'block';
}

function hideSpinner() {
    console.log("Hiding spinner");
    document.getElementById('overlay').style.display = 'none';
    document.getElementById('spinner').style.display = 'none';
    document.getElementById('statusMessage').style.display = 'none';
}

function updateChapter(url) {
    showSpinner();
    document.getElementById('statusMessage').innerText = 'Updating chapter...';
    const path = window.location.pathname.startsWith('/manga') ? '/manga/update' : '/update';
    fetch(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: url, timestamp: new Date().toISOString() })
    }).then(response => response.json())
      .then(data => {
          hideSpinner();
          location.reload();
      }).catch(error => {
          console.error("Error updating chapter:", error);
          hideSpinner();
      });
}

function recheckChapter(url) {
    showSpinner();
    document.getElementById('statusMessage').innerText = 'Rechecking chapter...';
    const path = window.location.pathname.startsWith('/manga') ? '/manga/recheck' : '/recheck';
    fetch(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: url })
    }).then(response => response.json())
      .then(data => {
          hideSpinner();
          location.reload();
      }).catch(error => {
          console.error("Error rechecking chapter:", error);
          hideSpinner();
      });
}

function addLink() {
    const name = document.getElementById('newName').value;
    const url = document.getElementById('newUrl').value;
    
    if (name && url) {
        const path = window.location.pathname.startsWith('/manga') ? '/manga/add' : '/add';
        fetch(path, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: name, url: url })
        }).then(response => response.json())
          .then(data => location.reload())
          .catch(error => {
              console.error("Error adding link:", error);
              hideSpinner();
          });
    } else {
        alert("Please enter both name and URL.");
    }
}

function forceUpdate() {
    showSpinner();
    document.getElementById('statusMessage').innerText = 'Fully updating database...';
    const path = window.location.pathname.startsWith('/manga') ? '/manga/force_update' : '/force_update';
    fetch(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
    }).then(response => response.json())
      .then(data => {
          // Do nothing here, wait for WebSocket update
      }).catch(error => {
          console.error("Error forcing update:", error);
          hideSpinner();
      });
}

window.onload = function() {
    console.log("Window loaded, update_in_progress:", update_in_progress);
    if (update_in_progress) {
        showSpinner();
        document.getElementById('statusMessage').innerText = 'Update in progress...';
    } else {
        hideSpinner();
    }
}