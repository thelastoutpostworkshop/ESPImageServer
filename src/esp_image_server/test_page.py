"""The small browser-based test interface served by the local server."""

TEST_PAGE_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ESPImageServer</title>
  <style>
    :root { color-scheme: dark; font-family: system-ui, sans-serif; background: #111827; color: #eef2ff; }
    body { margin: 0; min-height: 100vh; display: grid; place-items: center; }
    main { width: min(92vw, 760px); padding: 28px; }
    .hero { margin: 0 0 18px; background: #020816; border: 1px solid #164e78; border-radius: 16px; overflow: hidden; display: grid; place-items: center; }
    .hero img { display: block; width: 100%; max-height: min(62vh, 580px); object-fit: contain; }
    .brand { display: flex; align-items: center; gap: 16px; }
    .brand img { width: 70px; height: 70px; object-fit: contain; filter: drop-shadow(0 0 14px #38bdf880); }
    h1 { margin: 0 0 6px; } p { color: #cbd5e1; }
    form, .result, .delivery { background: #1f2937; border: 1px solid #374151; border-radius: 14px; padding: 18px; margin-top: 18px; }
    textarea { width: 100%; box-sizing: border-box; min-height: 40px; resize: vertical; padding: 10px 12px; border-radius: 8px; border: 1px solid #475569; background: #0f172a; color: inherit; font: inherit; }
    button, .download { margin-top: 12px; padding: 10px 16px; border: 0; border-radius: 8px; background: #38bdf8; color: #082f49; font-weight: 700; cursor: pointer; text-decoration: none; display: inline-block; }
    button:disabled { opacity: .6; cursor: wait; } #status { min-height: 1.4em; } #image { display: none; width: 100%; margin-top: 14px; border-radius: 8px; } .download { display: none; background: #a7f3d0; color: #064e3b; } .delivery h2 { margin: 0 0 8px; font-size: 1.1rem; }
  </style>
</head>
<body>
  <main>
    <section class="hero" aria-label="ESPImageServer welcome">
      <img src="/assets/welcome-hero-horizontal.png" alt="ESPImageServer: local AI images for ESP32 displays">
    </section>
    <div class="brand">
      <img src="/assets/test-page-logo.png" alt="ESPImageServer logo">
      <div><h1>Generate a test image</h1><p id="health">Checking server status...</p></div>
    </div>
    <section class="delivery">
      <h2>ESP32 display</h2>
      <p id="display-status">Waiting for the ESP32 board to report its integrated display...</p>
    </section>
    <form id="generate-form">
      <label for="prompt">Describe an image</label>
      <textarea id="prompt" required maxlength="1000">A cheerful small robot holding a paintbrush, friendly illustration</textarea>
      <button id="submit" type="submit">Generate image</button>
      <p id="status" role="status"></p>
    </form>
    <section class="result" id="result" hidden>
      <img id="image" alt="Generated image">
      <a id="download" class="download" download="esp-image.jpg">Download JPEG</a>
    </section>
  </main>
  <script>
    const health = document.getElementById('health');
    const form = document.getElementById('generate-form');
    const prompt = document.getElementById('prompt');
    const submit = document.getElementById('submit');
    const status = document.getElementById('status');
    const result = document.getElementById('result');
    const image = document.getElementById('image');
    const download = document.getElementById('download');
    const displayStatus = document.getElementById('display-status');
    let currentUrl;

    function escapeHtml(value) {
      const element = document.createElement('span');
      element.textContent = value;
      return element.innerHTML;
    }

    fetch('/server-info').then(async response => {
      const data = await response.json();
      health.innerHTML = `<strong>AI model: ${escapeHtml(data.model_name)}</strong><br>${escapeHtml(data.model_description)}<br>${escapeHtml(data.processing)}`;
    }).catch(() => health.textContent = 'Image generator information is unavailable.');

    async function loadDisplay() {
      try {
        const display = await fetch('/display').then(response => response.json());
        if (!display.connected) return;
        displayStatus.textContent = `${display.name} connected — ${display.width} x ${display.height}. Generated images will fit this screen.`;
      } catch {
        displayStatus.textContent = 'Display information is unavailable. You can set the size manually.';
      }
    }

    loadDisplay();
    setInterval(loadDisplay, 5000);

    form.addEventListener('submit', async event => {
      event.preventDefault();
      submit.disabled = true;
      status.textContent = 'Generating image... this can take a little while.';
      try {
        const response = await fetch('/generate', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({prompt: prompt.value})
        });
        if (!response.ok) {
          const error = await response.json().catch(() => ({}));
          throw new Error(error.detail || `Request failed (${response.status})`);
        }
        if (currentUrl) URL.revokeObjectURL(currentUrl);
        currentUrl = URL.createObjectURL(await response.blob());
        image.src = currentUrl;
        image.style.display = 'block';
        download.href = currentUrl;
        download.style.display = 'inline-block';
        result.hidden = false;
        status.textContent = 'Image ready. Your ESP32 display will pick it up shortly.';
      } catch (error) {
        status.textContent = `Could not generate the image: ${error.message}`;
      } finally {
        submit.disabled = false;
      }
    });
  </script>
</body>
</html>"""
