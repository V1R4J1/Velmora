(() => {
  const form = document.querySelector("[data-live-search]");
  if (!form) return;

  const input = form.querySelector("[data-search-input]");
  const clearButton = form.querySelector("[data-clear-search]");
  const suggestions = form.querySelector("[data-search-suggestions]");
  const filterToggle = form.querySelector("[data-filters-toggle]");
  const filterPanel = form.querySelector("[data-filter-panel]");
  const filterActiveMark = form.querySelector("[data-filter-active]");
  const resultGrid = document.querySelector("[data-product-results]");
  const resultCount = document.querySelector("[data-product-count]");
  const searchStatus = document.querySelector("[data-search-status]");
  const searchFeedback = document.querySelector("[data-search-feedback]");
  const toolbarRetryButton = document.querySelector("[data-search-retry]");
  const interpretation = document.querySelector("[data-search-interpretation]");
  const emptyState = document.querySelector("[data-empty-state]");
  const skeletons = document.querySelector("[data-search-skeleton]");
  const emptyHeading = emptyState?.querySelector("[data-empty-heading]");
  const emptyCopy = emptyState?.querySelector("[data-empty-copy]");
  const emptyAlternatives = emptyState?.querySelector("[data-empty-alternatives]");
  const retryButton = emptyState?.querySelector("[data-empty-retry]");
  const debounceDelay = 300;
  let debounceTimer;
  let activeRequest;
  let activeRequestKey = "";
  let requestVersion = 0;
  let activeOption = -1;
  let searchState = "idle";
  let localResults = [];
  let completedResults = [];
  let activeSuggestionQuery = "";

  const colourSuggestions = [
    ["white", ["ivory", "champagne"]], ["cream", ["champagne", "ivory"]],
    ["off white", ["ivory", "champagne"]], ["off-white", ["ivory", "champagne"]],
    ["burgundy", ["oxblood"]], ["maroon", ["oxblood"]], ["navy", ["midnight"]],
    ["blue", ["sapphire", "midnight"]], ["green", ["emerald"]], ["pink", ["dusty rose"]],
    ["silver", ["pewter"]], ["grey", ["pewter"]], ["gray", ["pewter"]],
  ];
  const swatchColours = {
    black: "#292421", champagne: "#d9bd94", "dusty rose": "#c99198", emerald: "#2e6950",
    ivory: "#eee9de", midnight: "#29324d", oxblood: "#692d3a", pewter: "#94969a", sapphire: "#365483",
  };
  const escapeHTML = (value) => String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[character]);
  const titleCase = (value) => String(value ?? "").replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());

  function readParams() {
    const params = new URLSearchParams();
    new FormData(form).forEach((value, key) => {
      const text = String(value).trim();
      if (text) params.set(key, text);
    });
    return params;
  }

  function syncAddressBar(params) {
    const url = new URL(form.action, window.location.href);
    url.search = params.toString();
    const activeFilter = ["category", "colour", "fabric", "min_price", "max_price", "availability"]
      .some((key) => params.has(key));
    filterActiveMark.hidden = !activeFilter;
    window.history.replaceState(null, "", `${url.pathname}${url.search}`);
  }

  function setSuggestionsOpen(open) {
    const shouldOpen = Boolean(open && input.value.trim());
    suggestions.hidden = !shouldOpen;
    input.setAttribute("aria-expanded", String(shouldOpen));
    if (!shouldOpen) {
      activeOption = -1;
      input.removeAttribute("aria-activedescendant");
      suggestions.querySelectorAll('[role="option"]').forEach((option) => option.setAttribute("aria-selected", "false"));
    }
  }

  function optionButtons() {
    return [...suggestions.querySelectorAll('[role="option"]:not([aria-disabled="true"])')];
  }

  function setActiveOption(nextIndex) {
    const options = optionButtons();
    if (!options.length) return;
    activeOption = (nextIndex + options.length) % options.length;
    options.forEach((option, index) => option.setAttribute("aria-selected", String(index === activeOption)));
    input.setAttribute("aria-activedescendant", options[activeOption].id);
    options[activeOption].scrollIntoView?.({ block: "nearest" });
  }

  function addQueryOption(label, query, index) {
    const option = document.createElement("button");
    option.type = "button";
    option.className = "query-suggestion-option";
    option.id = `search-option-${index}`;
    option.setAttribute("role", "option");
    option.setAttribute("aria-selected", "false");
    option.tabIndex = -1;
    option.dataset.searchQuery = query;
    option.textContent = label;
    suggestions.append(option);
  }

  function buildProductSuggestion(product, index) {
    const option = document.createElement("button");
    option.type = "button";
    option.className = "search-suggestion-option";
    option.id = `search-option-${index}`;
    option.setAttribute("role", "option");
    option.setAttribute("aria-selected", "false");
    option.tabIndex = -1;
    option.dataset.productUrl = product.url;

    if (product.image) {
      const image = document.createElement("img");
      image.className = "suggestion-image";
      image.src = product.image;
      responsiveImage(image, product.image);
      image.alt = "";
      image.loading = "lazy";
      option.append(image);
    } else {
      const placeholder = document.createElement("span");
      placeholder.className = "suggestion-image-placeholder";
      placeholder.setAttribute("aria-hidden", "true");
      placeholder.textContent = "V";
      option.append(placeholder);
    }

    const copy = document.createElement("span");
    copy.className = "suggestion-copy";
    const name = document.createElement("strong");
    name.textContent = product.name;
    const detail = document.createElement("span");
    detail.textContent = `${product.colour_label} · ${titleCase(product.fabric)}`;
    copy.append(name, detail);

    const price = document.createElement("span");
    price.className = "suggestion-price";
    price.textContent = `£${product.price}`;
    if (product.promotion_active) {
      const original = document.createElement('del'); original.textContent = `£${product.original_price_gbp} `;
      const note = document.createElement('small'); note.textContent = `${product.discount_percentage}% less · Demo preview`;
      price.classList.add('promotion-price'); price.prepend(original); price.append(note);
    }
    option.append(copy, price);
    return option;
  }

  function responsiveImage(image, url) {
    if (!url?.startsWith('/static/productImages/')) { image.removeAttribute('srcset'); return; }
    image.srcset = [320, 640, 960].map(width => `${url.replace('/static/', '/static/responsive/')}.${width}.webp ${width}w`).join(', ');
    image.sizes = '(max-width: 700px) 46vw, 25vw';
  }

  function showProductImage(container, product, variant) {
    container.replaceChildren();
    if (!variant.image) {
      const placeholder = document.createElement("span");
      placeholder.className = "search-product-placeholder";
      placeholder.textContent = "Photography coming soon";
      container.append(placeholder);
      return;
    }
    const image = document.createElement("img");
    image.className = "search-product-image";
    image.src = variant.image;
    responsiveImage(image, variant.image);
    image.alt = `${product.name} in ${variant.colour_label}`;
    image.loading = "lazy";
    image.width = 800;
    image.height = 1000;
    container.append(image);
  }

  function renderSuggestions(products, query, { correction = null, pending = false, show = true } = {}) {
    suggestions.replaceChildren();
    if (!query) { setSuggestionsOpen(false); return; }

    let index = 0;
    if (correction) addQueryOption(`Did you mean “${correction}”?`, correction, index++);

    const normalized = query.toLocaleLowerCase();
    const matchedColours = colourSuggestions.find(([phrase]) =>
      phrase.includes(" ") ? normalized.includes(phrase) : new RegExp(`(^|\\W)${phrase}(\\W|$)`, "i").test(normalized));
    if (matchedColours) {
      matchedColours[1].forEach((colour) => addQueryOption(`${titleCase(colour)} pieces`, colour, index++));
    }

    products.slice(0, 5).forEach((product) => suggestions.append(buildProductSuggestion(product, index++)));
    if (pending) {
      const status = document.createElement("div");
      status.className = "suggestions-status";
      status.setAttribute("role", "option");
      status.setAttribute("aria-disabled", "true");
      status.setAttribute("aria-selected", "false");
      status.textContent = "Finding more relevant pieces…";
      suggestions.append(status);
    } else if (!index) {
      const noOptions = document.createElement("div");
      noOptions.className = "suggestions-empty";
      noOptions.setAttribute("role", "presentation");
      noOptions.textContent = "No matching suggestions.";
      suggestions.append(noOptions);
    }
    setSuggestionsOpen(show);
  }

  function renderProduct(product) {
    const article = document.createElement("article");
    article.className = "search-product";
    article.dataset.productId = product.id;

    const imageLink = document.createElement("a");
    imageLink.className = "search-product-art";
    imageLink.href = product.url;
    imageLink.setAttribute("aria-label", `${product.name} in ${product.colour_label}`);
    showProductImage(imageLink, product, product);

    const meta = document.createElement("div");
    meta.className = "search-product-meta";
    const title = document.createElement("a");
    title.className = "search-product-name";
    title.href = product.url;
    title.textContent = product.name;
    const price = document.createElement("span");
    price.className = "search-product-price";
    price.textContent = `£${product.price}`;
    if (product.promotion_active) {
      const original = document.createElement('del'); original.textContent = `£${product.original_price_gbp} `;
      const note = document.createElement('small'); note.textContent = `${product.discount_percentage}% less · Demo preview`;
      price.classList.add('promotion-price'); price.prepend(original); price.append(note);
    }
    const detail = document.createElement("p");
    detail.className = "search-product-detail";
    detail.textContent = `${product.colour_label} · ${titleCase(product.fabric)}${product.availability === "unavailable" ? " · Currently unavailable" : ""}`;
    const headingRow = document.createElement("div");
    headingRow.className = "search-product-heading";
    headingRow.append(title, price);
    meta.append(headingRow, detail);

    const variants = document.createElement("div");
    variants.className = "search-product-swatches";
    variants.setAttribute("role", "group");
    variants.setAttribute("aria-label", `Available colours for ${product.name}`);
    for (const variant of product.variants || []) {
      const swatch = document.createElement("button");
      swatch.type = "button";
      swatch.className = "variant-swatch";
      swatch.dataset.variantId = variant.id;
      swatch.dataset.colourId = variant.colour_id;
      swatch.dataset.colourLabel = variant.colour_label;
      swatch.dataset.image = variant.image || "";
      swatch.dataset.url = variant.url;
      swatch.dataset.availability = variant.availability;
      swatch.setAttribute("aria-label", `${variant.colour_label}${variant.availability === "unavailable" ? " — unavailable" : ""}`);
      swatch.setAttribute("aria-pressed", String(variant.variant_id === product.variant_id || variant.id === product.variant_id));
      swatch.title = variant.colour_label;
      swatch.disabled = variant.availability === "unavailable";
      swatch.style.setProperty("--swatch-colour", swatchColours[variant.colour_label.toLocaleLowerCase()] || "#d5cec5");
      variants.append(swatch);
    }
    if (variants.childElementCount > 1) meta.append(variants);
    article.append(imageLink, meta);
    return article;
  }

  function renderGrid(products) {
    resultGrid.replaceChildren(...products.map(renderProduct));
    if (skeletons) skeletons.hidden = true;
    resultGrid.classList.remove("is-updating");
    resultGrid.setAttribute("aria-busy", "false");
    emptyState.hidden = products.length > 0;
  }

  function showSkeletons() {
    if (!resultGrid.childElementCount && skeletons) skeletons.hidden = false;
  }

  function setState(next, message = "") {
    searchState = next;
    form.dataset.searchState = next;
    searchStatus.textContent = message;
    searchFeedback.classList.toggle("is-active", Boolean(message));
    const isPending = ["typing", "catalogue-searching", "ai-searching"].includes(next);
    resultGrid.setAttribute("aria-busy", String(isPending));
    resultGrid.classList.toggle("is-updating", isPending && resultGrid.childElementCount > 0);
    if (retryButton) retryButton.hidden = next !== "failed" || resultGrid.childElementCount > 0;
    if (toolbarRetryButton) toolbarRetryButton.hidden = next !== "failed" || !resultGrid.childElementCount;
  }

  function setCount(count, pending = false) {
    resultCount.textContent = pending ? "Updating matches" : `${count} ${count === 1 ? "piece" : "pieces"}`;
  }

  function updateInterpretation(text) {
    interpretation.textContent = text || "";
    interpretation.hidden = !text;
  }

  function showNoResults({ failure = false, suggestion = null, constraint = null } = {}) {
    emptyState.hidden = false;
    if (failure) {
      emptyHeading.textContent = "We couldn’t complete that search.";
      emptyCopy.textContent = "Try again, use a product name or explore the collection.";
      retryButton.hidden = false;
    } else {
      emptyHeading.textContent = "We couldn’t find quite the right piece.";
      emptyCopy.textContent = "Try another description, explore a different shade or browse the collection.";
      retryButton.hidden = true;
    }
    if (constraint && !failure) emptyCopy.textContent = constraint;
    emptyAlternatives.replaceChildren();
    if (suggestion) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "empty-suggestion";
      button.dataset.searchQuery = suggestion;
      button.textContent = `Search for “${suggestion}”`;
      emptyAlternatives.append(button);
      emptyCopy.textContent = `Try “${suggestion}” instead, or explore a different shade.`;
    }
  }

  function syncControls(query) {
    clearButton.hidden = !query;
    filterToggle.setAttribute("aria-expanded", String(!filterPanel.hidden));
  }

  function syncAddressBar(params) {
    const url = new URL(form.action, window.location.href);
    url.search = params.toString();
    filterActiveMark.hidden = !["category", "colour", "fabric", "min_price", "max_price", "availability"].some((key) => params.has(key));
    window.history.replaceState(null, "", `${url.pathname}${url.search}`);
  }

  async function responseJSON(response) {
    let data;
    try { data = await response.json(); } catch { throw new Error("Search response could not be read."); }
    return { data, response };
  }

  function mergeResults(aiResults, lexicalResults) {
    const result = new Map();
    [...aiResults, ...lexicalResults].forEach((product) => {
      if (!result.has(product.id)) result.set(product.id, product);
    });
    return [...result.values()];
  }

  async function runSearch({ showSuggestions = true, initial = false } = {}) {
    clearTimeout(debounceTimer);
    const query = input.value.trim();
    const params = readParams();
    const key = params.toString();
    if (activeRequest && activeRequestKey === key && ["catalogue-searching", "ai-searching"].includes(searchState)) return;
    activeRequest?.abort();
    const controller = new AbortController();
    activeRequest = controller;
    activeRequestKey = key;
    const version = ++requestVersion;
    const isCurrent = () => version === requestVersion && !controller.signal.aborted;
    syncControls(query);
    syncAddressBar(params);
    updateInterpretation("");
    if (!initial) {
      setCount(0, true);
      setState("catalogue-searching", "Searching the collection…");
      showSkeletons();
    }

    try {
      const localResponse = await fetch(`/products/search?${key}`, {
        headers: { Accept: "application/json" }, signal: controller.signal,
      });
      const { data: localData, response } = await responseJSON(localResponse);
      if (!isCurrent()) return;
      if (!response.ok) {
        if (localData.errors) { showFilterErrors(localData.errors); return; }
        throw new Error("Search could not be completed.");
      }

      clearFilterErrors();
      localResults = localData.products || [];
      completedResults = localResults;
      emptyState.hidden = true;
      if (localResults.length) renderGrid(localResults);
      else if (localData.needs_semantic) showSkeletons();
      else renderGrid([]);
      renderSuggestions(localResults, query, {
        correction: localData.suggestion,
        pending: Boolean(localData.needs_semantic),
        show: showSuggestions,
      });

      if (localData.needs_semantic && localData.ai_available) {
        setCount(0, true);
        setState("ai-searching", "Finding pieces for you…");
        if (localResults.length) renderGrid(localResults);
        else showSkeletons();

        let related;
        {
          let timedOut = false;
          const timeout = setTimeout(() => { timedOut = true; controller.abort(); }, 15_000);
          try {
            const body = Object.fromEntries(params);
            const { data, response } = await responseJSON(await fetch("/api/search/semantic", {
              method: "POST",
              headers: { "Content-Type": "application/json", Accept: "application/json", "X-CSRF-Token": form.dataset.csrf },
              body: JSON.stringify(body), signal: controller.signal,
            }));
            clearTimeout(timeout);
            if (version !== requestVersion || (controller.signal.aborted && !timedOut)) return;
            if (!response.ok) throw new Error(data.code || "semantic_unavailable");
            related = data;

          } catch (error) {
            clearTimeout(timeout);
            if (version !== requestVersion || (controller.signal.aborted && !timedOut)) return;
            if (localResults.length) {
              renderGrid(localResults);
              setCount(localResults.length);
              setState("failed", "Showing catalogue matches; broader search couldn’t complete.");
              updateInterpretation(localData.interpretation);
              renderSuggestions(localResults, query, { correction: localData.suggestion, show: showSuggestions });
            } else {
              setCount(0);
              setState("failed", "Broader search couldn’t complete.");
              showNoResults({ failure: true });
              renderSuggestions([], query, { show: showSuggestions });
            }
            return;
          }
        }
        if (!isCurrent()) return;
        if (related.pricing_revision && related.pricing_revision !== localData.pricing_revision) {
          const refreshed = await fetch(`/products/search?${key}`, { headers: { Accept: "application/json" }, signal: controller.signal });
          if (!refreshed.ok) throw new Error("Current search prices could not refresh.");
          const fresh = await refreshed.json();
          if (!isCurrent()) return;
          localResults = fresh.products || [];
          // A second campaign change cannot reintroduce older semantic prices.
          if (fresh.pricing_revision !== related.pricing_revision) related.products = [];
        }
        const finalResults = mergeResults(related.products || [], localResults);
        completedResults = finalResults;
        renderGrid(finalResults);
        setCount(finalResults.length);
        setState("results");
        updateInterpretation(related.interpretation || localData.interpretation);
        renderSuggestions(finalResults, query, { correction: localData.suggestion, show: showSuggestions });
        if (!finalResults.length) {
          setState("no-results");
          showNoResults({ constraint: related.promotion_constraint || localData.promotion_constraint });
        }
        return;
      }

      completedResults = localResults;
      setCount(localResults.length);
      setState("results");
      updateInterpretation(localData.interpretation);
      if (!localResults.length) {
        setState("no-results");
        showNoResults({ suggestion: localData.suggestion, constraint: localData.promotion_constraint });
      }
    } catch (error) {
      if (error.name === "AbortError" || version !== requestVersion) return;
      setState("failed", "Search couldn’t refresh. Your previous results are still shown.");
      if (resultGrid.childElementCount) setCount(resultGrid.childElementCount);
      if (!resultGrid.childElementCount) showNoResults({ failure: true });
      renderSuggestions(localResults, query, { show: showSuggestions });
    }
  }

  function scheduleSearch({ showSuggestions = true, immediate = false } = {}) {
    clearTimeout(debounceTimer);
    activeRequest?.abort();
    activeRequest = null;
    activeRequestKey = "";
    syncControls(input.value.trim());
    emptyState.hidden = true;
    if (!input.value.trim()) setSuggestionsOpen(false);
    setCount(0, true);
    setState("typing", input.value.trim() ? "Searching the collection…" : "Refreshing pieces…");
    const run = () => runSearch({ showSuggestions });
    if (immediate) run();
    else debounceTimer = setTimeout(run, debounceDelay);
  }

  function showFilterErrors(errors) {
    let summary = document.querySelector("[data-filter-error-summary]");
    if (!summary) {
      summary = document.createElement("div");
      summary.className = "filter-errors";
      summary.setAttribute("role", "alert");
      summary.dataset.filterErrorSummary = "";
      form.insertAdjacentElement("afterend", summary);
    }
    summary.textContent = "Please adjust the highlighted filters to see matching pieces.";
    Object.entries(errors).forEach(([key, message]) => {
      const control = form.querySelector(`#${key}`);
      const field = control?.closest(".filter-field");
      if (!control || !field) return;
      const errorId = `${key}-error`;
      let error = field.querySelector(`#${errorId}`);
      if (!error) {
        error = document.createElement("p");
        error.className = "filter-error";
        error.id = errorId;
        error.dataset.filterError = "";
        control.parentElement.insertAdjacentElement("afterend", error);
      }
      error.textContent = message;
      control.setAttribute("aria-invalid", "true");
      control.setAttribute("aria-describedby", errorId);
    });
    resultGrid.replaceChildren();
    setCount(0);
    setState("results");
    showNoResults({ failure: true });
    setSuggestionsOpen(false);
  }

  function clearFilterErrors() {
    form.querySelectorAll("[aria-invalid='true']").forEach((control) => {
      control.removeAttribute("aria-invalid");
      control.removeAttribute("aria-describedby");
    });
    form.querySelectorAll("[data-filter-error]").forEach((error) => error.remove());
    document.querySelector("[data-filter-error-summary]")?.remove();
  }

  function submitQuery(query, { showSuggestions = true } = {}) {
    input.value = query;
    clearButton.hidden = !query;
    input.focus();
    scheduleSearch({ showSuggestions, immediate: true });
  }

  form.addEventListener("input", (event) => {
    if (event.target === input) {
      setSuggestionsOpen(Boolean(input.value.trim()));
      scheduleSearch();
      return;
    }
    if (event.target.matches("input, select")) scheduleSearch();
  });

  form.addEventListener("change", (event) => {
    if (event.target.matches("select, input[type='number']")) scheduleSearch();
  });

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const active = optionButtons()[activeOption];
    if (active?.dataset.productUrl) { window.location.assign(active.dataset.productUrl); return; }
    if (active?.dataset.searchQuery) { submitQuery(active.dataset.searchQuery); return; }
    scheduleSearch({ immediate: true, showSuggestions: true });
  });

  input.addEventListener("focus", () => {
    if (input.value.trim() && !suggestions.hidden) setSuggestionsOpen(true);
  });

  input.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      event.preventDefault();
      setSuggestionsOpen(false);
      return;
    }
    if (event.key === "ArrowDown" && !suggestions.hidden) {
      event.preventDefault();
      setActiveOption(activeOption + 1);
    } else if (event.key === "ArrowUp" && !suggestions.hidden) {
      event.preventDefault();
      setActiveOption(activeOption <= 0 ? optionButtons().length - 1 : activeOption - 1);
    }
  });

  clearButton.addEventListener("click", () => {
    input.value = "";
    input.focus();
    scheduleSearch({ immediate: true, showSuggestions: false });
  });

  filterToggle.addEventListener("click", () => {
    const expanded = filterToggle.getAttribute("aria-expanded") === "true";
    filterPanel.hidden = expanded;
    filterToggle.setAttribute("aria-expanded", String(!expanded));
  });

  form.querySelectorAll("[data-search-term]").forEach((link) => {
    link.addEventListener("click", (event) => {
      event.preventDefault();
      submitQuery(link.textContent.trim());
    });
  });

  form.querySelector("[data-clear-filters]")?.addEventListener("click", () => {
    form.querySelectorAll("select").forEach((control) => { control.value = ""; });
    form.querySelectorAll("input[type='number']").forEach((control) => { control.value = ""; });
    input.value = "";
    clearButton.hidden = true;
    scheduleSearch({ immediate: true, showSuggestions: false });
  });

  document.querySelector("[data-empty-clear]")?.addEventListener("click", () => {
    input.value = "";
    clearButton.hidden = true;
    scheduleSearch({ immediate: true, showSuggestions: false });
  });
  retryButton?.addEventListener("click", () => scheduleSearch({ immediate: true }));
  toolbarRetryButton?.addEventListener("click", () => scheduleSearch({ immediate: true }));

  document.querySelector("[data-empty-alternatives]")?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-search-query]");
    if (button) submitQuery(button.dataset.searchQuery);
  });

  suggestions.addEventListener("click", (event) => {
    const option = event.target.closest('[role="option"]');
    if (!option) return;
    if (option.dataset.productUrl) { window.location.assign(option.dataset.productUrl); return; }
    if (option.dataset.searchQuery) submitQuery(option.dataset.searchQuery);
  });

  resultGrid.addEventListener("click", (event) => {
    const swatch = event.target.closest("[data-variant-id]");
    if (!swatch) return;
    event.preventDefault();
    const card = swatch.closest("[data-product-id]");
    const imageLink = card.querySelector(".search-product-art");
    const titleLink = card.querySelector(".search-product-name");
    const detail = card.querySelector(".search-product-detail");
    const product = completedResults.find((item) => item.id === card.dataset.productId);
    const variant = product?.variants?.find((item) => item.id === swatch.dataset.variantId);
    if (!variant) return;
    card.querySelectorAll("[data-variant-id]").forEach((button) => button.setAttribute("aria-pressed", String(button === swatch)));
    showProductImage(imageLink, product, variant);
    imageLink.href = variant.url;
    imageLink.setAttribute("aria-label", `${product.name} in ${variant.colour_label}`);
    titleLink.href = variant.url;
    detail.textContent = `${variant.colour_label} · ${titleCase(product.fabric)}${variant.availability === "unavailable" ? " · Currently unavailable" : ""}`;
  });

  document.addEventListener("click", (event) => {
    if (!event.target.closest(".search-field-shell")) setSuggestionsOpen(false);
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !suggestions.hidden) setSuggestionsOpen(false);
  });

  document.addEventListener("velmora:campaign-change", (event) => {
    event.preventDefault();
    runSearch({ showSuggestions: false });
  });

  const query = input.value.trim();
  const hasFilters = [...filterPanel.querySelectorAll("select, input")].some((control) => control.value.trim());
  if (query || hasFilters) runSearch({ showSuggestions: false, initial: true });
  else runSearch({ showSuggestions: false, initial: true });
})();
