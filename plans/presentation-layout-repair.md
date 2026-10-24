# Presentation layout repair

## Goal

Make the El72 presentation reliable at presentation-sized viewports by removing
overflow, correcting misplaced elements, wiring the slide engine to the actual
DOM, and ensuring local assets render consistently.

## Approach

1. Normalize slide count, section metadata, and navigation chrome.
2. Apply the existing specialized layout hooks to the relevant slides.
3. Establish safe sizing for dense content, diagrams, photos, and embedded frames.
4. Validate navigation, asset loading, and element bounds at 16:9 and short-height
   viewports.
5. Consolidate the four technical slides into two AI-focused slides without
   dropping the anomaly, scoring, fake-discount, or cross-store evidence.

## Files touched

- `presentation/index.html`
- `presentation/css/apple-theme.css`
- `presentation/js/deck.js`
- `presentation/js/motion.js`
- `presentation/README.md`

## Test strategy

- Open the deck from `file://` and through the local server.
- Exercise hash, keyboard, click-zone, and first/middle/last slide navigation.
- Check every slide for viewport overflow and footer collisions at 1920x1080,
  1280x720, and a short-height viewport.
- Verify every image has a non-zero rendered size and no console resource errors.
