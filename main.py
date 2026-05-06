from machine import Pin, PWM, Timer
import time
import random
import _thread
from neopixel import Neopixel

# ---------- Boot escape hatch ----------
# Hold the RED button at power-on for 2 seconds to abort main.py before any
# Timer / IRQ / display code runs. Drops to bare REPL so Thonny can rename or
# edit files. Without this, an infinite-loop Timer in the file can lock the Pico
# and force a BOOTSEL wipe to recover.
_boot_red = Pin(0, Pin.IN, Pin.PULL_UP)
time.sleep(2)
if not _boot_red.value():
    raise SystemExit("Boot aborted — red button held at startup. Drop to REPL.")

# ---------- Hardware setup ----------
redSwitch   = Pin(0, Pin.IN, Pin.PULL_UP)
greenSwitch = Pin(2, Pin.IN, Pin.PULL_UP)
blueSwitch  = Pin(4, Pin.IN, Pin.PULL_UP)

redLED   = PWM(Pin(1))        # PWM for smooth fade (kids mode pulse)
redLED.freq(1000)
greenLED = PWM(Pin(3))        # PWM for smooth fade (normal mode pulse)
greenLED.freq(1000)
blueLED  = PWM(Pin(5))        # PWM for smooth fade (hard mode pulse)
blueLED.freq(1000)

buzzer = PWM(Pin(6))

NUM_PIXELS = 60
strip      = Neopixel(NUM_PIXELS, 0, 7, "RGBW")
strip.brightness(7)

# ---------- 4-digit 7-segment display (74HC595 + common-cathode 5641AS-style) ----------
# 595 control pins
SEG_CLOCK = Pin(8,  Pin.OUT, value=0)   # SH_CP — shifts each bit on rising edge
SEG_LATCH = Pin(9,  Pin.OUT, value=0)   # ST_CP — copies shift register to outputs on rising edge
SEG_DATA  = Pin(10, Pin.OUT, value=0)   # DS    — serial data input

# Digit-select pins (active LOW — sink current to enable that digit's common cathode)
# Order: leftmost digit (thousands) → rightmost (ones)
DIGIT_PINS = [
    Pin(11, Pin.OUT, value=1),  # D1 — thousands
    Pin(12, Pin.OUT, value=1),  # D2 — hundreds
    Pin(13, Pin.OUT, value=1),  # D3 — tens
    Pin(14, Pin.OUT, value=1),  # D4 — ones
]

# Segment encoding for digits 0-9.
# 595 wiring: Q0=A, Q1=B, Q2=C, Q3=D, Q4=E, Q5=F, Q6=G, Q7=DP.
# shift_byte uses MSB-first, so bit 7 lands on Q7 (DP) and bit 0 on Q0 (A).
SEG_DIGITS = [
    0x3F,  # 0  : A B C D E F
    0x06,  # 1  : B C
    0x5B,  # 2  : A B D E G
    0x4F,  # 3  : A B C D G
    0x66,  # 4  : B C F G
    0x6D,  # 5  : A C D F G
    0x7D,  # 6  : A C D E F G
    0x07,  # 7  : A B C
    0x7F,  # 8  : A B C D E F G
    0x6F,  # 9  : A B C D F G
]
SEG_BLANK = 0x00

# Idle snake animation path. Each entry is (digit_index, segment_bit).
# Snake weaves through every digit: left side up, across the top, right side down.
# Forward direction lights segments in this order; bounces at each end.
SEG_A = 0x01   # top horizontal
SEG_B = 0x02   # top-right vertical
SEG_C = 0x04   # bottom-right vertical
SEG_D = 0x08   # bottom horizontal
SEG_E = 0x10   # bottom-left vertical
SEG_F = 0x20   # top-left vertical
SEG_G = 0x40   # middle horizontal

