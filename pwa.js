
"use strict";

(() => {
  let installPrompt = null;

  const installButtons = () => {
    document.querySelectorAll("[data-install-app]").forEach((button) => {
      button.hidden = false;
    });
  };

  // Keep the button visible even if automatic installation
  // is not available in the current browser.
  installButtons();

  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    installPrompt = event;
    installButtons();
  });

  document.addEventListener("click", async (event) => {
    const button = event.target.closest?.("[data-install-app]");
    if (!button) return;

    if (!installPrompt) {
      alert(
        "Automatic installation is not available right now. " +
        "In Chrome, open the browser menu and look for " +
        "'Install app' or 'Add to Home screen'. " +
        "Make sure you are using HTTPS or localhost."
      );
      return;
    }

    const promptEvent = installPrompt;
    installPrompt = null;

    try {
      await promptEvent.prompt();
      await promptEvent.userChoice;
    } catch (error) {
      console.error("Installation prompt failed:", error);
    }
  });

  window.addEventListener("appinstalled", () => {
    installPrompt = null;
    document.querySelectorAll("[data-install-app]").forEach((button) => {
      button.hidden = true;
    });
    console.info("BugLens installed successfully.");
  });

  if ("serviceWorker" in navigator) {
    window.addEventListener("load", async () => {
      try {
        await navigator.serviceWorker.register("/service-worker.js");
        console.info("BugLens service worker registered.");
      } catch (error) {
        console.error("Service worker registration failed:", error);
      }
    });
  }
})();
