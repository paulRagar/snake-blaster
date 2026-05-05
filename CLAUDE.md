# Snake Blaster — Project Context

## Project Overview

A MicroPython hobby project running on a Raspberry Pi Pico.
It is a physical LED game device with arcade buttons, a NeoPixel LED strip,
and a passive buzzer. There are two programs in this project:

- `rgb_cascade.py` — a sandbox/toy where button presses animate colored pixels
  onto the LED strip with a queue system
- `main.py` — the main game (Snake Blaster), described below

## Hardware

- Raspberry Pi Pico (MicroPython)
- RGBW NeoPixel LED strip — 60 pixels, connected to GP7
  - Uses a custom `neopixel.py` library (Neopixel class, not the built-in)
  - Strip color order is GRBW (not RGBW) — all color tuples must be in GRBW order
  - Colors defined as 4-tuples: RED=(0,255,0,0), GREEN=(255,0,0,0), BLUE=(0,0,255,0), etc.
- 3x arcade buttons with built-in LEDs (ALL LEDs are PWM for smooth fading):
  - Red:   switch GP0, LED GP1 (PWM)
  - Green: switch GP2, LED GP3 (PWM)
  - Blue:  switch GP4, LED GP5 (PWM)
- Passive buzzer on GP6 (PWM controlled)
- All buttons use PULL_UP — value() is False when pressed
- 4-digit 7-segment display (5641AS-style common cathode) driven by a 74HC595 shift
  register for segments + 4 GPIOs for digit-select (multiplexed):
  - 595 SH_CP (clock, pin 11) → GP8
  - 595 ST_CP (latch, pin 12) → GP9
  - 595 DS    (data,  pin 14) → GP10
  - 595 OE (pin 13) tied to GND, MR (pin 10) tied to VCC, GND/VCC at pins 8/16
  - 595 Q0–Q7 → segments A, B, C, D, E, F, G, DP (in that order)
  - Digit-select commons (active LOW, 220Ω inline): D1→GP11, D2→GP12, D3→GP13, D4→GP14
    (D1 = leftmost / thousands; D4 = rightmost / ones)

## Snake Blaster — Game Description

A wave-based survival game on the LED strip.

### Gameplay

- A "snake" (array of colored pixels) creeps from the far end (position 59)
  toward the Pico end (position 0) one pixel per tick
- The player must shoot the HEAD of the snake by pressing the matching color button
- A correct hit removes the head; wrong color appends that color to the snake's tail
- Shot pixels animate from position 0 toward the snake head at TRAVEL_SPEED
- Rapid same-button shots queue into a pipeline (start_pos staggered by SHOT_STACK_GAP)
- Multiple shots can be in the air simultaneously
- If the snake head reaches position 0, the player loses

### Button Combine Mechanic (in-game)

Pressing two or three buttons within COMBINE_WINDOW (4ms) fires a single combined pixel:

- Red + Blue = Purple
- Red + Green = Yellow
- Green + Blue = Cyan
- Red + Green + Blue = White

### Game States

- `STATE_IDLE` — twinkle animation on the strip, all three button LEDs pulse at
  distinct rates to advertise the available game modes, and the 4-digit display
  shows either the snake animation or the last round number (see Display section)
- `STATE_PLAYING` — active gameplay with ticking snake
- `STATE_EXPLODE` — win animation: explosion from last pixel position, triumph jingle
- `STATE_LOSE` — sad trombone jingle, red flash, then returns to STATE_IDLE

### Game Modes

Selected from the idle state by pressing buttons within IDLE_COMBINE_WINDOW (150ms).
Single-button presses also pass through the combine buffer so that an all-3
combo wins out over any single mode.

