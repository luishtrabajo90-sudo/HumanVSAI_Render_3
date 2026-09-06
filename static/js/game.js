"use strict";

var $ = function (id) { return document.getElementById(id); };
var mobileController = document.body.classList.contains("mobile-controller");
function show(el) { el.classList.remove("hide"); }
function hide(el) { el.classList.add("hide"); }
function setStat(name, value) {
  var els = document.querySelectorAll('[data-stat="' + name + '"]');
  for (var i = 0; i < els.length; i++) { els[i].textContent = value; }
}

var state = {
  total: 0,
  round: 0,
  answered: false,
  timerSeconds: 15,
  timeLeft: 0,
  timerId: null,
  soundsOn: true,
  fxOn: true,
  roundReady: false,
  roundLoadToken: 0,
  roundErrorStage: null,
  transitioning: false,
  answerSubmitting: false,
  resultSubmitting: false,
  resultReceived: false,
};

/* ---------- Audio ---------- */
var SOUND_FILES = {
  correct: "/static/sounds/correct.mp3",
  wrong: "/static/sounds/wrong.mp3",
  timeout: "/static/sounds/timeout.mp3",
  click: "/static/sounds/click.mp3",
  tick: "/static/sounds/tick.mp3",
};
function stopTickSound() {
  window.AudioManager.stopAll();
}

function playSound(name) {
  if (!state.soundsOn) return;
  var src = SOUND_FILES[name];
  if (!src) return;
  if (name === "tick") stopTickSound();
  window.AudioManager.play(src, name === "wrong" ? { maxDurationMs: 2000 } : undefined);
}

/* ---------- Efectos visuales ---------- */
function flashFx(el, cls) {
  if (!state.fxOn || !el) return;
  el.classList.remove(cls);
  void el.offsetWidth; // reflow para reiniciar animación
  el.classList.add(cls);
}

/* ---------- API helpers ---------- */
function api(url, method, body) {
  var opts = { method: method || "GET", headers: {} };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  return fetch(url, opts).then(function (r) {
    return r.json().then(function (data) {
      if (!r.ok) throw new Error(data.error || "Error de red");
      return data;
    });
  });
}

function validateRoundPayload(round) {
  if (!round || !round.image) {
    throw new Error("La ronda no contiene una imagen.");
  }
  if (typeof round.image.id !== "string" || !round.image.id ||
      typeof round.image.src !== "string" ||
      !round.image.src.startsWith("/static/") && !round.image.src.startsWith("https://")) {
    throw new Error("El contrato de la imagen no es válido.");
  }
  if (Object.prototype.hasOwnProperty.call(round.image, "isAI")) {
    throw new Error("La ronda reveló una clasificación antes de responder.");
  }
  if (!Number.isFinite(round.timer_seconds) || round.timer_seconds <= 0 ||
      !Number.isInteger(round.round) || !Number.isInteger(round.total) ||
      typeof round.detective_tip !== "string" || !round.detective_tip) {
    throw new Error("Los datos de control de la ronda no son válidos.");
  }
  return round;
}

function validateAnswerPayload(answer) {
  if (!answer || !answer.image || typeof answer.image.isAI !== "boolean" ||
      !["ia", "real"].includes(answer.correct_choice) ||
      ["reason", "explanation", "next_tip", "summary"].some(function (field) {
        return typeof answer[field] !== "string" || !answer[field];
      })) {
    throw new Error("La respuesta no incluyó una clasificación válida.");
  }
  return answer;
}

/* ---------- Timer ---------- */
function stopTimer() {
  if (state.timerId) { clearInterval(state.timerId); state.timerId = null; }
  stopTickSound();
}
function startTimer(seconds) {
  stopTimer();
  if (document.body.classList.contains("admin-session")) {
    $("vTimerBig").textContent = "∞";
    var mobileTimer = $("mobileRoundTimer");
    if (mobileTimer) mobileTimer.textContent = "∞";
    return;
  }
  state.timerSeconds = seconds;
  state.timeLeft = seconds;
  updateTimerUI();
  playSound("tick");
  state.timerId = setInterval(function () {
    state.timeLeft--;
    updateTimerUI();
    if (state.timeLeft <= 0) {
      stopTimer();
      onTimeout();
    }
  }, 1000);
}
function updateTimerUI() {
  var ring = $("timerRing");
  var pct = state.timerSeconds > 0 ? Math.max(0, (state.timeLeft / state.timerSeconds) * 100) : 0;
  ring.style.setProperty("--pct", pct);
  $("vTimerBig").textContent = state.timeLeft;
  ring.classList.toggle("low", state.timeLeft <= 5);
  var mobileTimer = $("mobileRoundTimer");
  if (mobileTimer) {
    mobileTimer.textContent = state.timeLeft;
    mobileTimer.style.setProperty("--timer-pct", pct + "%");
  }
}

