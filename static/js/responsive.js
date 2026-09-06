"use strict";

(function () {
  var root = document.documentElement;
  var fullscreenButton = null;
  var resizeTimer = null;

  function updateViewportState() {
    var viewport = window.visualViewport;
    var width = Math.round(viewport ? viewport.width : window.innerWidth);
    var height = Math.round(viewport ? viewport.height : window.innerHeight);
    root.style.setProperty("--app-height", height + "px");
    root.style.setProperty("--app-width", width + "px");
    root.classList.toggle("is-portrait", height >= width);
    root.classList.toggle("is-landscape", width > height);
    root.classList.toggle("is-ultrawide", width / Math.max(height, 1) >= 2);
    root.classList.toggle("is-tv-size", width >= 1920);
    window.dispatchEvent(new CustomEvent("appviewportchange", {
      detail: {width: width, height: height, fullscreen: Boolean(document.fullscreenElement)}
    }));
  }

  function scheduleViewportUpdate() {
    window.clearTimeout(resizeTimer);
    resizeTimer = window.setTimeout(updateViewportState, 80);
  }

  function toggleFullscreen() {
    if (document.fullscreenElement) {
      document.exitFullscreen().catch(function (error) {
        console.error("No se pudo salir de pantalla completa:", error);
      });
      return;
    }
    document.documentElement.requestFullscreen().catch(function (error) {
      console.error("No se pudo activar pantalla completa:", error);
    });
  }

  function updateFullscreenButton() {
    if (!fullscreenButton) return;
    var active = Boolean(document.fullscreenElement);
    fullscreenButton.setAttribute("aria-pressed", String(active));
    fullscreenButton.setAttribute("aria-label", active ? "Salir de pantalla completa" : "Activar pantalla completa");
    fullscreenButton.textContent = active ? "⛶" : "⛶";
    root.classList.toggle("is-fullscreen", active);
    window.requestAnimationFrame(updateViewportState);
  }

  function visibleFocusableElements() {
    return Array.prototype.filter.call(document.querySelectorAll(
      "button:not([disabled]),a[href],input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex='0']"
    ), function (node) {
      var rect = node.getBoundingClientRect();
      var style = window.getComputedStyle(node);
      return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none";
    });
  }

  function moveDirectionalFocus(event) {
    var directions = {
      ArrowLeft: [-1, 0], ArrowRight: [1, 0],
      ArrowUp: [0, -1], ArrowDown: [0, 1]
    };
    var direction = directions[event.key];
    if (!direction) return;
    var active = document.activeElement;
    if (active && (active.matches("input,textarea,select") || active.closest(".gh-scene"))) return;
    var candidates = visibleFocusableElements();
    if (!candidates.length) return;
    if (!active || !candidates.includes(active)) {
      candidates[0].focus();
      event.preventDefault();
      return;
    }
    var current = active.getBoundingClientRect();
    var originX = current.left + current.width / 2;
    var originY = current.top + current.height / 2;
    var best = null;
    var bestScore = Infinity;
    candidates.forEach(function (candidate) {
      if (candidate === active) return;
      var rect = candidate.getBoundingClientRect();
      var dx = rect.left + rect.width / 2 - originX;
      var dy = rect.top + rect.height / 2 - originY;
      var forward = dx * direction[0] + dy * direction[1];
      if (forward <= 2) return;
      var cross = Math.abs(dx * direction[1] - dy * direction[0]);
      var score = forward + cross * 2.4;
      if (score < bestScore) {
        best = candidate;
        bestScore = score;
      }
    });
    if (best) {
      event.preventDefault();
      best.focus({preventScroll: true});
      best.scrollIntoView({block: "nearest", inline: "nearest"});
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    fullscreenButton = document.getElementById("appFullscreen");
    if (!document.fullscreenEnabled) {
      fullscreenButton.hidden = true;
    } else {
      fullscreenButton.addEventListener("click", toggleFullscreen);
    }
    updateFullscreenButton();
    updateViewportState();
  });
  document.addEventListener("fullscreenchange", updateFullscreenButton);
  document.addEventListener("keydown", moveDirectionalFocus);
  window.addEventListener("resize", scheduleViewportUpdate, {passive: true});
  window.addEventListener("orientationchange", scheduleViewportUpdate, {passive: true});
  if (window.visualViewport) {
    window.visualViewport.addEventListener("resize", scheduleViewportUpdate, {passive: true});
  }
})();
