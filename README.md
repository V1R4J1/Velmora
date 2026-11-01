# Velmora

A Flask and Jinja shopping catalogue for a fictional London evening-wear label. The existing editorial campaign carousel, 48 product pages, nine featured products, searchable wider collection and bundle routes are preserved. Product pages now have a balanced two-column layout, bounded portrait photography, genuine-photo thumbnails, accessible zoom, minimal colour swatches, product-specific sizing, a working bag and collapsed details. The compact wardrobe strip switches complete product views on the same page and retains colour/size state in URLs and browser history.

The shared bundle model supports explicit colourways for curated sets, customer drafts and future AI-generated proposals. The Winter Soirée Set is Isola dress in Champagne, Bianca silk scarf in Champagne and Celeste clutch in Emerald. Homepage previews, `/sets`, the wardrobe strip and the bag resolve their names, selected-colour images and current prices from the catalogue. Missing selected-colour photography is identified without fabricating images or silently changing colour.

The bag is functional and server-validated. Online checkout, payments, orders and real stock quantities are not connected. The studio can add an entire validated set to the bag. AI styling is disabled by default and can be enabled with a server-side Gemini key as described below. Provider-independent generation, validation, private draft storage and publication access hooks are implemented. [The bundle API documentation](docs/bundle-api.md) explains the contract, security boundaries and deployment requirements.

For a guided tour of the application modules, browser assets, catalogue data and tests, see the [code map](docs/code-map.md).

## Setup

Python 3.10 or newer is required. Flask and certifi are the runtime dependencies; SQLite, dataclasses and the regression tests use Python's standard library. No frontend package installation or build step is required.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m flask --app app run --port 5055
```

Open `http://127.0.0.1:5055/bundles/winter-soiree` to review the main set, or `/products/VLM-012` to inspect a product with photographs for both colourways. `python app.py` also starts the development server. Production WSGI tooling can import `app:app` or call `app.create_app()`. Set `VELMORA_SECRET_KEY` to a stable secret and enable secure cookies over HTTPS before deployment; development otherwise generates a new session key on each process start.