/* ---------- Flujo del juego ---------- */
function startFlow() {
  window.AudioManager.stopAll();
  state.roundLoadToken++;
  state.roundReady = false;
  state.resultSubmitting = false;
  state.resultReceived = false;
  $("appWrap").classList.remove("start-mode", "launcher-mode");
  document.querySelectorAll(".game-chrome").forEach(function (el) { show(el); });
  hide($("howToSection"));
  hide($("screenStart")); hide($("screenResult")); show($("screenLoading"));
  var mobileExit = $("btnMobileGameExit");
  if (mobileExit) show(mobileExit);
  var playerBanner = $("mobilePlayerBanner");
  if (playerBanner) show(playerBanner);
  var playerIdentity = $("mobilePlayerIdentity");
  if (playerIdentity) show(playerIdentity);
  $("loadMsg").textContent = "Cargando imágenes…";
  api("/api/game/start", "POST").then(function (data) {
    state.total = data.total;
    hide($("screenLoading")); show($("screenGame"));
    loadRound();
  }).catch(function (err) {
    $("loadMsg").innerHTML = err.message + "<br><br>";
    var b = document.createElement("button");
    b.className = "btn"; b.textContent = "Volver";
    b.addEventListener("click", goHome);
    $("screenLoading").appendChild(b);
  });
}

function resetRoundUI() {
  window.AudioManager.stopAll();
  state.transitioning = false;
  state.answerSubmitting = false;
  stopTimer();
  state.answered = false;
  state.roundReady = false;
  state.roundErrorStage = null;
  $("btnNext").disabled = false;
  $("vTimerBig").textContent = "--";
  $("timerRing").style.setProperty("--pct", 100);
  $("timerRing").classList.remove("low");
  $("roundCards").classList.add("round-pending");
  $("roundCards").setAttribute("aria-busy", "true");
  $("screenGame").classList.add("round-loading");
  $("card0").className = "card single-image-card";
  $("img0").removeAttribute("src");
  document.querySelectorAll(".classification-choice").forEach(function (button) {
    button.className = "classification-choice";
    button.disabled = true;
  });
  hide($("feedback"));
  hide($("roundLoadError"));
  $("timeoutAlert").className = "timeout-alert waiting";
  $("timeoutAlert").textContent = "Preparando imágenes…";
  show($("timeoutAlert"));
  closeWrongModal();
}

function loadImage(imageElement, src) {
  return new Promise(function (resolve, reject) {
    var timeoutId = setTimeout(function () {
      cleanup();
      reject(new Error("La imagen tardó demasiado en responder."));
    }, 12000);
    function cleanup() {
      clearTimeout(timeoutId);
      imageElement.removeEventListener("load", onLoad);
      imageElement.removeEventListener("error", onError);
    }
    function onLoad() {
      cleanup();
      if (imageElement.naturalWidth > 0 && imageElement.naturalHeight > 0) {
        resolve();
      } else {
        reject(new Error("La imagen cargada no tiene dimensiones válidas."));
      }
    }
    function onError() {
      cleanup();
      reject(new Error("No se pudo cargar " + src + "."));
    }
    imageElement.addEventListener("load", onLoad);
    imageElement.addEventListener("error", onError);
    imageElement.src = src;
  });
}

function prepareRoundImage(round) {
  return loadImage($("img0"), round.image.src).then(function () { return round; });
}

function registerRound(round) {
  state.soundsOn = round.sound_effects_enabled;
  state.fxOn = round.visual_effects_enabled;
  state.round = round.round;
  state.total = round.total;
  state.roundReady = true;
  setStat("score", round.score);
  setStat("streak", round.streak);
  setStat("round", round.round + "/" + round.total);
  $("bar").style.width = ((round.round - 1) / round.total * 100) + "%";
}

