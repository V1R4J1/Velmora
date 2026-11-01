# Velmora (fictional client)

Velmora is a fictional brand created for this assessment. Every product, number and person in the assessment materials is invented. This document records the brand context and design conventions; `products.json` supplies the actual products, prices, colours, sizing, imagery and availability used by the demo.

## The brand and demo

Velmora is a London evening-wear label, launched in October 2025. The current demo has 48 pieces across dresses, jumpsuits, tops, skirts, outerwear and accessories. Most pieces are made to order in the London studio in 14 to 21 days. Some garments and both accessories are in stock. Garment sizes run from UK 6 to UK 18; accessories are one size. The nine featured product cards are controlled by `product_line.json`; the home page carousel follows every category in the catalogue.

The original business scenario describes a Shopify store selling to the UK and EU. This repository is a standalone Flask browsing demo and has no connection to Shopify, checkout or live orders. The scenario assumes a typical order of about £335 and a gross margin of about 55%; these are fictional planning assumptions, not calculations performed by the app.

The displayed delivery policy is 3 to 5 days for the UK or 5 to 8 days for the EU after making, or after dispatch for stocked pieces. Returns are within 14 days, unworn and with tags attached. Made-to-order pieces in a non-standard size cannot be returned. These policies are fictional demo copy.

## Assessment background

The original brief describes 760 Instagram followers, 41 posts and no customer reviews. Most visitors arrive from Instagram on a phone. `analytics.csv` contains six months of fictional data from April through September 2026, by channel and device, including a paid social test in August and September. It is reference material only; the app does not collect or process analytics.

The studio's assumed capacity is 20 made-to-order pieces a week. In the original assessment scenario, Black Friday was six weeks away. The founder wanted more website sales and better visibility when someone asked an AI assistant for an evening dress for a winter wedding. These are background goals, not capabilities implemented by this demo.

## Audience and voice

The audience is women aged 28 to 45 in the UK and Europe, buying for a particular occasion such as a winter wedding, black-tie dinner or New Year's Eve. Fit, fabric and time to delivery help them decide whether a piece suits their occasion.

Write in a calm, precise, warm voice, using short sentences. State fabric, fit and making and delivery times plainly. Avoid “luxury”, “stunning”, “must-have”, exclamation marks, invented reviews and invented scarcity.

## Design and imagery

The shared palette is ink `#1E1B1A`, ivory `#F6F1EA`, stone `#CFC6BA` and oxblood `#6B1F2A`, with complementary muted and panel colours. Use Cormorant Garamond for headings and Inter for text. `styles.css` owns these tokens for every page; page-specific styles inherit them.

The demo includes local WebP product images in `productImages/<product ID>/`. Each product's ordered `images` array associates these files with colours; the first image is the default. The home carousel uses actual product and colour images from these files to preview each category. Some products have imagery for only one of their available colours. Show an explicit note when the selected colour has no matching image, and use a plain placeholder for products without imagery. Do not introduce real brands' images or logos. Any additional stock photography should have an appropriate credit.
