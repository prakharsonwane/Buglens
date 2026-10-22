const CACHE_NAME = "buglens-static-v2";

const STATIC_ASSETS = [
  "/static/manifest.json",
  "/static/offline.html"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(async (cache) => {
      for (const asset of STATIC_ASSETS) {
        try {
          await cache.add(asset);
        } catch (error) {
          // Continue installation if an optional asset is unavailable.
        }
      }
      await self.skipWaiting();
    })
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then(async (cacheNames) => {
      await Promise.all(
        cacheNames
          .filter((name) => name.startsWith("buglens-") && name !== CACHE_NAME)
          .map((name) => caches.delete(name))
      );
      await self.clients.claim();
    })
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);

  // Only handle same-origin GET requests.
  if (
    request.method !== "GET" ||
    url.origin !== self.location.origin
  ) {
    return;
  }

  // Never cache private pages or API responses.
  if (
    url.pathname.startsWith("/api/") ||
    url.pathname.startsWith("/project/") ||
    url.pathname === "/dashboard" ||
    url.pathname === "/login" ||
    url.pathname === "/register" ||
    url.pathname === "/logout"
  ) {
    return;
  }

  // Cache-first for local static assets.
  if (url.pathname.startsWith("/static/")) {
    event.respondWith(
      caches.match(request).then(async (cachedResponse) => {
        if (cachedResponse) {
          return cachedResponse;
        }

        try {
          const response = await fetch(request);

          if (response.ok && response.type === "basic") {
            const cache = await caches.open(CACHE_NAME);
            await cache.put(request, response.clone());
          }

          return response;
        } catch (error) {
          return new Response("This resource is unavailable offline.", {
            status: 503,
            headers: { "Content-Type": "text/plain; charset=utf-8" }
          });
        }
      })
    );
    return;
  }

  // Network-first for public navigation, with an offline fallback.
  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request).catch(async () => {
        const offlinePage = await caches.match("/static/offline.html");

        if (offlinePage) {
          return offlinePage;
        }

        return new Response(
          "<!doctype html><html lang='en'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>BugLens Offline</title><body><h1>You're offline</h1><p>Reconnect to the internet and try again.</p></body></html>",
          {
            status: 503,
            headers: { "Content-Type": "text/html; charset=utf-8" }
          }
        );
      })
    );
  }
});