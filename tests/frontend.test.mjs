import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { runInNewContext } from "node:vm";

// Minimal browser interfaces for testing the scripts' observable behaviour.
class Element extends EventTarget {
  constructor(dataset = {}) {
    super();
    this.dataset = dataset;
    this.attributes = new Map();
    this.children = new Map();
    this.hidden = false;
    this.inert = false;
    this.textContent = "";
  }

  querySelectorAll(selector) {
    return this.children.get(selector) || [];
  }

  querySelector(selector) {
    return this.querySelectorAll(selector)[0] || null;
  }

  setAttribute(name, value) {
    this.attributes.set(name, value);
  }

  removeAttribute(name) {
    this.attributes.delete(name);
  }

  getAttribute(name) {
    return this.attributes.get(name) ?? null;
  }

  contains(target) {
    return target === this || [...this.children.values()].flat().some(child => child.contains?.(target));
  }

  fire(name) {
    this.dispatchEvent(new Event(name));
  }
}

function runScript(filename, document, reducedMotion = false) {
  const window = new Element();
  window.matchMedia = () => ({ matches: reducedMotion });
  const frames = new Map();
  const intervals = new Map();
  let frameId = 0;
  let time = 0;
  runInNewContext(readFileSync(new URL(`../static/${filename}`, import.meta.url), "utf8"), {
    document, window, Event,
    requestAnimationFrame: (callback) => {
      frames.set(++frameId, callback);
      return frameId;
    },
    cancelAnimationFrame: (id) => frames.delete(id),
    setInterval: (callback, delay) => { const id = ++frameId; intervals.set(id, { callback, delay, next: time + delay }); return id; },
    clearInterval: (id) => intervals.delete(id),
  });
  return {
    window,
    tickIntervals() { [...intervals.values()].forEach(({ callback }) => callback()); },
    advanceTime(milliseconds) {
      const target = time + milliseconds;
      while (intervals.size) {
        const next = Math.min(...[...intervals.values()].map(interval => interval.next));
        if (next > target) break;
        time = next;
        [...intervals.values()].filter(interval => interval.next <= time).forEach(interval => {
          interval.next += interval.delay; interval.callback();
        });
      }
      time = target;
    },
    flushFrames() {
      const callbacks = [...frames.values()];
      frames.clear();
      callbacks.forEach((callback) => callback());
    },
  };
}

function carouselFixture(count = 3, reducedMotion = false) {
  const document = new Element();
  const carousel = new Element();
  const viewport = new Element();
  viewport.clientWidth = 400;
  viewport.scrollLeft = 0;
  viewport.scrollTo = (options) => { viewport.lastScroll = options; };
  const slides = Array.from({ length: count }, () => new Element());
  const dots = Array.from({ length: count }, (_, i) => new Element({ carouselDot: String(i) }));
  const status = new Element();
  const previous = new Element();
  const next = new Element();
  const pause = new Element();
  document.children.set("[data-carousel]", [carousel]);
  carousel.children = new Map([
    ["[data-carousel-viewport]", [viewport]], ["[data-carousel-slide]", slides],
    ["[data-carousel-dot]", dots], ["[data-carousel-status]", [status]],
    ["[data-carousel-prev]", [previous]], ["[data-carousel-next]", [next]],
    ["[data-carousel-pause]", [pause]],
  ]);
  const runtime = runScript("carousel.js", document, reducedMotion);
  return { document, carousel, viewport, slides, dots, status, previous, next, pause, ...runtime };
}

test("carousel buttons wrap and expose only the active slide", () => {
  const { previous, next, slides, dots, status } = carouselFixture();
  assert.equal(status.textContent, "Slide 1 of 3");
  assert.deepEqual(slides.map((slide) => slide.inert), [false, true, true]);
  previous.fire("click");
  assert.equal(status.textContent, "Slide 3 of 3");
  next.fire("click");
  assert.equal(status.textContent, "Slide 1 of 3");
  dots[1].fire("click");
  assert.equal(status.textContent, "Slide 2 of 3");
  assert.equal(dots[1].getAttribute("aria-current"), "true");
  assert.equal(dots[0].getAttribute("aria-current"), null);
  assert.deepEqual(slides.map((slide) => slide.inert), [true, false, true]);
});

test("carousel rotates and respects reduced motion", () => {
  const normal = carouselFixture();
  normal.tickIntervals();
  assert.equal(normal.status.textContent, "Slide 2 of 3");
  const reduced = carouselFixture(3, true);
  reduced.tickIntervals();
  assert.equal(reduced.status.textContent, "Slide 1 of 3");
});

test("carousel advances every four seconds even with the pointer over the hero", () => {
  const { carousel, status, advanceTime } = carouselFixture();
  carousel.fire('mouseenter');
  advanceTime(3999);
  assert.equal(status.textContent, 'Slide 1 of 3');
  advanceTime(1);
  assert.equal(status.textContent, 'Slide 2 of 3');
  advanceTime(4000);
  assert.equal(status.textContent, 'Slide 3 of 3');
  advanceTime(4000);
  assert.equal(status.textContent, 'Slide 1 of 3');
});

