<template>
  <figure class="boot-mode-guide">
    <div class="button-demo" aria-hidden="true">
      <span class="board-hole board-hole-left" />
      <span class="board-hole board-hole-right" />
      <div class="demo-control">
        <v-icon icon="mdi-hand-pointing-down" class="press-hand boot-hand" size="32" />
        <div class="button-socket"><span class="button-cap boot-cap">BOOT</span></div>
      </div>
      <div class="demo-control">
        <v-icon icon="mdi-hand-pointing-down" class="press-hand reset-hand" size="32" />
        <div class="button-socket"><span class="button-cap reset-cap">RESET / EN</span></div>
      </div>
    </div>
    <figcaption>
      <p class="text-caption text-medium-emphasis mb-2">Use the buttons on your board</p>
      <ol class="button-sequence">
        <li class="sequence-step boot-step"><span class="step-number" aria-hidden="true">1</span><span>Hold <strong>BOOT</strong></span></li>
        <li class="sequence-step reset-step"><span class="step-number" aria-hidden="true">2</span><span>Tap <strong>RESET / EN</strong><small>Keep BOOT held</small></span></li>
        <li class="sequence-step release-step"><span class="step-number" aria-hidden="true">3</span><span>Release <strong>BOOT</strong></span></li>
      </ol>
      <p class="text-caption text-medium-emphasis mt-2">We’re still trying to connect.</p>
    </figcaption>
  </figure>
</template>

<style scoped>
.boot-mode-guide {
  --cycle: 8s;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 20px;
  width: fit-content;
  max-width: 100%;
  margin: 0;
  padding: 14px 18px;
  border: 1px solid rgb(var(--v-theme-primary), .24);
  border-radius: 12px;
  background: rgb(var(--v-theme-primary), .05);
}
.button-demo {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  flex: 0 1 218px;
  min-width: 0;
  max-width: 100%;
  gap: 20px;
  height: 94px;
  margin-top: 22px;
  border: 1px solid rgb(var(--v-theme-primary), .3);
  border-radius: 12px;
  background: linear-gradient(145deg, rgb(var(--v-theme-primary), .12), rgb(var(--v-theme-surface)));
  user-select: none;
}
.board-hole {
  position: absolute;
  top: 8px;
  width: 7px;
  height: 7px;
  border: 1px solid rgb(var(--v-theme-on-surface), .3);
  border-radius: 50%;
}
.board-hole-left { left: 8px; }
.board-hole-right { right: 8px; }
.demo-control { position: relative; }
.button-socket {
  padding: 5px 5px 9px;
  border-radius: 8px;
  background: rgb(var(--v-theme-on-surface), .12);
}
.button-cap {
  display: grid;
  place-items: center;
  width: 74px;
  height: 32px;
  border: 1px solid rgb(var(--v-theme-on-surface), .25);
  border-radius: 5px;
  background: rgb(var(--v-theme-surface));
  color: rgb(var(--v-theme-on-surface));
  box-shadow: 0 4px 0 rgb(var(--v-theme-on-surface), .2);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: .2px;
}
.press-hand {
  position: absolute;
  top: -30px;
  left: 26px;
  z-index: 1;
  opacity: 0;
}
.boot-hand { color: rgb(var(--v-theme-primary)); animation: boot-hand var(--cycle) infinite; }
.reset-hand { color: rgb(var(--v-theme-warning)); animation: reset-hand var(--cycle) infinite; }
.boot-cap { animation: boot-press var(--cycle) infinite; }
.reset-cap { animation: reset-press var(--cycle) infinite; }
.button-sequence { display: grid; gap: 6px; padding: 0; list-style: none; }
.sequence-step { display: flex; align-items: center; gap: 8px; font-size: 14px; opacity: .65; }
.sequence-step small { display: block; font-size: 11px; }
.step-number {
  display: grid;
  place-items: center;
  flex: 0 0 22px;
  height: 22px;
  border-radius: 50%;
  background: rgb(var(--v-theme-primary), .18);
  color: rgb(var(--v-theme-primary));
  font-size: 12px;
  font-weight: 700;
}
.boot-step { animation: boot-step var(--cycle) infinite; }
.reset-step { animation: reset-step var(--cycle) infinite; }
.release-step { animation: release-step var(--cycle) infinite; }
@keyframes boot-press {
  0%, 8%, 74%, 100% { transform: translateY(0); background: rgb(var(--v-theme-surface)); color: rgb(var(--v-theme-on-surface)); box-shadow: 0 4px 0 rgb(var(--v-theme-on-surface), .2); }
  12%, 68% { transform: translateY(3px); background: rgb(var(--v-theme-primary)); color: rgb(var(--v-theme-on-primary)); box-shadow: 0 1px 0 rgb(var(--v-theme-on-surface), .2); }
}
@keyframes reset-press {
  0%, 34%, 50%, 100% { transform: translateY(0); background: rgb(var(--v-theme-surface)); color: rgb(var(--v-theme-on-surface)); box-shadow: 0 4px 0 rgb(var(--v-theme-on-surface), .2); }
  38%, 46% { transform: translateY(3px); background: rgb(var(--v-theme-warning)); color: rgb(var(--v-theme-on-warning)); box-shadow: 0 1px 0 rgb(var(--v-theme-on-surface), .2); }
}
@keyframes boot-hand {
  0%, 8%, 74%, 100% { opacity: 0; transform: translateY(-5px); }
  12%, 68% { opacity: 1; transform: translateY(4px); }
}
@keyframes reset-hand {
  0%, 34%, 52%, 100% { opacity: 0; transform: translateY(-5px); }
  38%, 46% { opacity: 1; transform: translateY(4px); }
}
@keyframes boot-step {
  0%, 30% { opacity: 1; }
  34%, 100% { opacity: .65; }
}
@keyframes reset-step {
  0%, 30%, 72%, 100% { opacity: .65; }
  34%, 68% { opacity: 1; }
}
@keyframes release-step {
  0%, 68%, 100% { opacity: .65; }
  74%, 94% { opacity: 1; }
}
@media (max-width: 480px) {
  .boot-mode-guide { gap: 12px; padding: 12px; }
}
@media (prefers-reduced-motion: reduce) {
  .button-cap, .press-hand, .sequence-step { animation: none; }
  .sequence-step { opacity: 1; }
}
</style>
