"use strict";

(function (global) {
  var games = JSON.parse(document.getElementById("gameCatalogData").textContent);
  var catalog = {};
  var selected = "human-vs-ai";
  var launcher = document.getElementById("screenLauncher");
  var appWrap = document.getElementById("appWrap");
  var mobileController = document.body.classList.contains("mobile-controller");
  var profile = null;
  var visitorSession = null;
  var visitorDeadline = 0;
  var visitorTimerId = null;
  var visitorSyncId = null;
  var expirationCheckPending = false;
  var rankingRefreshId = null;
  var adminUsernames = JSON.parse(el("adminUsernameData").textContent);
  games.forEach(function (game) { catalog[game.id] = game; });

  function el(id) { return document.getElementById(id); }
  function escapeText(value) {
    var node = document.createElement("span");
    node.textContent = value == null ? "" : String(value);
    return node.innerHTML;
  }
  function requestJson(url, options) {
    return fetch(url, options).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (data) {
        if (response.status === 401 && data.session_expired) {
          handleSessionEnded(true, data.error);
        }
        if (!response.ok) throw new Error(data.error || "No se pudo completar la solicitud.");
        return data;
      });
    });
  }

  function select(id) {
    var game = catalog[id];
    if (!game) return;
    selected = id;
    document.querySelectorAll(".game-app").forEach(function (button) {
      button.classList.toggle("selected", button.dataset.gameId === id);
      button.setAttribute("aria-pressed", String(button.dataset.gameId === id));
    });
    el("gamePreviewAction").textContent = game.action_label;
    el("btnLaunchSelected").disabled = game.status !== "available";
  }

  function formatCountdown(seconds) {
    seconds = Math.max(0, seconds);
    return String(Math.floor(seconds / 60)).padStart(2, "0") + ":" +
      String(seconds % 60).padStart(2, "0");
  }

  function renderSessionClocks(timedSession) {
    var launcherVisible = !launcher.classList.contains("hide");
    var startVisible = !el("screenStart").classList.contains("hide");
    document.querySelector(".launcher-session-clock").classList.toggle(
      "hide",
      !(timedSession && launcherVisible)
    );
    el("gameSessionClock").classList.toggle(
      "hide",
      !(timedSession && !launcherVisible && !startVisible)
    );
  }

  function renderVisitorSession() {
    var active = Boolean(visitorSession && visitorSession.active);
    var timedSession = active && !visitorSession.admin;
    el("btnAdminPanel").classList.toggle("hide", !(active && visitorSession.admin));
    el("visitorRankingAdminActions").classList.toggle(
      "hide",
      !(active && visitorSession.can_clear_visitor_history)
    );
    renderSessionClocks(timedSession);
    if (!active) {
      el("gameSessionName").textContent = "Visitante";
      el("gameSessionTimer").textContent = "00:00";
      return;
    }
    var name = visitorSession.name;
    var playerBanner = el("mobilePlayerBanner");
    var playerIdentity = el("mobilePlayerIdentity");
    var gameActive = !el("screenGame").classList.contains("hide") ||
      !el("screenLoading").classList.contains("hide");
    if (playerBanner) {
      el("mobilePlayerNumber").textContent = "JUGADOR " + visitorSession.player_number;
      el("mobilePlayerName").textContent = name;
      playerBanner.classList.toggle(
        "hide",
        visitorSession.admin || !visitorSession.player_number || !gameActive
      );
      if (playerIdentity) playerIdentity.classList.toggle(
        "hide",
        visitorSession.admin || !visitorSession.player_number || !gameActive
      );
    }
    document.body.classList.toggle("admin-session", Boolean(visitorSession.admin));
    el("launcherProfileRole").textContent = visitorSession.admin ? "ADMIN" : "JUGADOR";
    el("launcherSessionName").textContent = name;
    el("launcherProfileName").textContent = name;
    el("gameSessionName").textContent = name;
    document.querySelector(".profile-avatar").textContent = name.charAt(0).toUpperCase();
    el("btnOpenProfilePhoto").classList.toggle("hide", Boolean(visitorSession.admin));
    if (timedSession) renderCountdown();
  }

  function renderCountdown() {
    if (!visitorSession || visitorSession.admin) return;
    var remaining = Math.max(0, Math.ceil((visitorDeadline - Date.now()) / 1000));
    var value = formatCountdown(remaining);
    el("launcherSessionTimer").textContent = value;
    el("gameSessionTimer").textContent = value;
    if (remaining === 0 && !expirationCheckPending) {
      expirationCheckPending = true;
      syncVisitorSession(false).finally(function () {
        expirationCheckPending = false;
      });
    }
  }

  function setVisitorSession(data) {
    visitorSession = data && data.active ? data : null;
    clearInterval(visitorTimerId);
    clearInterval(visitorSyncId);
    visitorTimerId = null;
    visitorSyncId = null;
    if (!visitorSession) {
      visitorDeadline = 0;
      renderVisitorSession();
      return;
    }
    if (visitorSession.admin) {
      visitorDeadline = 0;
      renderVisitorSession();
      if (mobileController) {
        var adminChoice = el("mobileAdminChoice");
        if (adminChoice) {
          el("mobileAdminName").textContent = visitorSession.name;
          adminChoice.classList.remove("hide");
        }
      }
      return;
    }
    visitorDeadline = Date.now() + visitorSession.seconds_remaining * 1000;
    renderVisitorSession();
    if (!visitorTimerId) visitorTimerId = setInterval(renderCountdown, 250);
    if (!visitorSyncId) {
      visitorSyncId = setInterval(function () { syncVisitorSession(false); }, 30000);
    }
  }

  function syncVisitorSession(initial) {
    return requestJson("/api/visitor-session").then(function (data) {
      if (!data.active && visitorSession) {
        handleSessionEnded(true, "Tu sesión de 10 minutos finalizó.");
      } else {
        setVisitorSession(data);
      }
      return data;
    }).catch(function (error) {
      if (!initial) console.error("No se pudo sincronizar la sesión:", error);
      return null;
    });
  }

  function showVisitorLogin(message) {
    if (global.ProfilePhoto) global.ProfilePhoto.discardRegistrationPhoto();
    el("visitorLoginError").textContent = message || "";
    el("visitorLoginError").classList.toggle("hide", !message);
    el("visitorLoginModal").classList.remove("hide");
    el("visitorNameInput").focus();
  }

  function isAdminUsername(value) {
    return adminUsernames.indexOf(String(value || "").trim().toLowerCase()) !== -1;
  }

  function updateAdminPasswordField() {
    var adminMatch = isAdminUsername(el("visitorNameInput").value);
    var field = el("visitorAdminPassword");
    var password = el("visitorPasswordInput");
    field.hidden = !adminMatch;
    field.setAttribute("aria-hidden", String(!adminMatch));
    password.disabled = !adminMatch;
    password.required = adminMatch;
    if (!adminMatch) password.value = "";
    return adminMatch;
  }

  function hideVisitorLogin(discardPhoto) {
    el("visitorLoginModal").classList.add("hide");
    el("visitorLoginError").classList.add("hide");
    if (discardPhoto && global.ProfilePhoto) global.ProfilePhoto.discardRegistrationPhoto();
  }

  function showSessionExpired(message) {
    hideVisitorLogin(true);
    el("sessionExpiredMessage").textContent = message ||
      "Han transcurrido los 10 minutos disponibles. Tus resultados quedaron guardados en el ranking.";
    el("sessionExpiredModal").classList.remove("hide");
    el("btnAcknowledgeSessionExpired").focus();
  }

  function hideAllScreens() {
    ["screenStart", "screenLoading", "screenGame", "screenResult"].forEach(function (id) {
      el(id).classList.add("hide");
    });
    el("howToSection").classList.add("hide");
    document.querySelectorAll(".game-chrome").forEach(function (node) { node.classList.add("hide"); });
  }

  function showStartScreen() {
    if (global.HumanVsAI) global.HumanVsAI.destroy();
    hideAllScreens();
    launcher.classList.add("hide");
    el("screenStart").classList.remove("hide");
    el("howToSection").classList.remove("hide");
    appWrap.classList.remove("launcher-mode");
    appWrap.classList.add("start-mode");
    renderSessionClocks(false);
    global.scrollTo({top: 0, behavior: "smooth"});
  }

  function resetGameStats() {
    [["score", "0"], ["streak", "0"], ["round", "0/0"]].forEach(function (stat) {
      document.querySelectorAll('[data-stat="' + stat[0] + '"]').forEach(function (node) {
        node.textContent = stat[1];
      });
    });
  }

  function renderProfileStats(data) {
    [["score", data.points], ["streak", data.mission_streak], ["round", data.missions]].forEach(function (stat) {
      document.querySelectorAll('[data-stat="' + stat[0] + '"]').forEach(function (node) {
        node.textContent = stat[1] || 0;
      });
    });
  }

  function handleSessionEnded(showExpired, message) {
    visitorSession = null;
    visitorDeadline = 0;
    profile = null;
    clearInterval(visitorTimerId);
    clearInterval(visitorSyncId);
    clearInterval(rankingRefreshId);
    visitorTimerId = null;
    visitorSyncId = null;
    rankingRefreshId = null;
    el("visitorRankingModal").classList.add("hide");
    document.documentElement.classList.remove("ranking-modal-open");
    document.body.classList.remove("ranking-modal-open");
    el("profileModal").classList.add("hide");
    if (global.ProfilePhoto) {
      global.ProfilePhoto.close();
      global.ProfilePhoto.discardRegistrationPhoto();
    }
    var mobileExit = el("btnMobileGameExit");
    var playerBanner = el("mobilePlayerBanner");
    var playerIdentity = el("mobilePlayerIdentity");
    if (mobileExit) mobileExit.classList.add("hide");
    if (playerBanner) playerBanner.classList.add("hide");
    if (playerIdentity) playerIdentity.classList.add("hide");
    resetGameStats();
    showStartScreen();
    if (showExpired) showSessionExpired(message);
  }

  function startVisitorSession(event) {
    event.preventDefault();
    var button = el("btnStartVisitorSession");
    var adminMatch = updateAdminPasswordField();
    button.disabled = true;
    el("visitorLoginError").classList.add("hide");
    requestJson("/api/visitor-session", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        name: el("visitorNameInput").value,
        password: adminMatch ? el("visitorPasswordInput").value : "",
        csrf_token: el("visitorLoginCsrf").value
      })
    }).then(function (data) {
      if (data.csrf_token) el("visitorLoginCsrf").value = data.csrf_token;
      if (data.password_change_required && data.redirect_url) {
        global.location.href = data.redirect_url;
        return null;
      }
      setVisitorSession(data);
      hideVisitorLogin(false);
      el("visitorLoginForm").reset();
      updateAdminPasswordField();
      if (data.admin && global.ProfilePhoto) {
        global.ProfilePhoto.discardRegistrationPhoto();
      }
      var photoUpload = global.ProfilePhoto && !data.admin
        ? global.ProfilePhoto.submitRegistrationPhoto()
        : Promise.resolve();
      return photoUpload.then(function () {
        if (mobileController && data.admin) {
          var adminChoice = el("mobileAdminChoice");
          if (adminChoice) {
            el("mobileAdminName").textContent = data.name;
            adminChoice.classList.remove("hide");
            return null;
          }
        }
        return mobileController ? launchSelected() : open();
      });
    }).catch(function (error) {
      el("visitorLoginError").textContent = error.message;
      el("visitorLoginError").classList.remove("hide");
      (adminMatch ? el("visitorPasswordInput") : el("visitorNameInput")).focus();
    }).finally(function () {
      button.disabled = false;
    });
  }

  function endVisitorSession(showLogin) {
    requestJson("/api/visitor-session/end", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({csrf_token: el("visitorLoginCsrf").value})
    }).then(function () {
      handleSessionEnded(false);
      if (showLogin) showVisitorLogin();
    }).catch(function (error) {
      console.error("No se pudo cerrar la sesión:", error);
    });
  }

  function refreshProfile(data) {
    if (!data) {
      requestJson("/api/profile").then(refreshProfile).catch(function (error) {
        console.error("No se pudo cargar el perfil:", error);
      });
      return;
    }
    profile = data;
    renderProfileStats(data);
    el("launcherProfileName").textContent = data.name;
    el("launcherProfileLevel").textContent = data.level;
    el("profileName").value = data.name;
    el("profilePoints").textContent = data.points;
    el("profileMissions").textContent = data.missions;
    el("profileTime").textContent = Math.floor(data.total_seconds / 60) + " min";
    el("profileLevel").textContent = data.level;
    if (global.ProfilePhoto) global.ProfilePhoto.renderProfile(data);
    el("profileAchievements").innerHTML = data.achievements.length
      ? data.achievements.map(function (achievement) {
          return "<span>★ " + escapeText(achievement) + "</span>";
        }).join("")
      : "<em>Completa una misión para desbloquear tu primer logro.</em>";
    el("profileHistory").innerHTML = data.history && data.history.length
      ? data.history.map(function (item) {
          return "<span><b>" + escapeText(item.mission_id || item.game_id) + "</b>" +
            item.score + " pts · " + item.seconds + " s</span>";
        }).join("")
      : "<em>Aún no hay misiones registradas.</em>";
  }

  function loadRanking() {
    requestJson("/api/ranking").then(function (data) {
      el("profileRanking").innerHTML = data.ranking.length
        ? data.ranking.map(function (item) {
            return "<li>" + (item.photo_url ? "<img class=\"ranking-avatar\" src=\"" + escapeText(item.photo_url) + "\" alt=\"\">" : "") +
              "<b>#" + item.position + " " + escapeText(item.name) + "</b><span>" +
              item.points + " pts · " + escapeText(item.level) + "</span></li>";
          }).join("")
        : "<li>Completa una misión para inaugurar el ranking.</li>";
    }).catch(function (error) {
      console.error("No se pudo cargar el ranking local:", error);
    });
  }

  function renderVisitorRanking(data) {
    var topTen = data.ranking.slice(0, 10);
    el("visitorRankingList").innerHTML = topTen.length
      ? topTen.map(function (item) {
          var medal = item.position <= 3
            ? "<span class=\"visitor-ranking-medal ranking-medal-" + item.position + "\" aria-label=\"Top " +
              item.position + "\">♛</span>"
            : "";
          return "<tr><td class=\"visitor-ranking-position\">" + item.position + "</td>" +
            "<td class=\"visitor-ranking-player\">" + medal + "<b>" + escapeText(item.name) + "</b>" +
            (item.active ? "<span class=\"visitor-ranking-live\" title=\"En juego\" aria-label=\"En juego\"></span>" : "") +
            "</td><td class=\"visitor-ranking-score\">" + Number(item.points).toLocaleString("en-US") + "</td></tr>";
        }).join("")
      : "<tr><td class=\"visitor-ranking-empty\" colspan=\"3\">Aún no hay visitantes registrados.</td></tr>";
    el("visitorRankingActiveCount").textContent = data.active_count || 0;
  }

  function loadVisitorRanking() {
    return requestJson("/api/visitor-ranking").then(renderVisitorRanking).catch(function (error) {
      el("visitorRankingList").innerHTML = "<tr><td class=\"visitor-ranking-empty\" colspan=\"3\">" +
        escapeText(error.message) + "</td></tr>";
      el("visitorRankingActiveCount").textContent = "—";
    });
  }

  function clearVisitorRanking() {
    if (!visitorSession || !visitorSession.can_clear_visitor_history) return;
    if (!global.confirm("¿Borrar todos los visitantes, sus resultados y el ranking? Esta acción no se puede deshacer.")) {
      return;
    }
    var button = el("btnClearVisitorRanking");
    var status = el("visitorRankingAdminStatus");
    button.disabled = true;
    status.textContent = "Borrando historial…";
    requestJson("/api/visitor-ranking/clear", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({csrf_token: el("visitorLoginCsrf").value})
    }).then(function (data) {
      status.textContent = "Historial borrado: " + data.deleted_visitors + " visitantes.";
      return loadVisitorRanking();
    }).catch(function (error) {
      status.textContent = error.message;
    }).finally(function () {
      button.disabled = false;
    });
  }

  function open() {
    if (!visitorSession) {
      showVisitorLogin();
      return;
    }
    hideAllScreens();
    appWrap.classList.remove("start-mode");
    appWrap.classList.add("launcher-mode");
    launcher.classList.remove("hide");
    renderVisitorSession();
    select(selected);
    refreshProfile();
    document.querySelector('[data-game-id="' + selected + '"]').focus();
  }

  function close() {
    launcher.classList.add("hide");
    appWrap.classList.remove("launcher-mode");
  }

  function launchSelected() {
    var game = catalog[selected];
    if (!visitorSession) {
      showVisitorLogin("Inicia una sesión para jugar.");
      return;
    }
    if (!game || game.status !== "available") return;
    close();
    if (selected === "human-vs-ai" && global.HumanVsAI) {
      global.HumanVsAI.start();
      renderVisitorSession();
    }
  }

  document.querySelectorAll(".game-app").forEach(function (button) {
    button.addEventListener("click", function () { select(button.dataset.gameId); });
    button.addEventListener("keydown", function (event) {
      var cards = Array.prototype.slice.call(document.querySelectorAll(".game-app"));
      var current = cards.indexOf(button);
      var columns = window.innerWidth > 768 ? (window.innerWidth <= 1024 ? 2 : 4) : (window.innerWidth > 480 ? 2 : 1);
      var next = current;
      if (event.key === "ArrowRight") next = Math.min(cards.length - 1, current + 1);
      if (event.key === "ArrowLeft") next = Math.max(0, current - 1);
      if (event.key === "ArrowDown") next = Math.min(cards.length - 1, current + columns);
      if (event.key === "ArrowUp") next = Math.max(0, current - columns);
      if (next !== current) {
        event.preventDefault();
        select(cards[next].dataset.gameId);
        cards[next].focus();
      }
    });
  });
  el("btnLaunchSelected").addEventListener("click", launchSelected);
  el("btnLauncherHome").addEventListener("click", function () {
    endVisitorSession(false);
  });
  el("btnStart").addEventListener("click", function () {
    showVisitorLogin();
  });
  el("visitorLoginForm").addEventListener("submit", startVisitorSession);
  el("visitorNameInput").addEventListener("input", updateAdminPasswordField);
  el("visitorNameInput").addEventListener("change", updateAdminPasswordField);
  el("btnCancelVisitorLogin").addEventListener("click", function () { hideVisitorLogin(true); });
  el("btnAcknowledgeSessionExpired").addEventListener("click", function () {
    el("sessionExpiredModal").classList.add("hide");
    showVisitorLogin();
  });
  el("btnLauncherLogout").addEventListener("click", function () { endVisitorSession(true); });
  var adminPlay = el("btnAdminPlay");
  if (adminPlay) adminPlay.addEventListener("click", function () {
    el("mobileAdminChoice").classList.add("hide");
    launchSelected();
  });
  el("btnOpenProfile").addEventListener("click", function () {
    el("profileModal").classList.remove("hide");
    loadRanking();
    el("profileName").focus();
  });
  el("btnCloseProfile").addEventListener("click", function () { el("profileModal").classList.add("hide"); });
  el("profileModal").addEventListener("click", function (event) {
    if (event.target === el("profileModal")) el("profileModal").classList.add("hide");
  });
  el("btnOpenVisitorRanking").addEventListener("click", function () {
    el("visitorRankingModal").classList.remove("hide");
    document.documentElement.classList.add("ranking-modal-open");
    document.body.classList.add("ranking-modal-open");
    loadVisitorRanking();
    clearInterval(rankingRefreshId);
    rankingRefreshId = setInterval(loadVisitorRanking, 2000);
    el("btnCloseVisitorRanking").focus();
  });
  function closeVisitorRanking() {
    el("visitorRankingModal").classList.add("hide");
    document.documentElement.classList.remove("ranking-modal-open");
    document.body.classList.remove("ranking-modal-open");
    clearInterval(rankingRefreshId);
    rankingRefreshId = null;
  }
  function openRanking() {
    el("visitorRankingModal").classList.remove("hide");
    document.documentElement.classList.add("ranking-modal-open");
    document.body.classList.add("ranking-modal-open");
    loadVisitorRanking();
  }
  el("btnCloseVisitorRanking").addEventListener("click", closeVisitorRanking);
  el("btnClearVisitorRanking").addEventListener("click", clearVisitorRanking);
  el("visitorRankingModal").addEventListener("click", function (event) {
    if (event.target === el("visitorRankingModal")) closeVisitorRanking();
  });
  global.GameLauncher = {
    open: open,
    close: close,
    refreshProfile: refreshProfile,
    syncVisitorSession: syncVisitorSession,
    endVisitorSession: endVisitorSession,
    openRanking: openRanking,
  };
  syncVisitorSession(true);
})(window);