| Trigger             | Mode constant   | Snake length | Colors            | Tick base | Tick step | Idle pulse  |
| ------------------- | --------------- | ------------ | ----------------- | --------- | --------- | ----------- |
| Green               | `MODE_NORMAL`   | 20           | `ROUND_COLORS`    | 600 ms    | -50 ms    | medium-fast |
| Red                 | `MODE_KIDS`     | 10 + gaps    | `KIDS_ROUND_COLORS` (same progression as green) | 900 ms | -30 ms | slow |
| Blue                | `MODE_HARD`     | 20           | all 7 from round 0 | 550 ms   | -60 ms    | fastest     |
| Red + Green + Blue  | `MODE_MEMORY`   | 20           | `ROUND_COLORS`    | 600 ms    | -50 ms    | (combo)     |

- Tick rate is computed dynamically: `TICK_BASE_<mode> - TICK_STEP_<mode> * round_num`,
  clamped to `TICK_FLOOR` (30 ms). No plateau — each round genuinely faster than the
  last until the floor.
- Winning a round increments round_num and auto-starts next round after WIN_PAUSE (2000ms),
  preserving `game_mode` across rounds.
- Losing resets round_num to 0, resets `game_mode` to MODE_NORMAL, and returns to idle.

### Kids Mode Specifics

- Snake = 10 colored pixels with EMPTY pixels interleaved between each ⇒ 19-cell snake
- On correct hit: pop head AND pop trailing EMPTY so next colored pixel becomes new head
- On wrong hit: append EMPTY then color, preserving the spacing pattern on the tail
- Color progression matches green mode round-for-round

### Hard Mode Specifics

- All seven colors (RED, GREEN, BLUE, PURPLE, CYAN, YELLOW, WHITE) available from round 0
- Single `HARD_ROUND_COLORS` list (no per-round table)

### Memory Mode Specifics

- Same colors progression and tick rate as `MODE_NORMAL`
- Snake alternates between visible and concealed every `MEMORY_REVEAL_TICKS` (3) ticks:
  ticks 1–3 visible, 4–6 concealed (all snake pixels rendered as WHITE),
  7–9 visible, 10–12 concealed, etc.
- Shot/hit logic still uses the TRUE underlying colors stored in `snake[]` —
  rendering applies the conceal mask only at the display layer
- Wrong-hit appends still add the true color to the tail; if appended during a
  concealed phase the new pixel is also displayed as WHITE
- During concealed ticks, `play_tick_concealed()` plays a lower/longer thunk
  (420 Hz, 18 ms) instead of the normal 800 Hz blip — audible cue for state

### Snake Generation Rules

- Normal/Hard/Memory: 20 pixels long
- Kids: 10 colored + 9 EMPTY gaps = 19 cells
- Max 2 consecutive pixels of the same color
- Colors chosen randomly from the mode's round-specific color pool

## Key Constants (tunable)

- `TRAVEL_SPEED = 0.004` — seconds per shot pixel step (lower = faster)
- `SHOT_PIXELS_PER_STEP = 3` — pixels each shot advances per `step_shots()` call
  (higher = faster shot animation; 1 was the original value)
- `SHOT_STACK_GAP = 2` — pixel separation between rapid stacked shots
- `COMBINE_WINDOW = 0.004` — in-game shot combo window (~4ms, tight so single
  presses fire fast)
- `IDLE_COMBINE_WINDOW = 0.150` — idle mode-select combo window (~150ms, loose for humans)
- `TICK_BASE_*` / `TICK_STEP_*` / `TICK_FLOOR` — see modes table above
- `MEMORY_REVEAL_TICKS = 3` — alternation period for memory mode reveal/conceal
- `WIN_PAUSE = 2000` — ms between explosion clearing and next round starting
- `SOUND_STEPS = 10` — laser sweep duration in loop iterations (~50ms total)
- `LOSE_NUMBER_HOLD_MS = 4000` — ms the lost round number stays on the digit display
  before the idle snake animation takes over
