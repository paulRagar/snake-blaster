# Snake Blaster

A handheld arcade-style LED game built on a Raspberry Pi Pico running MicroPython.
A "snake" of colored pixels creeps down an addressable LED strip toward the player.
Shoot the head of the snake by pressing the matching color button before it reaches the end.

## Hardware

- Raspberry Pi Pico (MicroPython)
- 60-pixel RGBW NeoPixel strip
- 3 arcade buttons with built-in LEDs (red, green, blue)
- Passive piezo buzzer
- 4-digit 7-segment display driven by a 74HC595 shift register, used as a round counter

## Gameplay

The snake starts at the far end of the strip and ticks one pixel closer per beat.
The player presses the button matching the head's color to fire a shot down the
strip. A correct hit removes the head; a wrong color appends to the tail. Pressing
two buttons together fires a combined color — Red+Blue = Purple, Red+Green = Yellow,
Green+Blue = Cyan, all three = White. Clear the snake before its head reaches the
player end of the strip to win the round. Each round gets faster and adds more
colors to the snake.

## Game Modes

Pick a mode from the idle screen by pressing one or more buttons:

- **Green** — Normal. Default difficulty curve, RGB-only at first then adds colors.
- **Red** — Kids. Slower snake with gaps between pixels, gentler ramp.
- **Blue** — Hard. All seven colors from the start, faster baseline and ramp.
- **All three** — Memory. Snake reveals itself for a few ticks then conceals
  (everything renders white); player has to remember the colors.

The 4-digit display shows the current round number during play

## Files

- `main.py` — game logic, hardware setup, all four game modes, display driver
- `neopixel.py` — PIO-based WS2812 driver
