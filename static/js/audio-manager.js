"use strict";

(function (global) {
  var active = new Map();

  function release(audio, stopPlayback) {
    var entry = active.get(audio);
    if (!entry) return;
    active.delete(audio);
    if (entry.timerId !== null) global.clearTimeout(entry.timerId);
    audio.removeEventListener("ended", entry.onEnded);
    audio.removeEventListener("error", entry.onError);
    if (stopPlayback) {
      audio.pause();
      audio.currentTime = 0;
    }
    audio.removeAttribute("src");
    audio.load();
  }

  function stopAll() {
    Array.from(active.keys()).forEach(function (audio) {
      release(audio, true);
    });
  }

  function stop(audio) {
    release(audio, true);
  }

  function isActive(audio) {
    return active.has(audio);
  }

  function play(src, options) {
    options = options || {};
    var audio = new global.Audio(src);
    audio.loop = Boolean(options.loop);
    if (options.volume !== undefined) {
      if (!Number.isFinite(options.volume) || options.volume < 0 || options.volume > 1) {
        throw new TypeError("volume debe ser un número entre 0 y 1.");
      }
      audio.volume = options.volume;
    }
    var entry = {
      timerId: null,
      onEnded: function () { release(audio, false); },
      onError: function () { release(audio, true); },
    };
    active.set(audio, entry);
    audio.addEventListener("ended", entry.onEnded);
    audio.addEventListener("error", entry.onError);

    if (options.maxDurationMs !== undefined) {
      if (!Number.isFinite(options.maxDurationMs) || options.maxDurationMs <= 0) {
        release(audio, true);
        throw new TypeError("maxDurationMs debe ser un número positivo.");
      }
      entry.timerId = global.setTimeout(function () {
        release(audio, true);
      }, options.maxDurationMs);
    }

    var playback = audio.play();
    if (playback && typeof playback.catch === "function") {
      playback.catch(function () {
        release(audio, true);
      });
    }
    return audio;
  }

  global.AudioManager = {
    play: play,
    stop: stop,
    stopAll: stopAll,
    isActive: isActive,
  };
})(window);
