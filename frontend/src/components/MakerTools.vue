<script setup>
import { makerTools, supportLinks } from '../makerResources.js'
</script>

<template>
  <article class="maker-tools" aria-labelledby="maker-tools-title">
    <header class="maker-tools-header">
      <p class="maker-tools-eyebrow">THE LAST OUTPOST WORKSHOP</p>
      <h1 id="maker-tools-title">Maker Tools</h1>
      <p>Free utilities for ESP32 and embedded projects, from planning your hardware to preparing its software.</p>
    </header>

    <section class="maker-tools-support" aria-labelledby="maker-tools-support-title">
      <v-icon icon="mdi-heart-outline" size="30" color="primary" aria-hidden="true" />
      <div class="maker-tools-support-copy">
        <h2 id="maker-tools-support-title">Support the project</h2>
        <p>ESPImageServer and these maker tools are free to use. If they help with your projects, a donation supports ongoing development.</p>
      </div>
      <div class="maker-tools-support-actions">
        <v-btn v-for="link in supportLinks" :key="link.href" :href="link.href" :prepend-icon="link.icon"
          target="_blank" rel="noopener noreferrer" color="primary" variant="tonal">
          {{ link.title }}
        </v-btn>
      </div>
    </section>

    <section class="maker-tools-grid" aria-label="Maker utilities">
      <article v-for="(tool, index) in makerTools" :key="tool.id" class="maker-tool-card"
        :style="{ '--tool-reveal-delay': `${index * 100}ms` }" :aria-labelledby="`maker-tool-${tool.id}`">
        <a class="maker-tool-thumbnail" :href="tool.tutorialHref || tool.href" target="_blank" rel="noopener noreferrer"
          :aria-label="tool.tutorialHref ? `Watch the ${tool.title} tutorial` : `${tool.action}: ${tool.title}`">
          <img :src="tool.thumbnail" :alt="`${tool.title} preview`" loading="lazy" width="480" height="270" />
          <span class="maker-tool-icon" aria-hidden="true"><v-icon :icon="tool.icon" size="22" /></span>
        </a>
        <div class="maker-tool-copy">
          <h2 :id="`maker-tool-${tool.id}`">{{ tool.title }}</h2>
          <p>{{ tool.description }}</p>
          <a v-if="tool.sourceHref" class="maker-tool-source" :href="tool.sourceHref" target="_blank" rel="noopener noreferrer"
            :aria-label="`View ${tool.title} source`">View source <v-icon icon="mdi-open-in-new" size="14" aria-hidden="true" /></a>
        </div>
        <footer class="maker-tool-actions">
          <v-btn v-if="tool.tutorialHref" :href="tool.tutorialHref" target="_blank" rel="noopener noreferrer"
            prepend-icon="mdi-youtube" variant="text" color="primary" :aria-label="`Watch the ${tool.title} tutorial`">
            Watch tutorial
          </v-btn>
          <v-btn class="maker-tool-primary-action" :href="tool.href" target="_blank" rel="noopener noreferrer"
            append-icon="mdi-open-in-new" variant="tonal" color="primary" :aria-label="`${tool.action}: ${tool.title}`">
            {{ tool.action }}
          </v-btn>
        </footer>
      </article>
    </section>
  </article>
</template>