SNAKE_PATH = [
    (0, SEG_E), (0, SEG_F), (0, SEG_A), (0, SEG_B), (0, SEG_C),  # D1: ↑ left, → top, ↓ right
    (1, SEG_E), (1, SEG_F), (1, SEG_A), (1, SEG_B), (1, SEG_C),  # D2
    (2, SEG_E), (2, SEG_F), (2, SEG_A), (2, SEG_B), (2, SEG_C),  # D3
    (3, SEG_E), (3, SEG_F), (3, SEG_A), (3, SEG_B), (3, SEG_C),  # D4
]
SNAKE_LEN           = 3       # how many segments are lit at a time
SNAKE_ANIM_INTERVAL = 250     # ms per animation frame (lower = faster)
LOSE_NUMBER_HOLD_MS = 4000    # how long to keep the round number on after a loss

# ---------- Colors (GRBW order) ----------
RED    = (0, 255, 0, 0)
GREEN  = (255, 0, 0, 0)
BLUE   = (0, 0, 255, 0)
YELLOW = (255, 255, 0, 0)
PURPLE = (0, 128, 128, 0)
CYAN   = (128, 0, 128, 0)
WHITE  = (0, 0, 0, 255)
EMPTY  = (0, 0, 0, 0)

ALL_COLORS = [RED, GREEN, BLUE, YELLOW, PURPLE, CYAN, WHITE]

# ---------- Constants ----------
SNAKE_LENGTH       = 20
KIDS_SNAKE_COLORS  = 10   # 10 colored pixels with EMPTY between → 19 cells total
COMBINE_WINDOW       = 0.004   # in-game shot combo — tight so single presses fire fast
IDLE_COMBINE_WINDOW  = 0.150   # idle mode-select combo (loose, easier for humans)
TRAVEL_SPEED         = 0.004   # seconds per shot pixel step (lower = faster)
SHOT_PIXELS_PER_STEP = 2       # pixels each shot advances per step_shots call (higher = faster animation)
SHOT_STACK_GAP       = 2       # pixels of separation between stacked rapid shots
WIN_PAUSE          = 2000
TWINKLE_INTERVAL   = 80
EXPLODE_FRAMES     = 20
SOUND_STEPS        = 10
SOUND_START        = 2000
SOUND_END          = 400

# Tick rate progression: linear decrement per round, never plateaus.
# Kids = easiest baseline + gentlest ramp.
# Normal = default.
# Hard = slightly faster baseline + slightly steeper ramp than normal.
TICK_BASE_NORMAL = 600   # ms per snake step at round 0
TICK_BASE_KIDS   = 900
TICK_BASE_HARD   = 550
TICK_STEP_NORMAL = 50    # ms shaved off per round
TICK_STEP_KIDS   = 30
TICK_STEP_HARD   = 60
TICK_FLOOR       = 30    # hardware safety minimum (5ms loop period)

ROUND_COLORS = [
    [RED, GREEN, BLUE],
    [RED, GREEN, BLUE],
    [RED, GREEN, BLUE],
    [RED, GREEN, BLUE, PURPLE],
    [RED, GREEN, BLUE, PURPLE, CYAN],
    [RED, GREEN, BLUE, PURPLE, CYAN, YELLOW],
    [RED, GREEN, BLUE, PURPLE, CYAN, YELLOW, WHITE],
]

KIDS_ROUND_COLORS = [
    [RED, GREEN, BLUE],
    [RED, GREEN, BLUE],
    [RED, GREEN, BLUE],
    [RED, GREEN, BLUE, PURPLE],
    [RED, GREEN, BLUE, PURPLE, CYAN],
    [RED, GREEN, BLUE, PURPLE, CYAN, YELLOW],
    [RED, GREEN, BLUE, PURPLE, CYAN, YELLOW, WHITE],
]

HARD_ROUND_COLORS = [RED, GREEN, BLUE, PURPLE, CYAN, YELLOW, WHITE]   # all colors from round 0

STATE_IDLE    = "idle"
STATE_PLAYING = "playing"
STATE_EXPLODE = "explode"
STATE_LOSE    = "lose"

MODE_NORMAL = "normal"   # green button             — default
MODE_KIDS   = "kids"     # red button               — easier, gap-spaced snake
MODE_HARD   = "hard"     # blue button              — all colors from round 0, faster ramp
MODE_MEMORY = "memory"   # all three buttons combo  — reveals/conceals snake every N ticks

