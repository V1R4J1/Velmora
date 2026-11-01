# Code map

This guide explains where each part of Velmora lives and how requests move through the application. It documents the current source without changing application or test code.

## Application and catalogue

`app.py` creates the Flask application, loads the catalogue, configures sessions and provider settings, and registers the storefront routes. It is the entry point used by the Flask command in the README.

`catalogue.py` defines products, colour variants, images, catalogue loading and validation, and server-side filters. `static/products.json` is the catalogue source of truth; product photographs are stored under `static/productImages/`.

`catalogue_search.py` normalises and ranks catalogue queries, handles conversational words and maintained colour/category synonyms, selects the matching real variant, and decides when broad searches can benefit from semantic matching. `shopping.py` owns the semantic search API and checks provider product and variant references against the loaded catalogue before returning them.

## Sets, styling and shopping

`bundles.py` defines the shared set and item model, validates submitted references and selections, resolves current catalogue prices and images, and adapts older set URLs. `styling.py` interprets a styling request, chooses eligible catalogue items, invokes the configured provider and validates the resulting proposal.

`styling_provider.py` contains the server-side Gemini and OpenAI adapters. Provider credentials are read from server configuration and are never sent to browser code. `bundle_store.py` persists private saved sets by product and variant references.

`shopping.py` also provides bag operations, session and CSRF protections, request limiting, set persistence APIs, and the routes that connect the browser to styling and catalogue data.

## Templates and browser assets

`templates/base.html` provides the shared page shell. `templates/macros.html` contains reusable product markup. The page templates in `templates/` assemble the home page, product pages, catalogue search, set builder, saved sets, bag and error messages.

`static/styles.css` contains the shared visual foundation. Page-specific styles live in `static/product.css`, `static/catalogue.css`, `static/builder.css` and `static/sets.css`. The JavaScript files follow the same areas: `catalogue-search.js` handles live search and filters; `builder.js` and `builder-state.js` manage the styling studio; `bundle-service.js` defines its API boundary; and `product-page.js` with `product-gallery.js` manage product selection, history and photography. `carousel.js` controls the homepage campaign carousel.

`static/product_line.json` lists the featured products. `static/campaign/` contains campaign artwork, while `static/productImages/` contains catalogue photography. `static/brand.md` records the brand conventions. `static/analytics.csv` is fictional historical data, not live customer analytics.

## Tests and local setup

Python tests under `tests/test_*.py` cover Flask routes, catalogue matching, set validation, provider behaviour and shopping APIs. JavaScript tests in `tests/*.test.mjs` exercise the browser state and interaction code. Fixture payloads live in `tests/fixtures/`.

`scripts/start-gemini.zsh` prompts for a Gemini key without echoing or saving it, enables the provider for that server process, and starts the local app. `.gitignore` excludes local virtual environments, secrets, caches and machine-specific files. Keep API keys, local databases and generated Python bytecode out of Git commits.