test("keyboard focus pauses the carousel and Play resumes while focused", () => {
  const { carousel, pause, status, advanceTime } = carouselFixture();
  carousel.matches = selector => selector === ':focus-visible';
  carousel.fire('focusin');
  advanceTime(8000);
  assert.equal(status.textContent, 'Slide 1 of 3');
  assert.equal(pause.textContent, 'Play');
  pause.fire('click');
  advanceTime(4000);
  assert.equal(status.textContent, 'Slide 2 of 3');
  pause.fire('click');
  advanceTime(8000);
  assert.equal(status.textContent, 'Slide 2 of 3');
});

test("a hidden page suspends rotation and reduced motion permits explicit Play", () => {
  const normal = carouselFixture();
  normal.document.hidden = true; normal.document.fire('visibilitychange');
  normal.advanceTime(8000);
  assert.equal(normal.status.textContent, 'Slide 1 of 3');
  normal.document.hidden = false; normal.document.fire('visibilitychange');
  normal.advanceTime(4000);
  assert.equal(normal.status.textContent, 'Slide 2 of 3');
  const reduced = carouselFixture(3, true);
  reduced.advanceTime(8000);
  assert.equal(reduced.status.textContent, 'Slide 1 of 3');
  reduced.pause.fire('click'); reduced.advanceTime(4000);
  assert.equal(reduced.status.textContent, 'Slide 2 of 3');
});

test("a horizontal swipe advances the carousel", () => {
  const { viewport, status } = carouselFixture();
  const start = new Event("touchstart");
  Object.defineProperty(start, "touches", { value: [{ clientX: 250, clientY: 100 }] });
  viewport.dispatchEvent(start);
  const end = new Event("touchend");
  Object.defineProperty(end, "changedTouches", { value: [{ clientX: 100, clientY: 105 }] });
  viewport.dispatchEvent(end);
  assert.equal(status.textContent, "Slide 2 of 3");
});

test("zero and single slide carousels are safe to initialise", () => {
  assert.doesNotThrow(() => carouselFixture(0));
  assert.doesNotThrow(() => carouselFixture(1));
});

function galleryFixture() {
  const document = new Element();
  const gallery = new Element();
  const state = new Element({ colour: 'ivory' });
  gallery.closest = () => state;
  const stage = new Element();
  const images = [0, 1, 2].map((index) => new Element({ photoIndex: String(index) }));
  images.forEach((image, index) => { image.hidden = index !== 0; image.src = `photo-${index}.webp`; image.alt = `Photo ${index}`; });
  const triggers = ['ivory', 'ivory', 'midnight'].map((colour, index) => {
    const trigger = new Element({ colour, photoIndex: String(index) });
    trigger.click = () => trigger.fire('click');
    return trigger;
  });
  const dialog = new Element();
  dialog.showModal = () => { dialog.open = true; };
  dialog.close = () => { dialog.open = false; };
  const zoom = new Element();
  const zoomImage = new Element();
  const close = new Element();
  document.children.set('[data-product-gallery]', [gallery]);
  gallery.children = new Map([
    ['[data-gallery-stage]', [stage]], ['[data-product-image]', images],
    ['[data-gallery-trigger]', triggers], ['[data-gallery-dialog]', [dialog]],
    ['[data-zoom-image]', [zoomImage]], ['[data-gallery-zoom]', [zoom]], ['[data-close-zoom]', [close]],
  ]);
  runScript('product-gallery.js', document);
  return { document, images, triggers, stage, dialog, zoom, zoomImage, close };
}

test('genuine same-colour photographs switch without changing the selected colour', () => {
  const { images, triggers } = galleryFixture();
  triggers[1].fire('click');
  assert.deepEqual(images.map((image) => image.hidden), [true, false, true]);
  assert.equal(triggers[1].getAttribute('aria-current'), 'true');
});

test('alternative-colour photographs leave selection to the atomic product navigator', () => {
  const { images, triggers } = galleryFixture();
  const click = new Event('click', { cancelable: true });
  triggers[2].dispatchEvent(click);
  assert.equal(click.defaultPrevented, false);
  assert.deepEqual(images.map((image) => image.hidden), [false, true, true]);
});

test('gallery swipes move between genuine photographs', () => {
  const { stage, images } = galleryFixture();
  const start = new Event('touchstart');
  Object.defineProperty(start, 'touches', { value: [{ clientX: 250, clientY: 100 }] });
  stage.dispatchEvent(start);
  const end = new Event('touchend');
  Object.defineProperty(end, 'changedTouches', { value: [{ clientX: 100, clientY: 105 }] });
  stage.dispatchEvent(end);
  assert.equal(images[1].hidden, false);
});

test('zoom uses the visible genuine image and closes', () => {
  const { triggers, zoom, zoomImage, dialog, close } = galleryFixture();
  triggers[1].fire('click');
  zoom.fire('click');
  assert.equal(dialog.open, true);
  assert.equal(zoomImage.src, 'photo-1.webp');
  close.fire('click');
  assert.equal(dialog.open, false);
});

test('reinitialising an existing gallery does not duplicate its handlers', () => {
  const { document, stage, images } = galleryFixture();
  document.fire('velmora:product-ready');
  const key = new Event('keydown', { cancelable: true });
  Object.defineProperty(key, 'key', { value: 'ArrowRight' });
  stage.dispatchEvent(key);
  assert.equal(images[1].hidden, false);
});