- `SNAKE_LEN = 3` — number of segments lit at once in the idle snake animation
- `SNAKE_ANIM_INTERVAL = 250` — ms per snake animation frame
- Idle LED pulse steps: `red_pwm_step = 450` (slow), `green_pwm_step = 900` (med),
  `blue_pwm_step = 1400` (fastest)
- `PULSE_INTERVAL = 12` — ms between LED PWM fade steps

## Sounds

- `play_tick()` — very quiet 800Hz blip each snake step (visible/normal phase)
- `play_tick_concealed()` — 420Hz hollow thunk during memory mode concealed phase
- `start_laser()` — non-blocking laser sweep (SOUND_START→SOUND_END over SOUND_STEPS)
- `play_happy()` — brief ascending 3-note on correct hit
- `play_error()` — brief low buzz on wrong hit
- `play_triumph()` — 4-note jingle on round win
- `play_sad()` — D4(294)→C4(262)→Bb3(247)→A3(220), durations [0.25,0.25,0.25,0.75]

## Architecture Notes

- Main loop runs every 5 ms (`time.sleep(0.005)`) on core 0
- A second `_thread` runs on core 1 driving the 4-digit display refresh, fully
  independent of the game loop (see 7-segment section)
- Animation timing uses `time.ticks_ms()` / `time.ticks_diff()` — never blocking sleeps
  for animations (exception: `play_happy`, `play_error`, `play_sad`, `play_tick*`
  are blocking but brief)
- `game_mode` (string enum) drives all per-mode branching; replaces older `kids_mode` boolean
- `snake_offset` tracks how many pixels of the snake are on the strip. Increments on tick,
  DECREMENTS on every correct hit (and twice on a kids-mode hit since the trailing gap is
  also popped). The decrement keeps remaining snake colors visually stationary after a hit
  instead of shifting them forward — without it, each correct hit gave the snake a free
  visual tick toward the player end. Clamped at 0.
- `tick_count` is a separate counter that ONLY increments on `tick_snake()` and resets
  per round. Used by `is_concealed()` so that hits-decrementing-snake_offset don't shift
  the memory-mode phase.
- `snake[0]` is always the head (closest to Pico end)
- `traveling_shots` is a list of dicts: `{color, pos, target, correct}`. Each shot
  advances `SHOT_PIXELS_PER_STEP` (3) pixels per `step_shots()` call.
- New shots stagger their starting `pos` behind any in-flight shot by `SHOT_STACK_GAP`,
  so rapid same-button presses visibly chain instead of overlapping
- Shot targets update every frame to track the moving head
- `pending_presses` buffer handles combine window detection — used in BOTH playing
  (combo shots) and idle (mode select) states via `resolve_pending()` /
  `resolve_pending_idle()`
- `lose_handled` flag prevents STATE_LOSE logic from firing more than once per loss
- All three button LEDs use PWM for smooth fading — use `.duty_u16()` not `.value()`
- Idle pulse rates differ per button to advertise relative game-mode difficulty:
  red = slowest (kids), green = medium (normal), blue = fastest (hard)
- **Boot escape hatch**: at the very top of `main.py`, before any imports of game
  state, the red button is read for 2 seconds. Holding it during this window aborts
  `main.py` via `raise SystemExit`, dropping to bare REPL. Recovery aid in case a
  future change introduces an infinite loop or runaway thread that locks the Pico.

## 7-segment display module

### Hardware refresh

- Driven from a dedicated thread on core 1 via `_thread.start_new_thread()`. The
  thread loops `multiplex_step()` + `time.sleep_us(500)` forever, so each of the
  four digits refreshes at ~500 Hz (4 digits × 500 µs cycle = 2 ms total cycle).
  This is well above the human flicker threshold and is fully decoupled from the
  game loop on core 0.
