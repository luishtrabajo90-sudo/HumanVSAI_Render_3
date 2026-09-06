"use strict";
(function () {
  var list = document.getElementById("publicRankingList");
  var page = 0;
  var pageSize = 13;
  var ranking = [];
  var nextButton = document.getElementById("btnNextRanking");
  var backButton = document.getElementById("btnBackToGame");
  function render(data) {
    ranking = data.ranking || [];
    var pageCount = Math.max(1, Math.ceil(ranking.length / pageSize));
    page = Math.min(page, pageCount - 1);
    list.replaceChildren();
    ranking.slice(page * pageSize, (page + 1) * pageSize).forEach(function (player) {
      var row = document.createElement("tr");
      row.innerHTML = "<td class='visitor-ranking-position'></td><td class='visitor-ranking-player'><b></b></td><td class='visitor-ranking-score'></td>";
      row.querySelector(".visitor-ranking-position").textContent = player.position;
      row.querySelector(".visitor-ranking-player b").textContent = player.name;
      row.querySelector(".visitor-ranking-score").textContent = player.points;
      list.appendChild(row);
    });
    document.getElementById("publicActiveCount").textContent = data.active_count || 0;
    if (!list.children.length) list.innerHTML = "<tr><td class='visitor-ranking-empty' colspan='3'>Aún no hay resultados.</td></tr>";
    nextButton.disabled = ranking.length <= pageSize;
    nextButton.textContent = pageCount > 1 ? "Siguiente " + (page + 1) + "/" + pageCount : "Siguiente";
  }
  function load() { fetch("/api/visitor-ranking").then(function (response) { return response.json(); }).then(render); }
  nextButton.addEventListener("click", function () { page = (page + 1) % Math.max(1, Math.ceil(ranking.length / pageSize)); render({ranking: ranking, active_count: document.getElementById("publicActiveCount").textContent}); });
  backButton.addEventListener("click", function () {
    if (window.history.length > 1) window.history.back();
    else window.location.href = "/?modo=movil";
  });
  load(); setInterval(load, 2000);
}());