To use Gemini styling locally, stop any server already running on port 5055 and run `zsh scripts/start-gemini.zsh`. Enter the Gemini API key at the hidden prompt; it stays in the server process environment and is not saved in the project. Alternatively, supply `GEMINI_API_KEY`, `VELMORA_AI_ENABLED=1` and `VELMORA_AI_PROVIDER=gemini` in the server environment before starting Flask. Styling and semantic search both use the pinned `gemini-3.1-flash-lite` model. Styling requests, search text and relevant catalogue details are sent to Google; review [Google's Gemini API terms](https://ai.google.dev/gemini-api/terms) for the applicable data handling and pricing. A live request is required to verify the key and account access.

## Routes

`/` and `/index.html` show the editorial campaign and featured collection. `/products` contains the other 39 products with search, category, price and availability filters, while `/products/search` supplies live catalogue matches and spelling suggestions. When an unmatched broad search is submitted, the configured Gemini model can return related catalogue pieces with validated colourways; the result image and product link use that colour, while searches without a colour request use each product's default colourway. Every item has `/products/<product_id>`, with optional canonical `colour` and `size` query selections. `/product` preserves the original VLM-001 example and `/product.html` opens the Winter Soirée Set. Unknown pages and products retain the shared 404.

`/sets` displays six official curated looks and other approved curated sets. `/sets/create` opens the manual styling studio and the disabled AI brief interface. Saved private or published sets can also be viewed at `/sets/saved/<id>`, subject to the same ownership rules as the existing saved-bundle route. `/bundles/winter-soiree` displays the named set; `item` selects its one-based position. `colours` and `sizes` carry ordered slash-separated customer selections, with `-` for an unchosen size. `/bundle?items=VLM-003/VLM-047/VLM-048` preserves legacy ordered product-ID links, including repeated IDs, by explicitly resolving photographed catalogue defaults into the shared model. Legacy input limits remain 50 items and 2,048 characters; malformed references and positions return 400. New bundle creation APIs require actual colourway references for every item.

`/bag` displays the current visitor's selected pieces, colours, sizes, quantities, availability and current subtotal. Native purchase forms work without JavaScript; enhanced forms stay on the product page and update the bag count. `/api/bundles/generate` is unavailable until a tested provider is configured. `/api/bundles` validates and durably saves session-owned drafts; publishing requires an explicitly configured editor permission check. `/bundles/saved/<id>` uses exactly the same product components as a curated set.

Catalogue filters accept `q`, `category`, `availability`, `min_price` and `max_price`. Search remains case-insensitive across name, ID, category, fabric, fit, colours and occasions. Colour searches use that real colourway's photograph and direct link, or a placeholder if photography is missing. Availability filters are `in_stock`, `made_to_order` and `unavailable`. Inclusive GBP bounds accept finite, non-negative decimals. Invalid filters return 400 with actionable messages, while a valid empty result returns 200.

## Catalogue and colourways

`static/products.json` is the product source of truth. Records contain `id`, `name`, `category`, `price_gbp`, non-empty `colours`, `fabric`, optional `fit`, non-empty `sizes`, `occasions`, making lead time and availability flags, colour-neutral `description` and `images`. IDs must be unique; prices and lead times are non-negative whole numbers. Accessories use `["one size"]`. `in_stock` and `made_to_order` cannot both be true; when both are false the piece is unavailable. Made-to-order availability requires a positive making lead time.

Each declared colour resolves to a stable local colourway ID, for example `VLM-047--pewter`. Size remains separate. All existing single-colour products also have an explicit colourway. These IDs are not external commerce SKUs. Stock currently inherits product-level availability; an optional `variant_availability` mapping keyed by canonical colour ID can accurately override individual colourways. Size-level stock and external commerce mapping require real additional data.

`images` is one shared array of objects such as `{ "colour": "ivory", "image": "productImages/VLM-012/VLM-012-ivory.webp" }`. Each path is static-relative, stays inside `static/` and must exist. Multiple genuine photographs per colour are supported; duplicate paths and unknown colours are rejected. An empty array produces a placeholder. Product and bundle previews never substitute a different colour's photograph. The main gallery may show the first genuine image when selected-colour photography is absent, with an explicit note naming its actual colour.

All 48 current records contain colour data, resolving to 90 declared colourways. Six colourways use AI-generated illustrations based on the existing product photographs: VLM-003 Emerald, VLM-005 Emerald, VLM-006 Midnight, VLM-007 Emerald, VLM-008 Ivory and VLM-010 Midnight. The existing catalogue name “Bianca silk scarf” and its recorded fabric “duchess satin” are retained as supplied and need merchandising confirmation before a production launch. The app does not infer a fibre composition from a product name or a photograph.

`static/product_line.json` retains the ordered nine featured IDs. The app loads and validates JSON once at startup, rejecting broken catalogue references, colour data and local assets with descriptive errors. Restart the server after changing JSON or image files. An empty featured list remains supported. `static/brand.md` describes the original brand conventions; `static/analytics.csv` remains a fictional historical dataset, not live tracking.

## Implementation

`app.py` retains the application factory, catalogue pages and legacy routes. `catalogue.py` owns immutable products, real colourways, image validation and filtering. `bundles.py` owns the sole bundle model, strict input validation, catalogue resolution, legacy-link adaptation and per-visitor URL customisation. `shopping.py` contains the validated bag, mutation protections and API routes. `bundle_store.py` stores reference-only drafts in SQLite. `styling.py` separates request interpretation, eligible catalogue retrieval, provider suggestions and authoritative backend validation.

`templates/_product_view.html` is the shared atomic product component for initial HTML and asynchronous switching. `static/product-page.js` coordinates history, cancellation, selection state and bag submission. `static/product-gallery.js` handles genuine-photo navigation, swipes, keyboard navigation and zoom. The styling studio uses `static/builder.js` and the shared bundle model; its AI request controls remain disabled until a provider is configured. All pages retain Cormorant Garamond and Inter with non-blocking optional font loading and system fallbacks, warm ivory backgrounds, restrained borders and charcoal purchase controls. Motion respects reduced-motion preferences.

## Verification

```sh
python -B -m unittest discover -s tests -v
python -m pip check
node --test tests/*.test.mjs
node --check static/carousel.js
node --check static/catalogue-search.js
node --check static/product-gallery.js
node --check static/product-page.js
node --check static/bundle-service.js
```

The Python suite covers all 48 detail pages and assets, featured/wider collection membership, filters, legacy routes, colour and size references, selected-colour imagery, full product-view responses, unavailable and retired selections, current totals, bag purchases/removal, private draft ownership, publication controls, CSRF, request limits and provider failures. JavaScript tests exercise the actual carousel, gallery and product-page scripts, including swipes, zoom, stale-request cancellation, browser history, selection propagation and server-confirmed bag updates. Browser QA covers desktop and narrow mobile views, bundle switching, colour customisation, size selection, bag contents and history navigation. Provider integration and checkout verification remain pending because neither external service is configured.


Use the **Black Friday demo** on/off switch directly below the navigation on any page. It applies to your visitor session, works on mobile and refreshes studio/search prices in place without discarding the current look. Demo preview prices remain excluded from the bag and checkout. Black Friday demo awareness is off by default. Set `VELMORA_BLACK_FRIDAY_ENABLED=1` before starting the server to enable it, or update the running app's server-side `BLACK_FRIDAY_ENABLED` configuration. `VELMORA_PROMOTION_RANKING_WEIGHT` (app config `PROMOTION_RANKING_WEIGHT`, default `0.35`, capped at `0.5`) tunes `promotionRankingWeight`; zero disables the ranking bonus while active prices still apply to preview budgets. The single shared campaign definition is `data/black-friday-demo.json`, loaded through `PROMOTION_CAMPAIGN_PATH`. Its product/variant references are resolved against the catalogue by `pricing.py`; there is no AI-specific sale list. Optional timezone-aware `starts_at` and `ends_at` values bound campaign activity.

Styling and search retrieve bounded real candidates and treat relevance as primary. Active discounts break relevance ties; sale-only and exclude-sale requests constrain actual variants. Explicit natural-language budgets and structured constraints are checked again after provider generation. The provider receives current original/promotional prices and demo metadata, but may return only references and styling copy. A generated set can mix discounted and ordinary pieces. The lookboard resolves totals through `POST /api/bundles/resolve`, refreshes while visible and on focus, and shows discreet demo savings. Saved sets keep reference-only selections plus a separate historical total for price-change notices; they always recalculate current prices, including when a campaign ends.

All campaign prices in this implementation are demo previews. The bag and `purpose="checkout"` pricing resolution always use ordinary catalogue prices. No setting can turn these preview rules into genuine checkout offers; real promotions require a commerce adapter. Existing checkout remains unavailable. Promotion regression coverage is in `tests/test_promotions.py`; provider tests use controlled fixtures rather than a live AI account.

The home carousel advances every four seconds, including while the pointer rests over the hero. Keyboard focus, the Pause control and a hidden browser tab suspend rotation. Reduced-motion preferences disable automatic playback initially; Play allows an explicit opt-in.
