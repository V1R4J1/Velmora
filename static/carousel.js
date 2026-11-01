document.querySelectorAll("[data-carousel]").forEach((carousel) => {
  const viewport = carousel.querySelector("[data-carousel-viewport]");
  const slides = Array.from(carousel.querySelectorAll("[data-carousel-slide]"));
  const dots = Array.from(carousel.querySelectorAll("[data-carousel-dot]"));
  const status = carousel.querySelector("[data-carousel-status]");
  if (!viewport || slides.length < 2) return;

  let current = 0;
  let touchStart = null;
  const pauseButton = carousel.querySelector("[data-carousel-pause]");
  const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
  let paused = false;
  let explicitPlay = false;
  let focused = false;
  let timer = null;

  function updateRotation() {
    clearInterval(timer);
    timer = null;
    const running = !paused && (!focused || explicitPlay) && !document.hidden && (!motion.matches || explicitPlay);
    if (running) timer = setInterval(() => show(current + 1), 4000);
    if (pauseButton) {
      pauseButton.textContent = running ? "Pause" : "Play";
      pauseButton.setAttribute("aria-label", running ? "Pause carousel" : "Play carousel");
    }
    status?.setAttribute("aria-live", running ? "off" : "polite");
  }

  pauseButton?.addEventListener("click", () => {
    const wasRunning = timer !== null;
    paused = wasRunning;
    explicitPlay = !wasRunning;
    updateRotation();
  });
  // A stationary pointer over the full-width hero must not stop the demo.
  // Keyboard focus pauses rotation; Play explicitly resumes it while focused.
  carousel.addEventListener("focusin", (event) => {
    focused = Boolean(event.target.matches?.(":focus-visible"));
    explicitPlay = false;
    updateRotation();
  });
  carousel.addEventListener("focusout", (event) => {
    if (!carousel.contains(event.relatedTarget)) { focused = false; updateRotation(); }
  });
  document.addEventListener("visibilitychange", updateRotation);
  motion.addEventListener?.("change", () => { explicitPlay = false; updateRotation(); });


  function show(index) {
    current = (index + slides.length) % slides.length;
    slides.forEach((slide, i) => {
      const active = i === current;
      if (active) slide.setAttribute("data-active", "true");
      else slide.removeAttribute("data-active");
      slide.inert = !active;
      slide.setAttribute("aria-hidden", String(!active));
    });
    dots.forEach((dot, i) => {
      if (i === current) dot.setAttribute("aria-current", "true");
      else dot.removeAttribute("aria-current");
    });
    if (status) status.textContent = `Slide ${current + 1} of ${slides.length}`;
  }

  carousel.querySelector("[data-carousel-prev]")?.addEventListener("click", () => show(current - 1));
  carousel.querySelector("[data-carousel-next]")?.addEventListener("click", () => show(current + 1));
  dots.forEach((dot, i) => dot.addEventListener("click", () => show(i)));
  carousel.addEventListener("keydown", (event) => {
    if (event.target.matches?.("input, textarea, select, [contenteditable='true']")) return;
    if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      event.preventDefault();
      show(current + (event.key === "ArrowRight" ? 1 : -1));
    } else if (event.key === "Home" || event.key === "End") {
      event.preventDefault();
      show(event.key === "Home" ? 0 : slides.length - 1);
    }
  });
  viewport.addEventListener("touchstart", (event) => {
    const touch = event.touches[0];
    touchStart = touch ? { x: touch.clientX, y: touch.clientY } : null;
  }, { passive: true });
  viewport.addEventListener("touchend", (event) => {
    if (!touchStart || !event.changedTouches[0]) return;
    const dx = event.changedTouches[0].clientX - touchStart.x;
    const dy = event.changedTouches[0].clientY - touchStart.y;
    if (Math.abs(dx) > 50 && Math.abs(dx) > Math.abs(dy)) show(current + (dx < 0 ? 1 : -1));
    touchStart = null;
  }, { passive: true });
  show(0);
  updateRotation();
});