function showPreparedRound(round) {
  $("qcat").textContent = round.category;
  $("qtitle").textContent = round.question;
  $("detectiveHint").textContent = round.detective_tip;
  $("roundCards").classList.remove("round-pending");
  $("screenGame").classList.remove("round-loading");
  $("roundCards").setAttribute("aria-busy", "false");
  document.querySelectorAll(".classification-choice").forEach(function (button) {
    button.disabled = false;
  });
  $("timeoutAlert").textContent = round.instruction;
}

function showRoundError(error, stage) {
  stopTimer();
  state.roundReady = false;
  state.roundErrorStage = stage || "load";
  $("timeoutAlert").className = "timeout-alert failure";
  $("timeoutAlert").textContent = stage === "answer" ? "No se pudo registrar la respuesta" : "Error al cargar la ronda";
  $("roundLoadErrorMessage").textContent = error.message;
  $("btnRetryRound").textContent = stage === "answer" ? "Volver al inicio" : "Reintentar";
  $("btnSkipRound").classList.toggle("hide", stage === "answer");
  show($("roundLoadError"));
}

function loadRound() {
  var loadToken = ++state.roundLoadToken;
  resetRoundUI();
  api("/api/game/round")
    .then(validateRoundPayload)
    .then(prepareRoundImage)
    .then(function (round) {
      if (loadToken !== state.roundLoadToken) return;
      registerRound(round);
      showPreparedRound(round);
      startTimer(round.timer_seconds);
    })
    .catch(function (error) {
      if (loadToken === state.roundLoadToken) showRoundError(error, "load");
    });
}

function choose(choice) {
  if (state.answered || !state.roundReady || state.answerSubmitting) return;
  state.answerSubmitting = true;
  state.answered = true;
  state.roundReady = false;
  stopTimer();
  document.querySelectorAll(".classification-choice").forEach(function (button) {
    button.disabled = true;
  });
  playSound("click");
  api("/api/game/answer", "POST", { choice: choice })
    .then(validateAnswerPayload)
    .then(function (r) { reveal(r, choice); })
    .catch(function (error) {
      state.answerSubmitting = false;
      showRoundError(error, "answer");
    });
}

function onTimeout() {
  if (state.answered || !state.roundReady || state.answerSubmitting) return;
  state.answerSubmitting = true;
  state.answered = true;
  state.roundReady = false;
  api("/api/game/timeout", "POST")
    .then(validateAnswerPayload)
    .then(function (r) { reveal(r, null); })
    .catch(function (error) {
      state.answerSubmitting = false;
      showRoundError(error, "answer");
    });
}

function revealCorrectChoice(correctAnswer) {
  document.querySelectorAll(".classification-choice").forEach(function (button) {
    button.disabled = true;
    button.classList.remove("is-correct", "is-wrong", "is-muted");
    button.classList.add(button.dataset.choice === correctAnswer ? "is-correct" : "is-muted");
  });
}

function reveal(r, chosenChoice) {
  state.answered = true;
  var correctAnswer = r.correct_choice;
  $("card0").classList.add("locked", "revealed", r.correct ? "is-correct" : "is-wrong");
  revealCorrectChoice(correctAnswer);

  if (r.correct) {
    var choiceButton = chosenChoice === "ia" ? "choiceAI" : "choiceReal";
    if (choiceButton) flashFx($(choiceButton), "fx-pulse");
    playSound("correct");
  } else {
    flashFx($("screenGame"), "fx-shake");
    playSound(chosenChoice === null ? "timeout" : "wrong");
    if (chosenChoice !== null) openWrongModal();
  }

  $("timeoutAlert").className = "timeout-alert " + (r.correct ? "success" : "failure");
  $("timeoutAlert").textContent = r.correct
    ? "✓ ¡Respuesta correcta!"
    : (chosenChoice === null ? "⏱ ¡Tiempo agotado!" : "✕ Respuesta incorrecta");
  show($("timeoutAlert"));

  var titleTxt = r.correct ? "✅ ¡Correcto!" : (chosenChoice === null ? "⏱️ ¡Se acabó el tiempo!" : "❌ Respuesta incorrecta");
  var gainTxt = r.correct ? ("+" + r.gain + " pts" + (r.streak > 1 ? "  🔥 x" + r.streak : "")) : "+0 pts";
  $("fbTitle").innerHTML = titleTxt + ' <span class="gain">' + gainTxt + "</span>";
  $("fbSummary").textContent = r.summary;
  show($("feedback"));

  setStat("score", r.score);
  setStat("streak", r.streak);
  $("bar").style.width = (state.round / state.total * 100) + "%";

  $("btnNext").textContent = r.is_last ? "Ver resultado ▶" : "Siguiente ▶";
  $("btnNext").focus();
}