MEMORY_REVEAL_TICKS = 3   # ticks visible, then same number concealed, alternating

# ---------- Global state ----------
game_state = STATE_IDLE
round_num  = 0
game_mode  = MODE_NORMAL

snake           = []
snake_offset    = 0
tick_count      = 0   # ticks elapsed in current round (decoupled from snake_offset)
traveling_shots = []
pending_presses = []

last_tick_time    = time.ticks_ms()
last_step_time    = time.ticks_ms()
last_twinkle_time = time.ticks_ms()

sound_steps_remaining = 0

explode_frame  = 0
explode_origin = 0
explode_active = False
state_timer    = None

twinkle_pixels = []

# Green LED fade state — faster pulse = "fast" game mode visual cue
green_pwm_val  = 0
green_pwm_dir  = 1
green_pwm_step = 900    # faster than red — signals normal/fast mode
last_pulse_time = time.ticks_ms()
PULSE_INTERVAL  = 12    # ms between each fade step

# Red LED fade state — slower pulse = "kids/slow" game mode visual cue
red_pwm_val  = 0
red_pwm_dir  = 1
red_pwm_step = 450      # slower than green — signals kids mode
last_red_pulse_time = time.ticks_ms()

# Blue LED fade state — fastest pulse = "hard mode" visual cue
blue_pwm_val  = 0
blue_pwm_dir  = 1
blue_pwm_step = 1400    # faster than green — signals hard mode
last_blue_pulse_time = time.ticks_ms()

# Lose sequence flag — ensures sad trombone only fires once
lose_handled = False

red_last   = True
green_last = True
blue_last  = True


# ============================================================
# 4-digit 7-segment display driver
# ============================================================
# Currently displayed value (0-9999). Updated by set_display_number();
# read by multiplex_step() during the main loop's pacing slot.
seven_seg_value = 1
_current_digit  = 0   # which of the 4 positions is currently being lit

# Snake animation state (idle screensaver on the digit display).
# When display_show_snake is True, multiplex_step renders snake_segments instead
# of the round-number segments. Animation frames are computed on core 0; core 1
# only reads snake_segments (per-byte atomic reads, safe across cores).
snake_segments          = bytearray(4)
snake_anim_head         = 0
snake_anim_dir          = 1
last_snake_anim_time    = time.ticks_ms()
display_show_snake      = True   # boot default — show snake straight away
display_snake_start_at  = 0      # ticks_ms target for snake to (re)activate; 0 = inactive timer

def shift_byte(b):
    # MSB-first into 595's shift register
    for i in range(8):
        bit = (b >> (7 - i)) & 1
        SEG_DATA.value(bit)
        SEG_CLOCK.value(1)
        SEG_CLOCK.value(0)

def _display_digit(digit_index, segment_byte):
    # Disable all digits first to prevent ghosting between positions
    for p in DIGIT_PINS:
        p.value(1)
    # Shift new segment pattern in while outputs are inert
    SEG_LATCH.value(0)
    shift_byte(segment_byte)
    SEG_LATCH.value(1)
    # Enable target digit ONLY if there's something to show. For blank positions
    # we leave all commons disabled — otherwise the 595's tiny leakage current
    # finds a ground path through the enabled digit and faintly lights segments.
    if segment_byte:
        DIGIT_PINS[digit_index].value(0)

