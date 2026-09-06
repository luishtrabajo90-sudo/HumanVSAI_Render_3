"use strict";

(function (global) {
  var stream = null;
  var capturedBlob = null;
  var previewUrl = null;
  var returnFocus = null;
  var cameraRequestId = 0;
  var modal = document.getElementById("profilePhotoModal");
  var video = document.getElementById("profilePhotoVideo");
  var canvas = document.getElementById("profilePhotoCanvas");
  var preview = document.getElementById("profilePhotoPreview");
  var error = document.getElementById("profilePhotoError");
  var consent = document.getElementById("profilePhotoConsent");
  var capture = document.getElementById("profilePhotoCapture");
  var openButton = document.getElementById("btnOpenProfilePhoto");
  var registrationButton = document.getElementById("btnVisitorPhoto");
  var registrationPreview = document.getElementById("visitorPhotoPreview");
  var registrationFallback = document.getElementById("visitorPhotoFallback");
  var registrationAction = document.getElementById("visitorPhotoAction");
  var registrationStatus = document.getElementById("visitorPhotoStatus");
  var csrfInput = document.getElementById("visitorLoginCsrf");
  var currentPhotoUrl = null;
  var mode = "profile";
  var stagedBlob = null;
  var stagedPreviewUrl = null;
  var CAMERA_ERROR = "No fue posible acceder a la cámara. Puedes seguir utilizando el juego sin fotografía.";

  function stopCamera() {
    cameraRequestId += 1;
    if (stream) stream.getTracks().forEach(function (track) { track.stop(); });
    stream = null;
    video.srcObject = null;
  }

  function clearCapture() {
    stopCamera();
    capturedBlob = null;
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = null;
    preview.removeAttribute("src");
    preview.hidden = true;
    video.hidden = false;
    document.getElementById("btnCaptureProfilePhoto").hidden = false;
    document.getElementById("btnRetakeProfilePhoto").hidden = true;
    document.getElementById("btnSaveProfilePhoto").hidden = true;
    canvas.width = 0;
    canvas.height = 0;
    error.textContent = "";
  }

  function closeModal() {
    clearCapture();
    modal.classList.add("hide");
    consent.hidden = false;
    capture.hidden = true;
    if (returnFocus) returnFocus.focus();
  }

  function showError() {
    stopCamera();
    error.textContent = CAMERA_ERROR;
    video.hidden = true;
    document.getElementById("btnCaptureProfilePhoto").hidden = true;
    if (mode === "registration") {
      registrationStatus.textContent = CAMERA_ERROR;
      closeModal();
    }
  }

  function waitForVideoReady() {
    if (video.readyState >= 2 && video.videoWidth && video.videoHeight) return Promise.resolve();
    return new Promise(function (resolve, reject) {
      var timeout = global.setTimeout(function () {
        cleanup();
        reject(new Error("Camera preview timeout"));
      }, 5000);
      function cleanup() {
        global.clearTimeout(timeout);
        video.removeEventListener("loadedmetadata", ready);
        video.removeEventListener("canplay", ready);
      }
      function ready() {
        if (!video.videoWidth || !video.videoHeight) return;
        cleanup();
        resolve();
      }
      video.addEventListener("loadedmetadata", ready);
      video.addEventListener("canplay", ready);
    });
  }

  function acquireCamera(requestId) {
    var request = navigator.mediaDevices.getUserMedia({video: {facingMode: "user"}, audio: false})
      .catch(function (failure) {
        if (failure && failure.name !== "OverconstrainedError") throw failure;
        return navigator.mediaDevices.getUserMedia({video: true, audio: false});
      });
    return new Promise(function (resolve, reject) {
      var settled = false;
      var timeout = global.setTimeout(function () {
        settled = true;
        reject(new Error("Camera permission timeout"));
      }, 15000);
      request.then(function (mediaStream) {
        if (settled || requestId !== cameraRequestId) {
          mediaStream.getTracks().forEach(function (track) { track.stop(); });
          return;
        }
        settled = true;
        global.clearTimeout(timeout);
        resolve(mediaStream);
      }).catch(function (failure) {
        if (settled) return;
        settled = true;
        global.clearTimeout(timeout);
        reject(failure);
      });
    });
  }

  function openModal(nextMode) {
    mode = nextMode || "profile";
    returnFocus = document.activeElement;
    clearCapture();
    consent.hidden = false;
    capture.hidden = true;
    modal.classList.remove("hide");
    document.getElementById("btnSaveProfilePhoto").textContent =
      mode === "registration" ? "Usar foto" : "Guardar Foto";
    document.getElementById("btnStartCamera").focus();
  }

  function openRegistrationPhoto() {
    registrationStatus.textContent = "";
    openModal("registration");
  }

  function startCamera() {
    var requestId = cameraRequestId + 1;
    cameraRequestId = requestId;
    consent.hidden = true;
    capture.hidden = false;
    video.hidden = false;
    error.textContent = "";
    document.getElementById("btnCaptureProfilePhoto").hidden = false;
    document.getElementById("btnCaptureProfilePhoto").disabled = true;
    if (!global.isSecureContext || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      showError();
      return;
    }
    acquireCamera(requestId)
      .then(function (mediaStream) {
        if (requestId !== cameraRequestId) {
          mediaStream.getTracks().forEach(function (track) { track.stop(); });
          return Promise.reject(new Error("Camera request cancelled"));
        }
        stream = mediaStream;
        video.srcObject = stream;
        return video.play().then(waitForVideoReady);
      })
      .then(function () {
        if (requestId !== cameraRequestId) return;
        document.getElementById("btnCaptureProfilePhoto").disabled = false;
        document.getElementById("btnCaptureProfilePhoto").focus();
      })
      .catch(function () {
        if (requestId === cameraRequestId) showError();
      });
  }

  function capturePhoto() {
    if (!stream || !video.videoWidth || !video.videoHeight) {
      showError();
      return;
    }
    var scale = Math.min(1, 640 / Math.max(video.videoWidth, video.videoHeight));
    canvas.width = Math.round(video.videoWidth * scale);
    canvas.height = Math.round(video.videoHeight * scale);
    canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
    canvas.toBlob(function (blob) {
      if (!blob) {
        showError();
        return;
      }
      capturedBlob = blob;
      previewUrl = URL.createObjectURL(blob);
      preview.src = previewUrl;
      preview.hidden = false;
      video.hidden = true;
      stopCamera();
      document.getElementById("btnCaptureProfilePhoto").hidden = true;
      document.getElementById("btnRetakeProfilePhoto").hidden = false;
      document.getElementById("btnSaveProfilePhoto").hidden = false;
      document.getElementById("btnSaveProfilePhoto").focus();
    }, "image/webp", 0.82);
  }

  function retakePhoto() {
    clearCapture();
    video.hidden = false;
    document.getElementById("btnCaptureProfilePhoto").hidden = false;
    document.getElementById("btnRetakeProfilePhoto").hidden = true;
    document.getElementById("btnSaveProfilePhoto").hidden = true;
    startCamera();
  }

  function uploadBlob(blob) {
    var formData = new FormData();
    var controller = global.AbortController ? new AbortController() : null;
    var timeout = global.setTimeout(function () {
      if (controller) controller.abort();
    }, 10000);
    formData.append("photo", blob, "profile.webp");
    return fetch("/api/profile/photo", {
      method: "POST",
      headers: {"X-CSRF-Token": csrfInput.value},
      body: formData,
      signal: controller ? controller.signal : undefined
    }).then(function (response) {
      return response.json().then(function (data) {
        if (!response.ok) throw new Error(data.error || "No se pudo guardar la fotografía.");
        return data;
      });
    }).finally(function () { global.clearTimeout(timeout); });
  }

  function renderRegistrationPhoto() {
    registrationPreview.hidden = !stagedPreviewUrl;
    registrationFallback.hidden = Boolean(stagedPreviewUrl);
    if (stagedPreviewUrl) registrationPreview.src = stagedPreviewUrl;
    else registrationPreview.removeAttribute("src");
    registrationAction.textContent = stagedPreviewUrl ? "Cambiar foto" : "Tomarse foto";
    registrationButton.setAttribute("aria-label", registrationAction.textContent);
    registrationButton.title = registrationAction.textContent;
  }

  function stagePhoto() {
    if (!capturedBlob) return;
    if (stagedPreviewUrl) URL.revokeObjectURL(stagedPreviewUrl);
    stagedBlob = capturedBlob;
    stagedPreviewUrl = URL.createObjectURL(stagedBlob);
    capturedBlob = null;
    renderRegistrationPhoto();
    registrationStatus.textContent = "Foto preparada. Se guardará al iniciar sesión.";
    closeModal();
  }

  function savePhoto() {
    if (!capturedBlob) return;
    if (mode === "registration") {
      stagePhoto();
      return;
    }
    uploadBlob(capturedBlob).then(function (data) {
      renderProfile(data.profile);
      if (global.GameLauncher) global.GameLauncher.refreshProfile(data.profile);
      closeModal();
    }).catch(function (failure) {
      error.textContent = failure.message;
    });
  }

  function discardRegistrationPhoto() {
    stopCamera();
    stagedBlob = null;
    if (stagedPreviewUrl) URL.revokeObjectURL(stagedPreviewUrl);
    stagedPreviewUrl = null;
    registrationStatus.textContent = "";
    renderRegistrationPhoto();
  }

  function submitRegistrationPhoto() {
    if (!stagedBlob) return Promise.resolve(null);
    var blob = stagedBlob;
    return uploadBlob(blob).then(function (data) {
      renderProfile(data.profile);
      if (global.GameLauncher) global.GameLauncher.refreshProfile(data.profile);
      return data.profile;
    }).catch(function () {
      var notice = document.getElementById("profilePhotoNotice");
      notice.textContent = "No se pudo guardar la fotografía. Puedes seguir utilizando el juego sin fotografía.";
      notice.hidden = false;
      global.setTimeout(function () { notice.hidden = true; }, 8000);
      return null;
    }).finally(discardRegistrationPhoto);
  }

  function setImage(image, fallback, url, initial) {
    image.hidden = !url;
    fallback.hidden = Boolean(url);
    if (url) image.src = url;
    else image.removeAttribute("src");
    if (initial) fallback.textContent = initial;
  }

  function renderProfile(profile) {
    currentPhotoUrl = profile.photo_url || null;
    var initial = (profile.name || "V").charAt(0).toUpperCase();
    setImage(
      document.getElementById("profilePhotoImage"),
      document.getElementById("profilePhotoFallback"),
      currentPhotoUrl,
      initial
    );
    var header = document.querySelector(".profile-avatar");
    header.textContent = currentPhotoUrl ? "" : initial;
    header.style.backgroundImage = currentPhotoUrl ? "url('" + currentPhotoUrl + "')" : "";
    var result = document.getElementById("resultProfilePhoto");
    result.hidden = !currentPhotoUrl;
    if (currentPhotoUrl) result.src = currentPhotoUrl;
    else result.removeAttribute("src");
    openButton.textContent = currentPhotoUrl ? "🗑 Cambiar Foto" : "📸 Tomarse Foto";
    openButton.setAttribute("aria-label", currentPhotoUrl ? "Cambiar foto" : "Tomarse foto");
  }

  function trapFocus(event) {
    if (event.key === "Escape") {
      closeModal();
      return;
    }
    if (event.key !== "Tab" || modal.classList.contains("hide")) return;
    var focusable = Array.from(modal.querySelectorAll("button:not([hidden]):not(:disabled)"));
    if (!focusable.length) return;
    var first = focusable[0];
    var last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  openButton.addEventListener("click", function () { openModal("profile"); });
  registrationButton.addEventListener("click", openRegistrationPhoto);
  document.getElementById("visitorNameInput").addEventListener("input", function (event) {
    if (!stagedPreviewUrl) {
      registrationFallback.textContent = (event.target.value.trim() || "V").charAt(0).toUpperCase();
    }
  });
  document.getElementById("btnCloseProfilePhoto").addEventListener("click", closeModal);
  document.getElementById("btnCancelProfilePhoto").addEventListener("click", closeModal);
  document.getElementById("btnStartCamera").addEventListener("click", startCamera);
  document.getElementById("btnCaptureProfilePhoto").addEventListener("click", capturePhoto);
  document.getElementById("btnRetakeProfilePhoto").addEventListener("click", retakePhoto);
  document.getElementById("btnSaveProfilePhoto").addEventListener("click", savePhoto);
  modal.addEventListener("click", function (event) {
    if (event.target === modal) closeModal();
  });
  modal.addEventListener("keydown", trapFocus);
  global.addEventListener("pagehide", discardRegistrationPhoto);
  global.ProfilePhoto = {
    renderProfile: renderProfile,
    close: closeModal,
    discardRegistrationPhoto: discardRegistrationPhoto,
    submitRegistrationPhoto: submitRegistrationPhoto
  };
})(window);