- The strip uses default `transfer_mode="PUT"` (no DMA, no PUT_CRITICAL). Earlier
  attempts to drive the multiplex from a `Timer` IRQ at 1-2 kHz were abandoned: at
  high rates the IRQ overhead consumed 40-60% CPU and slowed the game to a crawl;
  at low rates (or with PUT_CRITICAL/DMA) the WS2812 PIO FIFO could still underflow
  causing random color glitches. The dual-core approach has neither problem
  because the cores share neither CPU time nor PIO state.
- `multiplex_step()` is allocation-free (only pin writes and integer math). The
  `_display_thread()` wrapper has a `try/except` so a transient error keeps the
  thread alive rather than killing it silently.
- Per-digit refresh sequence: disable all four commons → pulse latch low → shift
  new segment byte into 595 MSB-first → pulse latch high → conditionally enable
  target common (active LOW). The conditional enable is the anti-ghost fix —
  positions whose `segment_byte == 0` (blank/leading-zero positions) leave ALL
  commons disabled, so the 595's tiny output leakage current has no path to ground
  and the position stays truly dark.
- `SEG_DIGITS[0..9]` table encodes the standard 7-seg pattern: bit 0 = A through
  bit 7 = DP. `shift_byte()` sends MSB-first, so bit 7 lands on Q7 (DP) and bit 0
  on Q0 (A) — matches the wiring on the breadboard. Per-segment helpers
  `SEG_A`/`SEG_B`/.../`SEG_G` expose the individual bits for the snake animation.

### Display content modes

`display_show_snake` (boolean global) selects what `multiplex_step()` renders:

- **`False` → number mode**: shows `seven_seg_value` (clamped 0-9999) with leading-zero
  blanking. Round 1 = `   1`, round 12 = `  12`, round 1234 = `1234`. Updated only
  by `set_display_number()`, which is called from `start_round()`.
- **`True` → snake animation mode**: shows whatever segments are set in
  `snake_segments` (a 4-byte `bytearray`, one byte per digit). Updated by
  `update_snake_segments()` once per animation frame.

### Idle snake animation

- Path: 20 segment positions (5 per digit × 4 digits). Per digit the snake walks
  E (bottom-left vertical) → F (top-left vertical) → A (top horizontal) → B
  (top-right vertical) → C (bottom-right vertical), then transitions to the next
  digit at E and repeats. After D4 C, direction reverses and the snake walks the
  same path backward.
- A 3-segment-long snake slides through the path. Head leads, two trailing
  segments behind. Bounce at each end of the path (length-1 transition frame
  shows only 2 visible segments, then back to 3).
- Frame rate: one `advance_snake_anim()` + `update_snake_segments()` every
  `SNAKE_ANIM_INTERVAL = 250` ms. Full forward sweep ≈ 5 sec, full back-and-forth
  ≈ 10 sec.
- Animation work runs in `render_idle()` on core 0. Core 1 reads the
  `snake_segments` bytearray for rendering — single-byte reads are atomic on
  RP2040, so cross-core access is safe without a lock.

### Display state lifecycle

- **Boot**: `display_show_snake = True`, `update_snake_segments()` populates the
  initial frame, then core 1 thread starts. Snake animation visible immediately.
- **Mode start (any button → `start_round()`)**: `display_show_snake = False`,
  `display_snake_start_at = 0` (cancels any pending lose timer),
  `set_display_number(round_num + 1)` writes `   1` (or higher).
- **Round won → next round**: `start_round(game_mode)` again. Display advances to
  next round number, snake stays off.
- **Round lost (STATE_LOSE handler)**: after `play_sad()` and `flash_red()`,
  `display_show_snake = False` (still showing lost round number) and
  `display_snake_start_at = ticks_ms() + LOSE_NUMBER_HOLD_MS` (4 sec from now).
- **Idle after loss**: `render_idle()` checks the timer each iteration. When
  `time.ticks_diff(now, display_snake_start_at) >= 0`, the snake takes over:
  `display_show_snake = True`, head reset to 0, direction forward.
- The 4-second hold gives the player time to see the round they ended on, then
  the screensaver kicks in and runs until they start a new game.