def multiplex_step():
    # Drive ONE digit. Called from core 1 every ~500µs so it stays sequential
    # with strip.show() on core 0. Picks rendering source based on display mode:
    # snake animation (idle screensaver) or numeric round counter.
    global _current_digit
    if display_show_snake:
        _display_digit(_current_digit, snake_segments[_current_digit])
    else:
        val = seven_seg_value
        if val < 0:
            val = 0
        elif val > 9999:
            val = 9999
        divisor   = (1000, 100, 10, 1)[_current_digit]
        if divisor > val and divisor > 1:
            _display_digit(_current_digit, SEG_BLANK)
        else:
            digit_val = (val // divisor) % 10
            _display_digit(_current_digit, SEG_DIGITS[digit_val])
    _current_digit = (_current_digit + 1) % 4

def update_snake_segments():
    # Recompute the per-digit segment bytes from the current snake head + direction.
    # Three segments are lit at a time (head + two trailing). Tail is computed by
    # walking backward through SNAKE_PATH against the current direction.
    snake_segments[0] = 0
    snake_segments[1] = 0
    snake_segments[2] = 0
    snake_segments[3] = 0
    for i in range(SNAKE_LEN):
        pos = snake_anim_head - i * snake_anim_dir
        if 0 <= pos < len(SNAKE_PATH):
            digit, bit = SNAKE_PATH[pos]
            snake_segments[digit] |= bit

def advance_snake_anim():
    # Move head forward by one. Bounce at either end of the path.
    global snake_anim_head, snake_anim_dir
    next_head = snake_anim_head + snake_anim_dir
    if next_head >= len(SNAKE_PATH) or next_head < 0:
        snake_anim_dir = -snake_anim_dir
        next_head = snake_anim_head + snake_anim_dir
    snake_anim_head = next_head

def blank_all_digits():
    # Even out brightness across positions: blank between cycles so the most-recently
    # lit digit doesn't linger through the next iteration's render work.
    DIGIT_PINS[0].value(1)
    DIGIT_PINS[1].value(1)
    DIGIT_PINS[2].value(1)
    DIGIT_PINS[3].value(1)

def set_display_number(num):
    global seven_seg_value
    if num < 0:
        num = 0
    elif num > 9999:
        num = 9999
    seven_seg_value = num


# ============================================================
# Sound
# ============================================================

def play_tick():
    buzzer.freq(800)
    buzzer.duty_u16(2000)
    time.sleep(0.012)
    buzzer.duty_u16(0)

def play_tick_concealed():
    # Hollow, lower thunk for the concealed phase of memory mode
    buzzer.freq(420)
    buzzer.duty_u16(2000)
    time.sleep(0.018)
    buzzer.duty_u16(0)

def start_laser():
    global sound_steps_remaining
    sound_steps_remaining = SOUND_STEPS

def play_happy():
    for freq in [1000, 1400, 1800]:
        buzzer.freq(freq)
        buzzer.duty_u16(20000)
        time.sleep(0.04)
    buzzer.duty_u16(0)

def play_error():
    for freq in [300, 250]:
        buzzer.freq(freq)
        buzzer.duty_u16(20000)
        time.sleep(0.04)
    buzzer.duty_u16(0)

def play_triumph():
    notes = [1047, 1319, 1568, 2093]
    for note in notes:
        buzzer.freq(note)
        buzzer.duty_u16(25000)
        time.sleep(0.12)
    buzzer.duty_u16(0)

def play_sad():
    notes    = [294, 262, 247, 220]   # D4, C4, B♭3, A3
    durations = [0.25, 0.25, 0.25, 0.75]
    for freq, dur in zip(notes, durations):
        buzzer.freq(freq)
        buzzer.duty_u16(25000)
        time.sleep(dur)
    buzzer.duty_u16(0)


# ============================================================
# Snake generation
# ============================================================

def generate_snake(round_index, mode):
    if mode == MODE_KIDS:
        colors = KIDS_ROUND_COLORS[min(round_index, len(KIDS_ROUND_COLORS) - 1)]
        count  = KIDS_SNAKE_COLORS
    elif mode == MODE_HARD:
        colors = HARD_ROUND_COLORS
        count  = SNAKE_LENGTH
    else:
        colors = ROUND_COLORS[min(round_index, len(ROUND_COLORS) - 1)]
        count  = SNAKE_LENGTH
    pixels  = []
    max_run = 2
    run     = 0
    last    = None
    for _ in range(count):
        choices = colors[:]
        if run >= max_run and last in choices and len(choices) > 1:
            choices.remove(last)
        c = random.choice(choices)
        pixels.append(c)
        if c == last:
            run += 1
        else:
            run  = 1
            last = c
    if mode == MODE_KIDS:
        spaced = []
        for i, c in enumerate(pixels):
            spaced.append(c)
            if i < len(pixels) - 1:
                spaced.append(EMPTY)
        return spaced
    return pixels


# ============================================================
# Helpers
# ============================================================

def get_tick_rate(round_index):
    if game_mode == MODE_KIDS:
        rate = TICK_BASE_KIDS - TICK_STEP_KIDS * round_index
    elif game_mode == MODE_HARD:
        rate = TICK_BASE_HARD - TICK_STEP_HARD * round_index
    else:
        rate = TICK_BASE_NORMAL - TICK_STEP_NORMAL * round_index
    return max(rate, TICK_FLOOR)

def snake_head_pos():
    pos = NUM_PIXELS - snake_offset
    if 0 <= pos < NUM_PIXELS:
        return pos
    return None

def is_concealed():
    # Memory mode: snake alternates visible/concealed every MEMORY_REVEAL_TICKS ticks.
    # Driven by tick_count (true elapsed ticks) so that correct hits — which retract
    # snake_offset to keep the snake from visually advancing — don't shift the phase.
    if game_mode != MODE_MEMORY or tick_count <= 0:
        return False
    return ((tick_count - 1) // MEMORY_REVEAL_TICKS) % 2 == 1

def clear_strip_display():
    for i in range(NUM_PIXELS):
        strip.set_pixel(i, EMPTY)
    strip.show()

def flash_red():
    for _ in range(3):
        for i in range(NUM_PIXELS):
            strip.set_pixel(i, RED)
        strip.show()
        time.sleep(0.2)
        clear_strip_display()
        time.sleep(0.15)


# ============================================================
# Rendering
# ============================================================

def render_playing():
    display  = [EMPTY] * NUM_PIXELS
    visible  = min(snake_offset, len(snake), NUM_PIXELS)
    head_pos = NUM_PIXELS - snake_offset
    concealed = is_concealed()
    for i in range(visible):
        pos = head_pos + i
        if 0 <= pos < NUM_PIXELS:
            color = snake[i]
            if concealed and color != EMPTY:
                color = WHITE
            display[pos] = color
    for shot in traveling_shots:
        if 0 <= shot['pos'] < NUM_PIXELS:
            display[shot['pos']] = shot['color']
    for i in range(NUM_PIXELS):
        strip.set_pixel(i, display[i])
    strip.show()

def render_explode():
    global explode_frame, explode_active
    display = [EMPTY] * NUM_PIXELS
    radius  = explode_frame // 2
    for i in range(NUM_PIXELS):
        dist       = abs(i - explode_origin)
        brightness = max(0.0, 1.0 - explode_frame / EXPLODE_FRAMES)
        if dist == radius:
            val = int(255 * brightness)
            display[i] = (0, val, val, val)
        elif dist < radius:
            val = int(120 * brightness)
            display[i] = (0, val // 2, val // 2, val // 2)
    for i in range(NUM_PIXELS):
        strip.set_pixel(i, display[i])
    strip.show()
    explode_frame += 1
    if explode_frame >= EXPLODE_FRAMES:
        explode_active = False

def render_idle():
    global twinkle_pixels, last_twinkle_time
    global green_pwm_val, green_pwm_dir, last_pulse_time
    global red_pwm_val, red_pwm_dir, last_red_pulse_time
    global blue_pwm_val, blue_pwm_dir, last_blue_pulse_time
    global display_show_snake, display_snake_start_at
    global last_snake_anim_time, snake_anim_head, snake_anim_dir

    now = time.ticks_ms()

    # --- Snake animation activation (post-lose hold expires → snake takes over) ---
    if not display_show_snake and display_snake_start_at:
        if time.ticks_diff(now, display_snake_start_at) >= 0:
            display_show_snake     = True
            display_snake_start_at = 0
            snake_anim_head        = 0
            snake_anim_dir         = 1
            last_snake_anim_time   = now
            update_snake_segments()

    # --- Snake animation frame advance ---
    if display_show_snake:
        if time.ticks_diff(now, last_snake_anim_time) >= SNAKE_ANIM_INTERVAL:
            last_snake_anim_time = now
            advance_snake_anim()
            update_snake_segments()

    # --- Twinkles ---
    if time.ticks_diff(now, last_twinkle_time) >= TWINKLE_INTERVAL:
        last_twinkle_time = now

        # Spawn more twinkles — higher probability, higher max count
        if random.random() < 0.6 and len(twinkle_pixels) < 30:
            twinkle_pixels.append({
                'pos':      random.randint(0, NUM_PIXELS - 1),
                'color':    random.choice(ALL_COLORS),
                'life':     0,
                'max_life': random.randint(6, 16)
            })

        alive = []
        for t in twinkle_pixels:
            t['life'] += 1
            if t['life'] < t['max_life']:
                alive.append(t)
        twinkle_pixels = alive

        display = [EMPTY] * NUM_PIXELS
        for t in twinkle_pixels:
            half = t['max_life'] // 2
            brightness = t['life'] / half if t['life'] <= half else (t['max_life'] - t['life']) / half
            display[t['pos']] = tuple(int(v * brightness) for v in t['color'])
        for i in range(NUM_PIXELS):
            strip.set_pixel(i, display[i])
        strip.show()

    # --- Green LED smooth PWM fade (fast = normal mode prompt) ---
    if time.ticks_diff(now, last_pulse_time) >= PULSE_INTERVAL:
        last_pulse_time = now
        green_pwm_val  += green_pwm_dir * green_pwm_step
        if green_pwm_val >= 65535:
            green_pwm_val = 65535
            green_pwm_dir = -1
        elif green_pwm_val <= 0:
            green_pwm_val = 0
            green_pwm_dir = 1
        greenLED.duty_u16(green_pwm_val)

    # --- Red LED smooth PWM fade (slow = kids mode prompt) ---
    if time.ticks_diff(now, last_red_pulse_time) >= PULSE_INTERVAL:
        last_red_pulse_time = now
        red_pwm_val += red_pwm_dir * red_pwm_step
        if red_pwm_val >= 65535:
            red_pwm_val = 65535
            red_pwm_dir = -1
        elif red_pwm_val <= 0:
            red_pwm_val = 0
            red_pwm_dir = 1
        redLED.duty_u16(red_pwm_val)

    # --- Blue LED smooth PWM fade (fastest = hard mode prompt) ---
    if time.ticks_diff(now, last_blue_pulse_time) >= PULSE_INTERVAL:
        last_blue_pulse_time = now
        blue_pwm_val += blue_pwm_dir * blue_pwm_step
        if blue_pwm_val >= 65535:
            blue_pwm_val = 65535
            blue_pwm_dir = -1
        elif blue_pwm_val <= 0:
            blue_pwm_val = 0
            blue_pwm_dir = 1
        blueLED.duty_u16(blue_pwm_val)


# ============================================================
# Game logic
# ============================================================

def start_round(mode=MODE_NORMAL):
    global snake, snake_offset, tick_count, traveling_shots, pending_presses
    global last_tick_time, last_step_time, game_state
    global explode_frame, explode_active, twinkle_pixels
    global green_pwm_val, red_pwm_val, blue_pwm_val, game_mode
    global display_show_snake, display_snake_start_at
    game_mode             = mode
    display_show_snake    = False                    # show round number, not snake
    display_snake_start_at = 0                       # cancel any pending lose timer
    set_display_number(round_num + 1)   # rounds are 0-indexed internally; display shows 1-indexed
    snake           = generate_snake(round_num, game_mode)
    snake_offset    = 0
    tick_count      = 0
    traveling_shots = []
    pending_presses = []
    twinkle_pixels  = []
    explode_active  = False
    explode_frame   = 0
    last_tick_time  = time.ticks_ms()
    last_step_time  = time.ticks_ms()
    game_state      = STATE_PLAYING
    green_pwm_val   = 0
    red_pwm_val     = 0
    blue_pwm_val    = 0
    greenLED.duty_u16(0)   # idle pulse off during play
    redLED.duty_u16(0)
    blueLED.duty_u16(0)

def fire_shot(color):
    head = snake_head_pos()
    if head is None:
        return
    correct = (len(snake) > 0 and color == snake[0])
    # Stack rapid shots in a pipeline so a second click starts behind the first
    start_pos = 0
    for s in traveling_shots:
        if s['pos'] <= start_pos:
            start_pos = s['pos'] - SHOT_STACK_GAP
    traveling_shots.append({
        'color':   color,
        'pos':     start_pos,
        'target':  head,
        'correct': correct
    })
    start_laser()

def step_shots():
    global snake, snake_offset, game_state, explode_origin
    global explode_frame, explode_active, state_timer
    arrived = []
    for shot in traveling_shots:
        head = snake_head_pos()
        if head is not None:
            shot['target']  = head
            shot['correct'] = (len(snake) > 0 and shot['color'] == snake[0])
        if shot['pos'] < shot['target']:
            shot['pos'] += SHOT_PIXELS_PER_STEP
        else:
            arrived.append(shot)
    for shot in arrived:
        traveling_shots.remove(shot)
        if not snake:
            continue
        head = snake_head_pos()
        if shot['correct']:
            play_happy()
            snake.pop(0)
            # Retract head_pos by 1 so remaining snake colors stay at their pre-hit
            # screen positions instead of all shifting forward (which would look like
            # the snake advanced one free tick on every correct hit).
            if snake_offset > 0:
                snake_offset -= 1
            # Kids mode: also drop the trailing gap so next colored pixel is the new head
            if game_mode == MODE_KIDS and snake and snake[0] == EMPTY:
                snake.pop(0)
                if snake_offset > 0:
                    snake_offset -= 1
            if len(snake) == 0:
                game_state     = STATE_EXPLODE
                explode_origin = head if head is not None else NUM_PIXELS // 2
                explode_frame  = 0
                explode_active = True
                play_triumph()
                state_timer    = time.ticks_ms()
            else:
                for s in traveling_shots:
                    s['correct'] = (s['color'] == snake[0])
        else:
            play_error()
            # Kids mode: preserve gap pattern on tail
            if game_mode == MODE_KIDS:
                snake.append(EMPTY)
            snake.append(shot['color'])
            for s in traveling_shots:
                s['correct'] = (len(snake) > 0 and s['color'] == snake[0])

def tick_snake():
    global snake_offset, tick_count, game_state
    if not snake:
        return
    snake_offset += 1
    tick_count   += 1
    if is_concealed():
        play_tick_concealed()
    else:
        play_tick()
    head = snake_head_pos()
    if head is not None and head <= 0:
        game_state = STATE_LOSE


# ============================================================
# Button input
# ============================================================

def resolve_pending():
    global pending_presses
    if not pending_presses:
        return
    now    = time.ticks_ms()
    oldest = pending_presses[0]['time']
    if time.ticks_diff(now, oldest) < int(COMBINE_WINDOW * 1000):
        return
    colors    = [p['color'] for p in pending_presses]
    pending_presses = []
    has_red   = RED in colors
    has_green = GREEN in colors
    has_blue  = BLUE in colors
    if has_red and has_green and has_blue:
        fire_shot(WHITE)
    elif has_red and has_green:
        fire_shot(YELLOW)
    elif has_red and has_blue:
        fire_shot(PURPLE)
    elif has_green and has_blue:
        fire_shot(CYAN)
    else:
        for color in colors:
            fire_shot(color)

def resolve_pending_idle():
    # Buffer idle presses through the same combine window so that pressing all
    # three buttons together triggers MODE_MEMORY instead of any single-button mode.
    global pending_presses
    if not pending_presses:
        return
    now    = time.ticks_ms()
    oldest = pending_presses[0]['time']
    if time.ticks_diff(now, oldest) < int(IDLE_COMBINE_WINDOW * 1000):
        return
    colors = [p['color'] for p in pending_presses]
    pending_presses = []
    has_red   = RED in colors
    has_green = GREEN in colors
    has_blue  = BLUE in colors
    if has_red and has_green and has_blue:
        start_round(MODE_MEMORY)
    elif colors[0] == GREEN:
        start_round(MODE_NORMAL)
    elif colors[0] == RED:
        start_round(MODE_KIDS)
    elif colors[0] == BLUE:
        start_round(MODE_HARD)

def handle_button_press(color):
    if game_state == STATE_PLAYING:
        pending_presses.append({'color': color, 'time': time.ticks_ms()})
    elif game_state == STATE_IDLE:
        pending_presses.append({'color': color, 'time': time.ticks_ms()})


# ============================================================
# Boot + main loop
# ============================================================

clear_strip_display()
update_snake_segments()   # populate first snake frame so core 1 has something to render at boot

# ---------- Core 1: 4-digit display refresh thread ----------
# Runs continuously on the second CPU core, completely independent of the game
# loop on core 0. Each digit refreshes at ~500Hz, fully flicker-free, with no
# CPU stolen from gameplay. The try/except wrapper prevents a transient error
# from killing the thread silently. If the thread does die, the display will
# freeze on whatever it last showed; the game itself keeps running.
def _display_thread():
    while True:
        try:
            multiplex_step()
            time.sleep_us(500)
        except Exception:
            time.sleep_ms(10)

_thread.start_new_thread(_display_thread, ())

while True:
    now = time.ticks_ms()

    # ---------- Read buttons ----------
    red_current   = redSwitch.value()
    green_current = greenSwitch.value()
    blue_current  = blueSwitch.value()

    if red_last == True and red_current == False:
        handle_button_press(RED)
    if game_state != STATE_IDLE:
        redLED.duty_u16(65535 if not red_current else 0)
    red_last = red_current

    if green_last == True and green_current == False:
        handle_button_press(GREEN)
    if game_state != STATE_IDLE:
        greenLED.duty_u16(65535 if not green_current else 0)
    green_last = green_current

    if blue_last == True and blue_current == False:
        handle_button_press(BLUE)
    if game_state != STATE_IDLE:
        blueLED.duty_u16(65535 if not blue_current else 0)
    blue_last = blue_current

    # ---------- Resolve pending ----------
    if game_state == STATE_PLAYING:
        resolve_pending()
    elif game_state == STATE_IDLE:
        resolve_pending_idle()

    # ---------- State machine ----------
    if game_state == STATE_IDLE:
        render_idle()

    elif game_state == STATE_PLAYING:
        if time.ticks_diff(now, last_tick_time) >= get_tick_rate(round_num):
            tick_snake()
            last_tick_time = now
        if time.ticks_diff(now, last_step_time) >= int(TRAVEL_SPEED * 1000):
            step_shots()
            last_step_time = now
        render_playing()

    elif game_state == STATE_EXPLODE:
        if explode_active:
            render_explode()
            time.sleep(0.03)
        else:
            if state_timer and time.ticks_diff(now, state_timer) >= WIN_PAUSE:
                round_num += 1
                start_round(game_mode)

    elif game_state == STATE_LOSE:
        if not lose_handled:
            lose_handled = True
            play_sad()
            flash_red()
            clear_strip_display()
            round_num      = 0
            game_mode      = MODE_NORMAL
            twinkle_pixels = []
            green_pwm_val  = 0
            green_pwm_dir  = 1
            red_pwm_val    = 0
            red_pwm_dir    = 1
            blue_pwm_val   = 0
            blue_pwm_dir   = 1
            greenLED.duty_u16(0)
            redLED.duty_u16(0)
            blueLED.duty_u16(0)
            # Keep round number on display for a few seconds, then snake takes over
            display_show_snake     = False
            display_snake_start_at = time.ticks_add(time.ticks_ms(), LOSE_NUMBER_HOLD_MS)
            game_state = STATE_IDLE
        lose_handled = False

    # ---------- Laser sound ----------
    if sound_steps_remaining > 0 and game_state == STATE_PLAYING:
        progress = 1 - (sound_steps_remaining / SOUND_STEPS)
        freq = int(SOUND_START + (SOUND_END - SOUND_START) * progress)
        buzzer.freq(freq)
        buzzer.duty_u16(30000)
        sound_steps_remaining -= 1
    else:
        buzzer.duty_u16(0)

    # 7-segment refresh runs autonomously on core 1; main loop just paces.
    time.sleep(0.005)