function next() {
  if (state.transitioning) return;
  state.transitioning = true;
  $("btnNext").disabled = true;
  window.AudioManager.stopAll();
  api("/api/game/next", "POST").then(function (r) {
    if (r.finished) { finish(); }
    else { loadRound(); }
  }).catch(function (error) {
    state.transitioning = false;
    $("btnNext").disabled = false;
    showRoundError(error, "answer");
  });
}

function retryRound() {
  if (state.roundErrorStage === "answer") {
    goHome();
  } else if (mobileController) {
    state.roundLoadToken++;
    $("btnRetryRound").disabled = true;
    api("/api/game/next", "POST").then(function (result) {
      if (result.finished) startFlow();
      else loadRound();
    }).catch(function (error) {
      $("btnRetryRound").disabled = false;
      showRoundError(error, "answer");
    });
  } else {
    loadRound();
  }
}

function skipRound() {
  if (state.roundErrorStage !== "load") return;
  state.roundLoadToken++;
  hide($("roundLoadError"));
  $("timeoutAlert").textContent = "Omitiendo ronda…";
  api("/api/game/timeout", "POST")
    .then(function () { return api("/api/game/next", "POST"); })
    .then(function (result) {
      if (result.finished) finish();
      else loadRound();
    })
    .catch(function (error) { showRoundError(error, "answer"); });
}

function finish() {
  if (state.resultSubmitting || state.resultReceived) return;
  state.resultSubmitting = true;
  window.AudioManager.stopAll();
  state.transitioning = false;
  hide($("screenGame"));
  $("bar").style.width = "100%";
  api("/api/game/result").then(function (r) {
    state.resultSubmitting = false;
    state.resultReceived = true;
    $("rScore").textContent = r.score;
    $("rAcc").textContent = r.accuracy + "%";
    $("rHits").textContent = r.hits + "/" + r.total;
    $("rBest").textContent = r.best_streak;
    $("rRank").textContent = r.rank;
    $("rMsg").textContent = r.message;
    if (window.GameLauncher && window.GameLauncher.refreshProfile) {
      window.GameLauncher.refreshProfile(r.profile);
    }
    show($("screenResult"));
  }).catch(function (error) {
    state.resultSubmitting = false;
    show($("screenGame"));
    showRoundError(error, "answer");
  });
}

/* ---------- Inicio / Salir ---------- */
function goHome() {
  window.AudioManager.stopAll();
  state.transitioning = false;
  state.roundLoadToken++;
  state.roundReady = false;
  stopTimer();
  closeWrongModal();
  hide($("screenGame"));
  hide($("screenLoading"));
  hide($("screenResult"));
  hide($("feedback"));
  hide($("timeoutAlert"));
  document.querySelectorAll(".game-chrome").forEach(function (el) { hide(el); });
  $("appWrap").classList.remove("launcher-mode");
  $("appWrap").classList.add("start-mode");
  show($("howToSection"));
  show($("screenStart"));
  var mobileExit = $("btnMobileGameExit");
  if (mobileExit) hide(mobileExit);
  var playerBanner = $("mobilePlayerBanner");
  if (playerBanner) hide(playerBanner);
  var playerIdentity = $("mobilePlayerIdentity");
  if (playerIdentity) hide(playerIdentity);
}
/* ---------- Learn modal ---------- */
function openLearn() { show($("overlay")); }
function closeLearn() { hide($("overlay")); }
function setTab(t) {
  var img = t === "img";
  $("tabImg").classList.toggle("active", img);
  $("tabVid").classList.toggle("active", !img);
  $("tabImgBody").classList.toggle("hide", !img);
  $("tabVidBody").classList.toggle("hide", img);
}

