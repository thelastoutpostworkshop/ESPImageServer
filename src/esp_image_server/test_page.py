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
    form, .result, .devices { background: #1f2937; border: 1px solid #374151; border-radius: 14px; padding: 18px; margin-top: 18px; }
    textarea, select { width: 100%; box-sizing: border-box; min-height: 40px; resize: vertical; padding: 10px 12px; border-radius: 8px; border: 1px solid #475569; background: #0f172a; color: inherit; font: inherit; }
    button, .download { margin-top: 12px; padding: 10px 16px; border: 0; border-radius: 8px; background: #38bdf8; color: #082f49; font-weight: 700; cursor: pointer; text-decoration: none; display: inline-block; }
    button:disabled { opacity: .6; cursor: wait; } #status, #device-status, #pairing-code { min-height: 1.4em; } #image { display: none; width: 100%; margin-top: 14px; border-radius: 8px; } .download { display: none; background: #a7f3d0; color: #064e3b; } .devices h2 { margin: 0 0 8px; font-size: 1.1rem; } .device-actions { display: flex; gap: 10px; align-items: center; } .device-actions button { margin-top: 0; } .online { color: #86efac; } .offline { color: #fbbf24; }
  </style>
</head>
<body>
  <main>
    <section class="hero" aria-label="ESPImageServer welcome">
      <img src="/assets/welcome-hero-horizontal.png" alt="ESPImageServer: local AI images for ESP32 displays">
    </section>
    <div class="brand">
      <img src="/assets/test-page-logo.png" alt="ESPImageServer logo">
      <div><h1>Generate a test image</h1>
    <p id="health">Checking server status…</p>
      </div>
    </div>
    <section class="devices">
      <h2>ESP32 display</h2>
      <label for="device">Send generated images to</label>
      <select id="device"><option value="">No paired displays found</option></select>
      <div class="device-actions">
        <button id="refresh-devices" type="button">Refresh displays</button>
        <button id="create-pairing" type="button">Pair a new ESP32</button>
      </div>
      <p id="pairing-code" role="status"></p>
      <p id="device-status" role="status"></p>
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
      <button id="send-to-display" type="button" disabled>Send to display</button>
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
    const deviceSelect = document.getElementById('device');
    const refreshDevices = document.getElementById('refresh-devices');
    const createPairing = document.getElementById('create-pairing');
    const pairingCode = document.getElementById('pairing-code');
    const deviceStatus = document.getElementById('device-status');
    const sendToDisplay = document.getElementById('send-to-display');
    let currentUrl;
    let currentImage;

    function escapeHtml(value) {
      const element = document.createElement('span');
      element.textContent = value;
      return element.innerHTML;
    }

    fetch('/health').then(async response => {
      const data = await response.json();
      health.textContent = `Server is ${data.status} (${data.device})`;
    }).catch(() => health.textContent = 'Server status is unavailable.');

    async function loadDevices() {
      try {
        const devices = await fetch('/devices').then(response => response.json());
        const selected = deviceSelect.value;
        deviceSelect.innerHTML = devices.length
          ? devices.map(device => `<option value="${device.id}">${escapeHtml(device.name)} — ${device.online ? 'online' : 'offline'} (${device.queued_images} queued)</option>`).join('')
          : '<option value="">No paired displays found</option>';
        if ([...deviceSelect.options].some(option => option.value === selected)) deviceSelect.value = selected;
        deviceStatus.innerHTML = devices.length
          ? `${devices.length} paired display${devices.length === 1 ? '' : 's'} found.`
          : 'Pair an ESP32 to send images directly to its screen.';
      } catch {
        deviceStatus.textContent = 'Could not load paired displays.';
      }
    }

    refreshDevices.addEventListener('click', loadDevices);
    createPairing.addEventListener('click', async () => {
      createPairing.disabled = true;
      try {
        const pairing = await fetch('/pairing-codes', {method: 'POST'}).then(async response => {
          if (!response.ok) throw new Error('Could not create a pairing code');
          return response.json();
        });
        pairingCode.innerHTML = `Enter pairing code <strong>${pairing.code}</strong> on the ESP32 within ${Math.floor(pairing.expires_in_seconds / 60)} minutes.`;
      } catch (error) {
        pairingCode.textContent = error.message;
      } finally {
        createPairing.disabled = false;
      }
    });

    sendToDisplay.addEventListener('click', async () => {
      if (!currentImage || !deviceSelect.value) return;
      sendToDisplay.disabled = true;
      deviceStatus.textContent = 'Queueing image for the display...';
      try {
        const response = await fetch(`/devices/${deviceSelect.value}/images`, {
          method: 'POST', headers: {'Content-Type': 'image/jpeg'}, body: currentImage
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || 'Could not queue image');
        deviceStatus.textContent = `Queued for ${data.device}. The ESP32 will retrieve it shortly.`;
        loadDevices();
      } catch (error) {
        deviceStatus.textContent = error.message;
      } finally {
        sendToDisplay.disabled = false;
      }
    });

    loadDevices();

    form.addEventListener('submit', async event => {
      event.preventDefault();
      submit.disabled = true;
      status.textContent = 'Generating image… this can take a little while.';
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
        currentImage = await response.blob();
        currentUrl = URL.createObjectURL(currentImage);
        image.src = currentUrl;
        image.style.display = 'block';
        download.href = currentUrl;
        download.style.display = 'inline-block';
        sendToDisplay.disabled = !deviceSelect.value;
        result.hidden = false;
        status.textContent = 'Image ready. This is the same JPEG returned to an ESP32.';
      } catch (error) {
        status.textContent = `Could not generate the image: ${error.message}`;
      } finally {
        submit.disabled = false;
      }
    });
  </script>
</body>
</html>"""
