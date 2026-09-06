"use strict";

(function () {
  var grid = document.getElementById("playerGrid");
  var projection = Number(document.querySelector(".projection").dataset.projectionNumber) || 1;

  function formatTime(seconds) {
    return String(Math.floor(seconds / 60)).padStart(2, "0") + ":" +
      String(seconds % 60).padStart(2, "0");
  }

  function playerCard(player, index) {
    var card = document.createElement("article");
    card.className = "projection-player" + (player ? "" : " is-empty");
    if (!player) {
      card.innerHTML = '<span class="empty-slot">Esperando jugador</span>';
      return card;
    }
    if (player.image_url) {
      var image = document.createElement("img");
      image.className = "projection-image";
      image.alt = "Imagen del juego de " + player.name;
      image.src = player.image_url;
      card.appendChild(image);
    }
    var number = document.createElement("b");
    number.className = "projection-player-number";
    number.textContent = "N° " + (index + 1);
    card.appendChild(number);
    var timer = document.createElement("div");
    timer.className = "projection-timer-ring";
    timer.style.setProperty("--pct", Math.max(0, player.round_seconds_remaining / 15 * 100));
    timer.textContent = player.round_seconds_remaining;
    card.appendChild(timer);
    var outcomes = document.createElement("div");
    outcomes.className = "projection-outcomes";
    for (var hit = 0; hit < player.hits; hit++) {
      var check = document.createElement("span");
      check.className = "projection-outcome is-hit";
      check.textContent = "✓";
      outcomes.appendChild(check);
    }
    for (var miss = 0; miss < player.misses; miss++) {
      var cross = document.createElement("span");
      cross.className = "projection-outcome is-miss";
      cross.textContent = "✕";
      outcomes.appendChild(cross);
    }
    card.appendChild(outcomes);
    var details = document.createElement("div");
    details.className = "projection-details";
    var position = document.createElement("span");
    position.textContent = "JUGADOR";
    var name = document.createElement("h2");
    name.textContent = player.name;
    var stats = document.createElement("dl");
    stats.className = "projection-stats";
    [["Puntos", player.points], ["Ronda", player.round + "/" + player.total_rounds]].forEach(function (stat) {
      var item = document.createElement("div");
      var label = document.createElement("dt");
      label.textContent = stat[0];
      var value = document.createElement("dd");
      value.textContent = stat[1];
      item.append(label, value);
      stats.appendChild(item);
    });
    details.append(position, name, stats);
    card.appendChild(details);
    return card;
  }

  function loadPlayers() {
    fetch("/api/online-players?projection=" + projection)
      .then(function (response) { return response.ok ? response.json() : Promise.reject(); })
      .then(function (data) {
        var players = Array.isArray(data.players) ? data.players.slice(0, 4) : [];
        grid.replaceChildren();
        for (var index = 0; index < 4; index++) {
          grid.appendChild(playerCard(players[index], (projection - 1) * 4 + index));
        }
      })
      .catch(function () { grid.replaceChildren(); });
  }

  loadPlayers();
  setInterval(loadPlayers, 1000);
}());