/* ---------- Wrong answer modal ---------- */
var wrongModalTimer = null;
function openWrongModal() {
  show($("overlayWrong"));
  if (wrongModalTimer) clearTimeout(wrongModalTimer);
  wrongModalTimer = setTimeout(closeWrongModal, 5000);
}
function closeWrongModal() {
  hide($("overlayWrong"));
  if (wrongModalTimer) { clearTimeout(wrongModalTimer); wrongModalTimer = null; }
}

function returnToGames() {
  window.AudioManager.stopAll();
  state.roundLoadToken++;
  state.roundReady = false;
  stopTimer();
  closeWrongModal();
  hide($("screenGame"));
  hide($("screenLoading"));
  hide($("screenResult"));
  state.total = 0;
  state.round = 0;
  state.answered = false;
  state.timeLeft = 0;
  var mobileExit = $("btnMobileGameExit");
  if (mobileExit) hide(mobileExit);
  if (window.GameLauncher) window.GameLauncher.open();
  else goHome();
}

/* ---------- Wire up ---------- */
function startAnotherGame() {
  hide($("screenResult"));
  startFlow();
}
var retryGameButton = $("btnRetryGame");
if (retryGameButton) {
  retryGameButton.addEventListener("click", function () {
    api("/api/game/result/discard", "POST").finally(startAnotherGame);
  });
}
var newGameButton = $("btnNewGame");
if (newGameButton) newGameButton.addEventListener("click", startAnotherGame);
var viewRankingButton = $("btnViewRanking");
if (viewRankingButton) {
  viewRankingButton.addEventListener("click", function () {
    window.location.href = "/ranking";
  });
}
$("btnNext").addEventListener("click", next);
$("btnRetryRound").addEventListener("click", retryRound);
$("btnSkipRound").addEventListener("click", skipRound);
$("choiceAI").addEventListener("click", function () { choose("ia"); });
$("choiceReal").addEventListener("click", function () { choose("real"); });
document.addEventListener("keydown", function (e) {
  if ($("screenGame").classList.contains("hide")) return;
  if (!state.answered) {
    if (e.key === "i" || e.key === "I" || e.key === "1") choose("ia");
    if (e.key === "r" || e.key === "R" || e.key === "2") choose("real");
  }
});
["btnLearnTop", "btnLearnStart", "btnLearnEnd"].forEach(function (id) {
  var el = $(id); if (el) el.addEventListener("click", openLearn);
});
$("btnCloseLearn").addEventListener("click", closeLearn);
$("overlay").addEventListener("click", function (e) { if (e.target === $("overlay")) closeLearn(); });
$("tabImg").addEventListener("click", function () { setTab("img"); });
$("tabVid").addEventListener("click", function () { setTab("vid"); });
document.addEventListener("keydown", function (e) { if (e.key === "Escape") closeLearn(); });
$("btnCloseWrong").addEventListener("click", closeWrongModal);
$("overlayWrong").addEventListener("click", function (e) { if (e.target === $("overlayWrong")) closeWrongModal(); });
$("btnExit").addEventListener("click", returnToGames);
var mobileExit = $("btnMobileGameExit");
if (mobileExit) {
  mobileExit.addEventListener("click", function () {
    if (window.GameLauncher) window.GameLauncher.endVisitorSession(false);
  });
}

/* configuración inicial (para mostrar HUD antes de iniciar partida) */
api("/api/settings").then(function (s) {
  state.soundsOn = s.sound_effects_enabled;
  state.fxOn = s.visual_effects_enabled;
});

api("/api/exhibition").then(function (data) {
  if (!data.active) return;
  $("exhibitionQr").src = data.qr_url + "?url=" + encodeURIComponent(data.public_url);
  $("exhibitionUrl").href = data.public_url;
  $("exhibitionUrl").textContent = data.public_url;
  show($("exhibitionPanel"));
}).catch(function (error) {
  console.error("No se pudo cargar el acceso de exposición:", error);
});

window.HumanVsAI = {
  start: startFlow,
  home: goHome,
  destroy: function () {
    window.AudioManager.stopAll();
    state.roundLoadToken++;
    state.roundReady = false;
    stopTimer();
    closeWrongModal();
  },
};