<style scoped>
.maker-tools { max-width: 1600px; margin-inline: auto; container-type: inline-size; }
.maker-tools-header { margin-bottom: 28px; }
.maker-tools-eyebrow { margin-bottom: 10px; font-size: .72rem; font-weight: 700; letter-spacing: .16em; color: rgb(var(--v-theme-primary)); }
h1 { font-size: clamp(2rem, 4cqi, 3rem); line-height: 1.2; letter-spacing: -.03em; }
.maker-tools-header > p:last-child { max-width: 70ch; margin-top: 14px; line-height: 1.7; color: rgba(var(--v-theme-on-background), .75); }
.maker-tools-support { display: grid; grid-template-columns: auto minmax(0, 1fr); align-items: center; gap: 20px; margin-bottom: 28px; padding: 24px; border: 1px solid rgba(var(--v-theme-primary), .25); border-radius: 16px; background: linear-gradient(120deg, rgba(var(--v-theme-primary), .1), rgba(var(--v-theme-primary), .025)); }
.maker-tools-support-copy { min-width: 0; }
.maker-tools-support h2 { margin-bottom: 8px; font-size: 1.1rem; line-height: 1.4; }
.maker-tools-support p { line-height: 1.7; color: rgba(var(--v-theme-on-background), .75); }
.maker-tools-support-actions { display: flex; flex-wrap: wrap; gap: 12px; grid-column: 2; min-width: 0; }
.maker-tools-grid { display: grid; grid-template-columns: minmax(0, 1fr); gap: 20px; }
.maker-tool-card { display: flex; flex-direction: column; min-width: 0; overflow: hidden; border: 1px solid rgba(var(--v-theme-on-background), .12); border-radius: 16px; background: rgb(var(--v-theme-surface)); }
.maker-tool-card { animation: maker-tool-reveal 650ms cubic-bezier(.22, 1, .36, 1) var(--tool-reveal-delay) both; }
.maker-tool-card:focus-within { animation: none; }
@keyframes maker-tool-reveal {
  from { opacity: 0; transform: translateY(24px) scale(.98); }
  to { opacity: 1; transform: none; }
}
@media (prefers-reduced-motion: reduce) {
  .maker-tool-card { animation: none; }
}
.maker-tool-thumbnail { position: relative; display: block; width: 50%; margin-inline: auto; aspect-ratio: 16 / 9; overflow: hidden; background: rgba(var(--v-theme-primary), .06); }
.maker-tool-thumbnail img { display: block; width: 100%; height: 100%; object-fit: cover; }
.maker-tool-thumbnail:focus-visible { outline: 3px solid rgb(var(--v-theme-primary)); outline-offset: -3px; }
.maker-tool-icon { position: absolute; bottom: 14px; left: 14px; display: grid; place-items: center; width: 40px; height: 40px; border: 1px solid rgba(var(--v-theme-primary), .25); border-radius: 10px; color: rgb(var(--v-theme-primary)); background: rgb(var(--v-theme-surface)); }
.maker-tool-copy { flex: 1; min-width: 0; padding: 12px 16px; }
.maker-tool-copy h2 { margin: 0; font-size: 1.1rem; line-height: 1.35; overflow-wrap: anywhere; }
.maker-tool-copy p { margin: 6px 0 8px; line-height: 1.5; color: rgba(var(--v-theme-on-surface), .75); overflow-wrap: anywhere; }
.maker-tool-source { display: inline-flex; align-items: center; gap: 6px; min-height: 28px; color: rgb(var(--v-theme-primary)); text-underline-offset: 3px; }
.maker-tool-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; padding: 8px 16px; border-top: 1px solid rgba(var(--v-theme-on-surface), .1); }
.maker-tool-primary-action { margin-inline-start: auto; }
.maker-tools :deep(.v-btn) { min-height: 44px; height: auto; max-width: 100%; }
.maker-tools :deep(.v-btn__content) { white-space: normal; line-height: 1.4; text-align: left; }
@container (min-width: 760px) {
  .maker-tools-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@container (max-width: 420px) {
  .maker-tools-support { grid-template-columns: minmax(0, 1fr); padding: 20px; }
  .maker-tools-support-actions { grid-column: 1; }
  .maker-tools-support-actions :deep(.v-btn) { width: 100%; }
  .maker-tool-actions { padding-inline: 12px; }
  .maker-tool-actions :deep(.v-btn) { width: 100%; }
  .maker-tool-primary-action { margin-inline-start: 0; }
}
</style>
