<script setup>
import { onMounted, ref } from 'vue'
import AppUpdateStatus from './AppUpdateStatus.vue'

defineProps({ serverInfo: Object, health: Object, displayMessage: String })
defineEmits(['navigate'])
const bannerImage = ref(null)
const bannerReady = ref(false)
onMounted(() => {
  if (bannerImage.value?.complete) bannerReady.value = true
})
const features = [
  { icon: 'mdi-image-multiple-outline', title: 'Imagine it. Create it.', text: 'Turn a prompt into artwork or a short video. Animate a saved image and explore different local AI models.', page: 'generate', action: 'Create something' },
  { icon: 'mdi-monitor-small', title: 'Give your ideas a screen.', text: 'Send your creations over Wi-Fi to a supported ESP32 display. The app handles the sizing for your board.', page: 'firmware', action: 'Set up a display' },
  { icon: 'mdi-play-circle-outline', title: 'Keep the art playing.', text: 'Save favorites to the SD card and configure a Display Experience to play them when the server is offline.', page: 'display-experience', action: 'Explore Display Experience' },
]
</script>

<template>
  <article class="about-page" aria-labelledby="about-title">
    <div class="about-banner" :class="{ 'about-banner-ready': bannerReady }">
      <img ref="bannerImage" :src="'/ui/about/espimageserver-banner.png'" alt="ESPImageServer — Free local AI image and video generation for your ESP32" width="2172" height="724" @load="bannerReady = true" @error="bannerReady = true" />
    </div>
    <section class="about-intro">
      <div>
        <p class="about-eyebrow">YOUR COMPUTER. YOUR CREATIVITY.</p>
        <h1 id="about-title">Big ideas.<br><span>Tiny displays.</span></h1>
        <p class="about-lead">A little screen can hold a whole new world. ESPImageServer brings local AI image and video generation to your ESP32 projects, from the first prompt to the finished display.</p>
      </div>
      <div class="about-promise">
        <v-icon icon="mdi-creation-outline" size="32" color="primary" />
        <h2>Make more. No subscription.</h2>
        <p>No API registration, API key, or per-generation fee. Your prompts and creations stay on your computer.</p>
        <p class="about-requirements">Generation requires a supported NVIDIA GPU with CUDA. Internet access is needed to download dependencies and models.</p>
      </div>
    </section>

    <section class="about-support" aria-labelledby="about-support-title">
      <div class="about-support-icon"><v-icon icon="mdi-lifebuoy" size="28" color="primary" aria-hidden="true" /></div>
      <div>
        <h2 id="about-support-title">Need help?</h2>
        <p>Find answers and setup tips in the troubleshooting guide on GitHub.</p>
      </div>
      <v-btn href="https://github.com/thelastoutpostworkshop/ESPImageServer#troubleshooting" target="_blank" rel="noopener noreferrer" color="primary" variant="flat" prepend-icon="mdi-github" append-icon="mdi-open-in-new">Get help</v-btn>
    </section>

    <section class="about-features" aria-label="What you can create">
      <div v-for="(feature, index) in features" :key="feature.title" class="about-feature">
        <div class="about-feature-top"><v-icon :icon="feature.icon" size="28" /><span>0{{ index + 1 }}</span></div>
        <h2>{{ feature.title }}</h2>
        <p>{{ feature.text }}</p>
        <v-btn variant="text" color="primary" append-icon="mdi-arrow-right" @click="$emit('navigate', feature.page)">{{ feature.action }}</v-btn>
      </div>
    </section>

    <section class="about-system" aria-labelledby="about-system-title">
      <div class="about-section-heading"><h2 id="about-system-title">On this computer</h2><v-chip size="small" variant="tonal">{{ serverInfo?.version ? `Version ${serverInfo.version}` : 'Loading version…' }}</v-chip></div>
      <dl class="about-system-grid">
        <div><dt>Generation hardware</dt><dd>{{ serverInfo?.processing || (health?.device === 'cuda' ? 'NVIDIA CUDA' : 'Loading hardware information…') }}</dd></div>
        <div><dt>Selected image model</dt><dd>{{ serverInfo?.model_description || 'Loading model information…' }}</dd></div>
        <div><dt>Active display</dt><dd>{{ displayMessage }}</dd></div>
      </dl>
      <AppUpdateStatus :current-version="serverInfo?.version" />
    </section>

    <footer class="about-footer">
      <div><p class="about-eyebrow">THE LAST OUTPOST WORKSHOP</p><h2>Built for your next project.</h2><p>Explore the source, find new releases, or help make the app better.</p></div>
      <div class="about-links">
        <v-btn href="https://github.com/thelastoutpostworkshop/ESPImageServer" target="_blank" rel="noopener noreferrer" variant="tonal" prepend-icon="mdi-github">Project on GitHub</v-btn>
        <v-btn href="https://github.com/thelastoutpostworkshop/ESPImageServer/issues" target="_blank" rel="noopener noreferrer" variant="text" append-icon="mdi-open-in-new">Report an issue</v-btn>
      </div>
    </footer>
  </article>
</template>

<style scoped>
.about-page { max-width: 1600px; margin-inline: auto; container-type: inline-size; }
.about-banner { overflow: hidden; border-radius: 20px; border: 1px solid rgba(var(--v-theme-primary), .25); background: rgb(var(--v-theme-surface)); opacity: 0; }
.about-banner-ready { opacity: 1; animation: banner-intro 900ms cubic-bezier(.22, 1, .36, 1) both; }
.about-banner img { display: block; width: 100%; height: auto; }
@keyframes banner-intro {
  from { opacity: 0; transform: translateY(18px) scale(.985); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}
@media (prefers-reduced-motion: reduce) {
  .about-banner { opacity: 1; animation: none; }
}
.about-intro { display: grid; grid-template-columns: minmax(0, 1fr); gap: 32px; padding: clamp(24px, 4cqi, 64px) 0; align-items: center; }
.about-eyebrow { font-size: .72rem; letter-spacing: .16em; font-weight: 700; color: rgb(var(--v-theme-primary)); margin-bottom: 14px; }
h1 { font-size: clamp(2.3rem, 5cqi, 4.5rem); line-height: 1.05; letter-spacing: -.04em; font-weight: 750; }
h1 span { color: rgb(var(--v-theme-primary)); }
.about-lead { max-width: 62ch; margin-top: 24px; font-size: 1.08rem; line-height: 1.8; color: rgba(var(--v-theme-on-background), .8); }
h2 { font-size: 1.2rem; line-height: 1.4; }
.about-promise { padding: clamp(24px, 3cqi, 40px); border: 1px solid rgba(var(--v-theme-primary), .25); border-radius: 18px; background: linear-gradient(135deg, rgba(var(--v-theme-primary), .12), rgba(var(--v-theme-primary), .02)); }
.about-promise h2 { margin: 18px 0 12px; }
.about-promise p { line-height: 1.7; }
.about-requirements { margin-top: 20px; font-size: .85rem; color: rgba(var(--v-theme-on-background), .65); }
.about-support { display: grid; grid-template-columns: auto minmax(0, 1fr); align-items: center; gap: 16px; margin-bottom: 32px; padding: 20px 24px; border: 1px solid rgba(var(--v-theme-primary), .45); border-radius: 16px; background: linear-gradient(110deg, rgba(var(--v-theme-primary), .18), rgba(var(--v-theme-primary), .04)); }
.about-support-icon { display: grid; place-items: center; width: 48px; height: 48px; border-radius: 12px; background: rgba(var(--v-theme-primary), .12); }
.about-support p { margin-top: 4px; line-height: 1.6; color: rgba(var(--v-theme-on-background), .8); }
.about-support .v-btn { grid-column: 1 / -1; justify-self: start; max-width: 100%; height: auto; min-height: 44px; }
.about-support :deep(.v-btn__content) { white-space: normal; }
.about-features { display: grid; grid-template-columns: minmax(0, 1fr); gap: 18px; }
.about-feature { display: flex; flex-direction: column; min-width: 0; padding: 28px; border: 1px solid rgba(var(--v-theme-on-background), .12); border-radius: 16px; background: rgb(var(--v-theme-surface)); }
.about-feature-top { display: flex; justify-content: space-between; align-items: center; color: rgb(var(--v-theme-primary)); margin-bottom: 28px; }
.about-feature-top span { font-size: .85rem; letter-spacing: .12em; opacity: .65; }
.about-feature p { margin: 14px 0 24px; line-height: 1.7; color: rgba(var(--v-theme-on-surface), .75); }
.about-feature .v-btn { align-self: flex-start; margin-top: auto; max-width: 100%; height: auto; min-height: 40px; }
.about-feature :deep(.v-btn__content) { white-space: normal; text-align: left; }
.about-system { margin-top: 32px; padding: 28px; border-radius: 16px; background: rgba(var(--v-theme-on-background), .035); }
.about-section-heading { display: flex; flex-wrap: wrap; align-items: center; gap: 16px; justify-content: space-between; }
.about-system-grid { display: grid; gap: 24px; margin-top: 24px; }
.about-system-grid > div { min-width: 0; }
dt { font-size: .8rem; color: rgba(var(--v-theme-on-background), .6); margin-bottom: 8px; }
dd { margin: 0; line-height: 1.6; overflow-wrap: anywhere; }
.about-footer { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 24px; padding: 40px 0 16px; }
.about-footer p:last-child { margin-top: 10px; color: rgba(var(--v-theme-on-background), .7); }
.about-links { display: flex; flex-wrap: wrap; gap: 12px; }
@container (min-width: 760px) {
  .about-intro { grid-template-columns: minmax(0, 1.3fr) minmax(0, 1fr); }
  .about-support { grid-template-columns: auto minmax(0, 1fr) auto; }
  .about-support .v-btn { grid-column: auto; justify-self: end; }
  .about-features, .about-system-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
</style>
