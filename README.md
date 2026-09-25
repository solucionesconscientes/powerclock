<p align="center"><img src="https://raw.githubusercontent.com/solucionesconscientes/powerclock/main/src/powerclock/gui/icons/powerclock.svg" width="96" alt=""></p>

# PowerClock

**Shutdown, wake-up and task scheduler**

**English** · [Español](README.es.md)

> **Status:** pre-release (0.1.0 in preparation). Linux is supported today; Windows and macOS are
> planned. Its Quick tab was inspired by [KShutdown](https://kshutdown.sourceforge.io/); it is a
> separate program, written from scratch and not affiliated with it.

**Schedule shutdown, wake-up and your tasks, at an exact time or when the conditions you choose
are met.** PowerClock shuts down, restarts, suspends, hibernates, locks, logs out and **turns your
computer on** by itself, and runs your programs and scripts **at a time, on a schedule or when a
condition is met**: you stop using the computer, a render or a download finishes, the battery runs
low, the laptop is unplugged…

It does this with **persistent rules** that PowerClock keeps in the background (a small service,
the *daemon*). Rules keep working with the window closed, after a restart, and even with the
session closed. You can
drive it from a **tray icon and a window** (in the spirit of KShutdown), from the **command
line**, or from any program through a **local API**.

![The Quick tab](https://raw.githubusercontent.com/solucionesconscientes/powerclock/main/docs/images/en/quick.png)

---

## Contents

- [What it can do](#what-it-can-do)
- [Screenshots](#screenshots)
- [Requirements](#requirements)
- [Installation](#installation)
- [Getting started in five minutes](#getting-started-in-five-minutes)
- [How it works: the main ideas](#how-it-works-the-main-ideas)
- [The graphical interface](#the-graphical-interface)
- [The command line](#the-command-line)
- [Rules in detail](#rules-in-detail)
- [Turning the computer on and waking it up](#turning-the-computer-on-and-waking-it-up)
- [Conditions and sensors](#conditions-and-sensors)
- [Safety](#safety)
- [Using it on a server](#using-it-on-a-server)
- [Files and settings](#files-and-settings)
- [The local API](#the-local-api)
- [Troubleshooting](#troubleshooting)
- [Uninstalling](#uninstalling)
- [Development](#development)
- [Roadmap](#roadmap)
- [License](#license)

---

## What it can do

**Power actions**

| Action | What happens |
|---|---|
| Shut down | Turns the computer off. By default *gracefully*: your desktop asks open applications to save first (KDE and GNOME). |
| Restart | Reboots, also gracefully by default. |
| Suspend | Sleep to RAM (S3). Resumes in seconds. |
| Hibernate | Saves memory to disk and powers off (needs a swap as large as RAM and `resume=` configured). |
| Hybrid sleep | Suspend + hibernate: resumes fast, and survives a power cut. |
| Lock the screen | Locks your session. |
| Log out | Closes your session (gracefully by default). |
| Turn off the screen | Turns the display off (KDE, GNOME or X11). |
| **Turn on / wake up** | Programs the computer's hardware clock (RTC) so it **wakes from suspend or even powers on from off** at a given time. |

**Other actions** (steps of a rule, run in order): **open an installed application** (picked from
the menu's list, Flatpak and Snap ones too) with ready-made **recipes** (a web page as a kiosk,
a playlist on a loop, a PDF as a presentation…), placing its window on a screen or full screen
and keeping it open if it closes · run a program or a shell command (with a time limit, its output
kept in the history) · open a file or web page · close a program (asking it nicely, then forcing
it) · show a desktop notification · wait a while · wait until a condition is met · program the
next wake-up. File names and texts can carry the date: `radio-{date}.mp3`.

**When** (the *trigger*):

- **At a time**: once at a date and time, after a delay (a countdown), or repeating with a cron
  expression (every night at 03:00, weekdays at 07:30…), in your time zone or another one.
- **When a condition is met**: the computer has not been used for a while · a program ends
  (render, compression, copy…) · the computer goes quiet (low CPU for a while) · a download
  finishes (low network traffic for a while) · the battery goes below/above a level · the laptop is unplugged or
  plugged in · the desktop session starts (after logging in) · PowerClock starts or the computer
  resumes from sleep.
- **By hand**: from the window, the tray, the command line or the API.

**Only if / wait while**:

- **Only if…** (*conditions*) decides whether a rule runs at its moment ("only if plugged in",
  "only on weekdays", "only between 22:00 and 07:00", "only on my home Wi-Fi"…).
- **Wait while…** (*guards*) makes it *wait* and check again ("while a video is playing", "while
  someone is connected by SSH", "while ffmpeg is running") up to a limit.

**Around it**: a **warning** before any power action that you can cancel until the last second
(with *Cancel* and *Postpone 10 minutes* in a notification and a dialog) · a **test mode**
(`--dry-run`) to try everything without turning anything off · a **history** of every run with its result and reason · `powerclock doctor`, which
checks what works on your computer and says how to fix what does not · a **tray icon** · an
interface in **English and Spanish**.

## Screenshots

| | |
|---|---|
| ![Quick tab](https://raw.githubusercontent.com/solucionesconscientes/powerclock/main/docs/images/en/quick.png) **Quick**: an action, when, and a button that says what it will do. Below, what is scheduled. | ![Rules tab](https://raw.githubusercontent.com/solucionesconscientes/powerclock/main/docs/images/en/rules.png) **Rules**: every rule and what comes next. |
| ![Rule editor: conditions](https://raw.githubusercontent.com/solucionesconscientes/powerclock/main/docs/images/en/editor-conditions.png) **Rule editor**: *Only if…*, the conditions. | ![Rule editor: steps](https://raw.githubusercontent.com/solucionesconscientes/powerclock/main/docs/images/en/editor-steps.png) **Rule editor**: the steps, in order. |
| ![History](https://raw.githubusercontent.com/solucionesconscientes/powerclock/main/docs/images/en/history.png) **History**: result and reason of every run. | ![Diagnostics](https://raw.githubusercontent.com/solucionesconscientes/powerclock/main/docs/images/en/diagnostics.png) **Diagnostics**: what works here and how to fix the rest. |
| ![Countdown](https://raw.githubusercontent.com/solucionesconscientes/powerclock/main/docs/images/en/countdown.png) The **countdown** before a power action. | ![Tray menu](https://raw.githubusercontent.com/solucionesconscientes/powerclock/main/docs/images/en/tray-menu.png) The **tray menu**. |

## Requirements

- **Linux with systemd** (logind). Tested on Kubuntu 26.04 with KDE Plasma 6 on Wayland; it also
  supports GNOME and X11, and any desktop for the basics (power actions go through logind).
- **Python 3.11 or newer** (every current distribution has it) and **pipx** to install it.
- For the window and the tray: a graphical session. On GNOME, the tray icon needs the
  *AppIndicator* extension (Ubuntu enables it by default); without it PowerClock works from its window.
- To **turn the computer on** at a time: an RTC wake alarm (almost every PC) and, to power on from
  *off*, a BIOS/UEFI that allows it (usually only on AC power for laptops). `powerclock doctor` tells you.
- A server without a desktop (a VPS) can run PowerClock in the background and its command line alone.

## Installation

### The easy way (Linux)

1. **Download the installer**: [`install-powerclock.sh`](https://github.com/solucionesconscientes/powerclock/releases/latest/download/install-powerclock.sh) (a few KB).
2. **Allow it to run**: right click → *Properties* → *Permissions* → *Allow executing file as
   program* (or, in a terminal, `chmod +x install-powerclock.sh`).
3. **Double-click it.** A terminal shows the download: PowerClock with its own Python and Qt,
   about 130 MB to download and 400 MB on disk, so it does not depend on what your system has.
   Then PowerClock's installation window opens.
4. **Press Install** and type your password when asked (once, so that PowerClock can turn the
   computer on).

That is all: PowerClock is in the tray and in the applications menu, and its service is running.
Everything lives in your home folder except a small program that can only program the wake-up
alarm, so updating never asks for the password. To update: *Diagnostics → Check for updates* (or `powerclock update`). To uninstall:
*Diagnostics → Uninstall PowerClock…* (or `powerclock uninstall`).

Windows and macOS installers will work the same way when those versions arrive.

### With pipx (technical users and servers)

```bash
sudo apt install pipx && pipx ensurepath   # once (Debian/Ubuntu shown); then open a new terminal
pipx install "powerclock[gui]"             # on a server, without the window: pipx install powerclock
powerclock setup                           # service, menu, login start and wake-up helper (sudo once)
powerclock doctor                          # what works on this computer
```

`powerclock setup --no-helper`, `--no-menu`, `--no-login` and `--unattended` choose what to set up;
`powerclock service install` and `powerclock helper install` do it step by step. See
[Using it on a server](#using-it-on-a-server).

## Getting started in five minutes

Everything below can be tried safely first in **test mode**: add `--dry-run` to a quick command,
or install the service with `powerclock service install --dry-run`. Power actions are then only
noted down, never done.

**From the window** (`powerclock gui`), *Quick* tab: pick an *Action* (e.g. *Shut down*), pick *When*
(e.g. *After a delay* → `30m`) and press the button, which says what it will do (*Schedule
shutdown*). It appears under *Scheduled* with its time, and the tray icon turns blue. Cancel or
postpone it from there, from the tray menu or from the warning window that appears one minute
before acting.

**From the command line**:

```bash
powerclock shutdown --in 30m                   # shut down in 30 minutes
powerclock suspend --at 23:30 --wake 07:30     # suspend at 23:30 and wake up at 07:30
powerclock shutdown --when-exits ffmpeg        # shut down when the render ends
powerclock suspend --when-idle 20m             # suspend after 20 minutes without use
powerclock shutdown --when-net-below 50 --for 5m   # shut down when the download is over
powerclock reboot --when-cpu-below 10 --for 5m # restart when the CPU calms down
powerclock run --at 03:00 --wake -- /home/me/bin/backup.sh   # turn on at 03:00 to run a backup
powerclock wake --at "2026-10-01 07:30"        # just turn the computer on at that time

powerclock status      # what is scheduled, running and being watched
powerclock cancel      # cancel the countdown in progress or the next quick action
powerclock postpone 10m
powerclock history     # what ran and why
```

**With a rule** (for anything that repeats): put this in `nightly.json` and add it with
`powerclock rules add nightly.json` (or create it in the *Rules* tab):

```json
{
  "id": "nightly-backup",
  "name": "Nightly backup, then shut down",
  "trigger": {"type": "cron", "expr": "0 3 * * *"},
  "wake": true,
  "conditions": {"type": "power_source", "is": "ac"},
  "guards": {"any": [{"type": "media_playing"}, {"type": "ssh_session"}], "retry": "5m", "max_wait": "2h"},
  "actions": [
    {"type": "run", "cmd": ["/home/me/bin/backup.sh"], "timeout": "2h"},
    {"type": "notify", "title": "PowerClock", "body": "Backup done"},
    {"type": "power", "action": "shutdown"}
  ]
}
```

Every night the computer turns itself on at 02:58, and at 03:00 it runs the backup if it is on
AC. While a video plays or someone is connected by SSH it waits (up to two hours). Then it
notifies you and shuts down after a one-minute countdown you can cancel.

## How it works: the main ideas

- **PowerClock in the background** (`powerclock-daemon`, the *daemon*) does everything: it keeps the rules, watches the time and the
  sensors, runs the actions and records the history. It runs as **your user** (never as root), as
  a systemd user service installed by `powerclock service install`. The window, the tray and the command
  line are only clients: closing them changes nothing.
- **A rule** is: **when** (the *trigger*) + optional **only if…** (*conditions*) + optional **wait
  while…** (*guards*) + **what it does** (the *steps*, in order) + options (warning, only once, turn
  the computer on…).
- **A quick action** is a rule made for you by the Quick tab, the tray or commands such as
  `powerclock shutdown --in 30m`. It runs once and then disappears (its run stays in the history).
- **The warning**: before any power action PowerClock warns you with a countdown you can cancel
  until the last second (60 seconds by default, configurable per rule, `0s` to skip it). During it you get a notification and a window
  with **Cancel** and **Postpone 10 minutes**, and `powerclock cancel` / `powerclock postpone` work too.
- **The history** records every run: when, where it came from (*Schedule*, *Condition* or
  *Manual*), how it ended (*done*, *failed*, *cancelled*, *skipped*) and why, with each step's result
  and the last lines of each command's output.
- **Missed runs**: if a scheduled moment passes while the computer is off or asleep, the rule is
  *skipped* by default; with `"on_missed": "run_once"` it runs once as soon as possible.
- **Time zones**: times follow your computer's time zone; a rule can set its own
  (`"timezone": "Europe/Madrid"`). Summer/winter time changes are handled (a 02:30 job moves to
  03:30 on the spring change, and runs once on the autumn one).

## The graphical interface

Open it with `powerclock gui` or from the applications menu. Only **one** copy runs: opening it again
brings up the window that is already running. Closing the window leaves the tray icon; *Hide the
icon (PowerClock keeps working)* in its menu quits the interface (your rules keep running in the
background).

**Tray icon.** Its colour says what is going on: grey (nothing scheduled), blue with a clock
(something scheduled or being watched), red (a countdown is running), grey and crossed out
(PowerClock is not running in the background). Hover it to see what comes next. Its menu has: what comes next,
**Cancel**, **Postpone 10 minutes**, **Now ▸** (shut down, restart, suspend, hibernate, lock, log
out, turn off the screen; the first ones with their countdown, locking and screen off at once),
**Schedule…**, **Open PowerClock** and **Hide the icon**. A left click opens the window.

**Quick tab** (like KShutdown): choose an **Action** (any power action or *Run a program*),
**When** (now, at a date and time, after a delay, after a period without use, when a program ends
— pick it from the running ones or type its name or PID —, when the computer goes quiet (CPU
below…), when the download finishes (network below…), with how long it must last), **Warn me
first**, whether to **force** (without waiting for applications to save) and **Turn it back on at**
a time. The button says what it will do (*Shut down now*, *Schedule shutdown*…). Below,
**Scheduled** lists the quick actions not done yet, each with **Cancel**
and, if it has a time, **+10 min**. For the ones waiting for a condition it shows what the sensor
sees now ("ffmpeg is running", "idle for 5m 12s", "CPU 35 % · measuring: 2m of 5m").

**Rules tab.** Every rule with a checkbox to enable or disable it, when it fires, what comes next
and its id. **New…**, **Edit…** (or double click), **Run now**, **Delete**, **Import…** and
**Export…** (JSON files).

**Rule editor.** Tabs *When* (name, enabled, and when it acts), *Only if…* (the conditions that
must all hold), *Wait while…* (the reasons to wait, with how often to check again and when to give
up), *What it does* (the steps in order, with ↑ ↓ to reorder), *Options* and *JSON*. The JSON tab shows the same rule as
text and stays in step with the forms when you switch tabs, so you can edit in either. Conditions
more complex than a list (an *any*, nested groups) are kept and can be edited as JSON inside the
form. Mistakes are explained before saving (for example, that shutting down must be the last
step).

**History tab.** Every run with when it finished, the rule, the result, its source and the reason;
select one to see its steps and their output.

**Diagnostics tab.** Whether PowerClock is running in the background (and a button to start
it), everything `powerclock doctor` checks, by name, with how to fix what does not work, the next
wake-up alarm, **Allow turning the computer on…** (shows the exact commands and runs them asking
for your password in a desktop window), **Test a wake-up in 2 minutes…** and two checkboxes: *Show PowerClock in the
applications menu* and *Start the tray icon when the session starts*.

**Warning window.** Appears on top of the others when a power action is about to happen and says
what will happen ("The computer will shut down in 42 s") and that you can cancel it until the last
second: **Cancel** (or Esc) and **Postpone 10 minutes**.

The interface follows your desktop's colours, icons and light or dark mode. Installed with pipx,
Qt draws the controls in its own *Fusion* style; see
[native look on KDE](#native-look-on-kde) to get Breeze exactly.

## The command line

`powerclock --help` and `powerclock COMMAND --help` explain every option. Times accept `23:30` (its next
occurrence), `"2026-10-01 07:30"` (local time) or ISO 8601 with a time zone. Durations are written
as `30s`, `5m`, `2h`, `1d` or combined (`1h30m`).

**Quick actions** — one command per action: `shutdown`, `reboot`, `suspend`, `hibernate`,
`hybrid-sleep`, `lock`, `logout`, `screen-off`, `run -- PROGRAM ARGS…` and
`launch APP [--recipe ID] -- ARGS…` (open an installed application).

| Option | Meaning |
|---|---|
| *(none)* | Now (after the countdown). |
| `--in 30m` | After a delay. |
| `--at 23:30` | At a time. |
| `--when-idle 20m` | When nobody has used the computer for that long. |
| `--when-exits NAME\|PID` | When that program ends. If it is not running yet, PowerClock waits for it to start: a mistyped name never shuts the computer down. |
| `--when-cpu-below 10` | When the average CPU usage stays below 10 % … |
| `--when-net-below 50` | … or the network traffic below 50 kbit/s … |
| `--for 5m` | … for this long (default `5m`). |
| `--warning 2m` | Warn this long before acting (default `60s`; `0s` for none). |
| `--force` | Do not let applications ask to save. |
| `--wake 07:30` | (power actions) Also turn the computer on at that time — e.g. suspend now, wake up in the morning. |
| `--wake` | (`run`, `launch`) Turn the computer on to run or open it (with `--in`/`--at`). |
| `--log-in` | With `--wake` (or `powerclock wake`): log in by itself when that turns the computer on, screen locked. |
| `--recipe ID` | (`launch`) Take the arguments from a recipe; what it asks for (`<url>`, `<file>`…) goes after `--`, in order. |
| `--dry-run` | Global option (`powerclock --dry-run shutdown …`): test mode, the power action is only noted down. |

**Other commands**

| Command | What it does |
|---|---|
| `powerclock wake --at TIME` | Turn the computer on at that time (from suspend, or from off if the BIOS allows it). |
| `powerclock apps [TEXT]` | The installed applications (`launch` opens them by id), with their recipes. |
| `powerclock recipes [APP]` | Ready-made arguments for common applications. |
| `powerclock status` | What is running, what comes next, what is being watched, and the next wake-up alarm. |
| `powerclock cancel [RUN_ID]` | Cancel the countdown in progress; otherwise the quick action running, the next timed one, or the last one waiting for a condition. |
| `powerclock postpone [10m] [--run RUN_ID]` | Postpone the countdown in progress or the next timed quick action. |
| `powerclock history [-n 20] [--rule ID]` | Past runs, their result and why. |
| `powerclock rules list` | Every rule and when it fires next (or what it is watching). |
| `powerclock rules show ID` | A rule as JSON. |
| `powerclock rules add FILE.json` | Add the rules in a file (one rule or a list). |
| `powerclock rules edit ID` | Edit a rule in your `$EDITOR`. |
| `powerclock rules enable\|disable ID` | Turn a rule on or off (it stays saved). |
| `powerclock rules run ID` | Run a rule now (its conditions, guards and countdown still apply). |
| `powerclock rules rm ID` | Delete a rule. |
| `powerclock rules export [FILE]` / `powerclock rules import FILE [--replace]` | Back up and restore rules. |
| `powerclock doctor [--json]` | What works on this computer and how to fix what does not. |
| `powerclock doctor --test-wake 120` | Program a wake-up in N seconds (60–3600) and **suspend now**, then say whether it woke up by itself and what woke it. Asks first and gives 10 seconds to take your hands off. |
| `powerclock service install [--linger] [--dry-run]` · `uninstall` · `status` | The daemon as a systemd user service. `--linger` keeps it running without a login. |
| `powerclock helper install [--unattended] [--print]` · `uninstall` | The small root helper that programs the wake alarm (shows the `sudo` commands and asks before running them). |
| `powerclock gui [--tray]` | Open the window (or only the tray icon). |
| `powerclock setup [--no-menu] [--no-login] [--no-helper] [--unattended]` | Set PowerClock up in this session: service, menu entry, login start and wake-up helper (what the installer's window does). |
| `powerclock update` | Install the newest version and restart the service. |
| `powerclock uninstall [--purge]` | Remove everything (with `--purge`, also rules and history). |

## Rules in detail

Rules are JSON. The editor writes it for you, but it is short enough to write by hand, and the
daemon validates every rule: a typo in a field name is reported, never silently ignored. The full
JSON Schema is served at `/schema/rule` by the local API; [`examples/`](examples/) has ready-made
rules.

```json
{
  "id": "nightly-backup",              // letters, digits, - and _ (optional when creating)
  "name": "Nightly backup",
  "enabled": true,
  "trigger": { … },                     // when
  "conditions": { … },                  // only if (optional)
  "guards": { "any": [ … ], "retry": "5m", "max_wait": "2h" },   // wait while (optional)
  "actions": [ { … }, { … } ],          // what to do, in order
  "warning": "60s",                     // countdown before power actions
  "wake": false,                        // turn the computer on for it (time triggers only)
  "on_missed": "skip",                  // or "run_once"
  "on_error": "stop",                   // or "continue"
  "one_shot": false,                    // disable it after it fires once
  "dry_run": false,                     // only log its power actions
  "timezone": "Europe/Madrid"           // optional; default: the computer's
}
```

(JSON has no comments: they are only explanations here.)

### Triggers

| `type` | Fields | Fires |
|---|---|---|
| `at` | `when` (ISO 8601 with time zone) | Once at that moment. |
| `countdown` | `duration` | That long after the rule is enabled. Survives restarts. |
| `cron` | `expr` (5 fields or `@daily`, `@hourly`…) | On that schedule, in the rule's time zone. |
| `idle` | `for` | When nobody has used the keyboard or mouse for that long. |
| `process_exit` | `name` or `pid` | When the program ends. With a name, when none of that name is left. It must have been seen running first. A PID reused by another process counts as ended. |
| `cpu_below` | `percent`, `for` | When the **average** CPU usage over the last `for` is below `percent`. |
| `net_below` | `kbps`, `for`, `direction` (`down`, `up`, `both`), `interface` (optional) | When the **average** network traffic over the last `for` is below `kbps` kilobits per second. |
| `battery` | `below` or `above` (%), `for` (optional) | When the battery level crosses that threshold (held for `for`). |
| `power_source` | `is` (`ac` or `battery`), `for` (optional) | When the computer is on that power source (held for `for`). |
| `desktop_session` | — | When a desktop session starts (someone logs in), so applications can be opened. |
| `startup` | `on` (`daemon_start`, `resume`), `delay` | When PowerClock starts (e.g. at boot) and/or after resuming from sleep, after `delay`. |
| `manual` | — | Only when run by hand. |

**Triggers that watch a state** (`idle`, `process_exit`, `cpu_below`, `net_below`, `battery`,
`power_source`, `desktop_session`) fire **once** when the state becomes true, and fire again only after it has been
false. Staying idle does not suspend the computer again and again; using it re-arms the rule. If
the state already holds when you enable the rule (the battery is already low), it fires.

### Conditions and guards

Both use the same **predicates**:

| `type` | Fields | True when |
|---|---|---|
| `process_running` | `name` | A program with that name is running. |
| `media_playing` | — | A media player is playing (MPRIS). |
| `ssh_session` | — | Someone is logged in over SSH. |
| `idle` | `for` | Nobody has used the computer for that long. |
| `cpu_below` | `percent`, `for` | Average CPU usage over `for` is below `percent`. |
| `net_below` | `kbps`, `for`, `direction`, `interface` | Average network traffic over `for` is below `kbps`. |
| `battery` | `below` or `above`, `for` | Battery level below/above that. |
| `power_source` | `is`, `for` | On AC or on battery. |
| `time_window` | `start`, `end` (`"22:00"`) | The time of day is in that window (it can cross midnight: 22:00 → 07:00). |
| `weekday` | `days` (`mon` … `sun`) | Today is one of those days. |
| `wifi_ssid` | `ssid` | Connected to that Wi-Fi network. |
| `desktop_session` | — | A desktop session is up. |

Combine them with `{"all": [ … ]}`, `{"any": [ … ]}` and `{"not": … }`, nested as you like.

- **Conditions** are checked when the rule fires: if they do not hold, the run is *skipped* (and
  recorded as such).
- **Guards** (`"guards": {"any": [ … ]}`) are checked just before acting: while any of them holds,
  the run waits and checks again every `retry` (default `5m`), up to `max_wait` (default `2h`);
  after that it is skipped.
- A sensor that cannot be read makes its predicate **unknown**, never a guess. Unknown conditions
  do not let the rule run; unknown guards do not block it; `wait_until` keeps waiting.

### Steps

| `type` | Fields | Does |
|---|---|---|
| `power` | `action` (`shutdown`, `reboot`, `suspend`, `hibernate`, `hybrid_sleep`, `lock`, `logout`, `screen_off`), `mode` (`graceful` or `force`) | A power action, after the countdown. Shut down, restart and log out must be the last step. |
| `run` | `cmd` (list: program and arguments), `cwd`, `env`, `shell`, `timeout`, `wait` | Runs a program. With `"shell": true`, `cmd` is one command line. With `wait` (default) it waits for it and fails if it returns an error; its output is kept in the history. On cancel or timeout it is asked to stop, then killed 5 s later. |
| `launch` | `app` (its id, see `powerclock apps`), `args`, `recipe`, `window` (`screen`, `desktop`, `state`: `normal`/`maximized`/`fullscreen`/`minimized`, `above`), `keep_open`, `stop_signal` (`TERM`, `INT`, `HUP`), `wait_desktop` (default `2m`) | Opens an installed application in your desktop session, waiting up to `wait_desktop` for one. It runs as a unit of its own (`app-powerclock-….service`), so it sees your screen even if PowerClock started before you logged in. `window` places it (KDE Plasma); `keep_open` opens it again if it closes (at most 3 times an hour). |
| `open` | `target` | Opens a file or URL with your default application. |
| `close_app` | `name` and `signal` (`TERM`, `INT` or `HUP`), or `app`; `timeout` (default `30s`) | Asks your programs with that name to quit, or closes the instances of `app` that PowerClock opened; kills them after `timeout`. |
| `notify` | `title`, `body` | A desktop notification (skipped on a computer without a desktop). |
| `wait` | `duration` | Waits. |
| `wait_until` | `condition` (a predicate), `timeout` (optional) | Waits until the condition holds; fails after `timeout`. |
| `set_wake` | `when` or `after` | Programs a wake-up (e.g. "wake me up again in 8 h"). |

**Variables**: in `run` (`cmd`, `cwd`, `env`), `launch` (`args`), `open` and `notify`,
`{date}` (2026-09-25), `{time}` (07-30), `{datetime}` (2026-09-25_07-30), `{weekday}` (thu),
`{rule}` (its id), `{home}` and `{data}` (PowerClock's data folder) are replaced when the step
runs, e.g. `ffmpeg -i URL -t 2h radio-{date}.mp3`. Any other braces stay as they are. `run` also
gets the variables of your desktop session, so a program with a window finds your screen.

If a step fails, the rule stops (`"on_error": "stop"`) or goes on with the next one
(`"continue"`); the history says which step failed and why. The same rule never runs twice at the
same time, and only one power action (and one countdown) happens at a time.

### Options

| Field | Default | Meaning |
|---|---|---|
| `warning` | `60s` | Countdown before each power action (`0s` for none). |
| `wake` | `false` | Turn the computer on for this rule (only with `at`, `countdown` or `cron`). |
| `log_in` | `null` | With `wake`: log in by itself when that turns the computer on from off, leaving the screen `locked` or `unlocked` (see below). |
| `on_missed` | `skip` | If its moment passed while the computer was off or asleep (more than 2 minutes late): `skip` or `run_once`. |
| `on_error` | `stop` | `stop` or `continue` when a step fails. |
| `one_shot` | `false` | Disable the rule after it fires once. |
| `dry_run` | `false` | Only log this rule's power actions. |
| `timezone` | the computer's | IANA name (`Europe/Madrid`) for `cron`, `time_window` and `weekday`. |

### The examples

| File | What it does |
|---|---|
| [`backup-nocturno.json`](examples/backup-nocturno.json) | Turns on at night, runs a backup if on AC and nobody is watching a video or connected by SSH, waits for the network to calm down, notifies and shuts down. |
| [`buenos-dias-laborables.json`](examples/buenos-dias-laborables.json) | Turns on at 07:30 on weekdays and opens the calendar; if the computer was off at that time, runs once when it can. |
| [`suspender-inactivo.json`](examples/suspender-inactivo.json) | Suspends after 20 idle minutes, but not while media plays, someone is connected by SSH or the CPU is busy. |
| [`apagar-al-terminar-ffmpeg.json`](examples/apagar-al-terminar-ffmpeg.json) | Shuts down when ffmpeg finishes, once. |
| [`apagar-tras-descarga.json`](examples/apagar-tras-descarga.json) | Shuts down when the download traffic stays below 50 kbit/s for 5 minutes. |

## Turning the computer on and waking it up

Computers have a hardware clock (RTC) with **one** alarm that can wake them from suspend and, if
the BIOS/UEFI allows it, power them on from off. PowerClock manages that alarm for you:

- It works out the next wake-up needed by your rules (`"wake": true`, `--wake`, `powerclock wake`) and
  programs it **2 minutes early**, so the daemon is ready on time. It reprograms it whenever rules
  change, after each run and right before the computer suspends or shuts down.
- It never moves an earlier alarm that is not its own, and it leaves its alarm in place when the
  daemon stops (it must still turn the computer on).
- Writing the alarm needs root, so a **tiny helper** does only that: `powerclock helper install` copies it
  to `/usr/local/libexec/powerclock-helper` with a polkit policy. It asks for your password **once**;
  after that wake-ups need no password while you are logged in (even with the screen locked). It
  only accepts "set / clear / read the alarm", validates the time strictly and runs `rtcwake`
  with an absolute path and a clean environment.
- **Logging in by itself** (`"log_in": "locked"`, `--log-in`, *and log in* in the Quick tab):
  programs with a window need a desktop session, and after powering on from off the computer
  waits at the login screen. PowerClock never turns on automatic log-in for good. Instead, the
  helper keeps a **one-time ticket** with the alarm's time for **your** user (the one who asked,
  never another account or root). At boot, before the login screen, `powerclock-boot.service`
  looks at it: only if this boot is that alarm's (from the alarm to 10 minutes later, and not
  switched on with the power button when the BIOS tells) does it write the automatic log-in to
  `/run` (memory), where the display manager's settings point. PowerClock then **locks the
  screen** at once (unless the rule says `unlocked`, for a kiosk with a user of its own) and
  removes that setting. Any other start-up asks for your password as usual, and a power cut
  leaves nothing behind. Works with SDDM (KDE) and LightDM; GDM not yet. The alarm goes 3 minutes
  early instead of 2. With automatic log-in the KDE wallet does not open: the browser recipes use
  a profile of their own that does not need it.
- **Unattended mode** (turn on → run → shut down with nobody logged in):
  `powerclock helper install --unattended` adds a polkit rule for your user, and
  `powerclock service install --linger` keeps the daemon running without a login.

**Try it**: `powerclock doctor --test-wake 120` (or *Test a wake-up in 2 minutes* in Diagnostics)
suspends the computer and checks that it wakes up by itself; it also tells you what woke it if it
was something else. Things learnt on a Dell Latitude 5480:

- A touchpad or pointing stick can wake a laptop the moment it suspends: keep your hands off
  during the test (PowerClock gives you 10 seconds).
- Waking from suspend worked out of the box (2 s after the alarm).
- Powering on from **off** worked too, on AC power, with the BIOS defaults (the kernel was
  starting 14 s after the alarm). Many laptops need AC for this, and some BIOSes need
  *Power Management → Auto On Time* (Dell) or a similar option; `powerclock doctor` gives a hint for
  your brand.

## Conditions and sensors

PowerClock only reads the sensors your rules use: with no rule watching the CPU, it never reads the CPU.

- **Idle time** comes from the desktop: on Wayland through `ext-idle-notify` (KDE Plasma, Sway,
  Hyprland…), on GNOME through Mutter, otherwise from logind, and on X11 with `xprintidle`. On
  Wayland only the keyboard and the mouse count: a film playing does not keep the computer "in
  use", so add a `media_playing` guard to idle rules (as the examples do).
- **CPU and network** are sampled every 5 seconds; `cpu_below` and `net_below` use the **average**
  of the last `for`, so a 5-second spike does not break a 5-minute average, but real work does.
  Until PowerClock has measured the whole `for` (e.g. the first 5 minutes after you create the rule), the
  value is unknown; a gap in the samples (a suspend) starts the measurement again. `net_below`
  without `interface` adds up the physical interfaces (not `lo`, Docker or virtual bridges); with
  `direction: both`, download + upload.
- **Programs** are listed every 3 seconds; **battery and AC** every 5; **SSH sessions** every 10.
- **Media** comes from MPRIS (any player that shows up in your desktop's media controls) and
  **Wi-Fi** from NetworkManager.
- `powerclock status` and the window show what each watching rule sees right now.

## Safety

- **Nothing turns off without warning**: every power action has a cancellable countdown (unless
  you set `warning: 0s`), with buttons in a notification and in a window, plus `powerclock cancel`.
- **Graceful by default**: on KDE and GNOME, shutting down, restarting and logging out go through
  the session manager so applications can ask to save. `force` is only used when you ask for it.
- **Test mode** (*dry run*) everywhere: per quick action (`--dry-run`), per rule (`"dry_run":
  true`), for the whole daemon (`powerclock service install --dry-run`, `"dry_run": true` in
  `daemon.json`, or `POWERCLOCK_DRY_RUN=1`). Power actions and alarms are then only noted down; the
  rest still runs.
- **Wait while…** (*guards*) prevents acting at a bad moment (a render, a video, an SSH session…).
- **Least privilege**: the daemon runs as your user. Only the wake helper runs as root, it only
  touches the RTC alarm, and it is installed by you with the exact commands shown first.
- **Private API**: it only listens on `127.0.0.1` and needs a token stored in a file only your
  user can read.
- `run` executes programs **without a shell** unless you set `"shell": true`.
- Everything that ran, was skipped or postponed is in the history, with the reason.

## Using it on a server

On a computer without a desktop (a VPS, a home server):

```bash
pipx install powerclock                   # without the window
powerclock service install --linger       # the daemon keeps running without anyone logged in
powerclock doctor
```

Everything works from the command line; notifications are skipped. Examples: restart every Sunday
at 05:00 with a cron rule, restart when a long job finishes (`powerclock reboot --when-exits
my-job`), run maintenance scripts on a schedule. Waking up from off is usually not available on
virtual machines.

## Files and settings

| File | What it is |
|---|---|
| `~/.config/powerclock/rules.json` | Your rules (`{"version": 1, "rules": [ … ]}`). You can edit it by hand: the daemon reloads it within 2 seconds. If it has an error, the daemon keeps the last good rules, shows the error in `powerclock status` and does not write the file until you fix it, so your edit is never lost. |
| `~/.config/powerclock/daemon.json` | Daemon settings: `port` (default `47831`), `dry_run` (`false`), `log_level` (`info`). |
| `~/.config/powerclock/api.token` | The API's secret token (readable only by you). |
| `~/.local/share/powerclock/history.sqlite` | The history of runs. |
| `~/.config/systemd/user/powerclock.service` | The user service (`powerclock service install`). |
| `~/.local/share/applications/powerclock.desktop`, `~/.config/autostart/powerclock-gui.desktop` | Menu entry and login start (Diagnostics tab). |

Environment variables: `POWERCLOCK_DRY_RUN=1` (test mode), `POWERCLOCK_HOME=/some/dir` (keep every file in one
folder, handy to experiment without touching your rules) and `POWERCLOCK_BACKEND=fake` (a simulated
computer, used by the tests).

Logs: `journalctl --user -u powerclock -f`.

## The local API

Other programs can drive PowerClock through its HTTP API on `http://127.0.0.1:47831` with the header
`Authorization: Bearer <token>` (the token is in `~/.config/powerclock/api.token`).

```bash
TOKEN=$(cat ~/.config/powerclock/api.token)
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:47831/pending
curl -s -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
     -d '{"action": "suspend", "in": "30m"}' http://127.0.0.1:47831/quick
```

| Method | Path | Use |
|---|---|---|
| GET | `/health` | Version, backend, time zone, uptime, rule errors. |
| GET · POST | `/rules` | List · create. |
| GET · PUT · DELETE | `/rules/{id}` | Read · replace · delete. |
| POST | `/rules/{id}/enable` · `/disable` · `/run` · `/cancel` · `/postpone` | Act on one rule. |
| GET | `/apps` · `/recipes` | The installed applications (with their recipes) · the recipes. |
| POST | `/quick` | A quick action: `action`, `command` or `app` (+ `args`), and `in`, `at`, `when_idle`, `when_exits`, `when_cpu_below`, `when_net_below` (+ `for`), `warning`, `mode`, `wake`, `wake_at`, `dry_run`. |
| POST | `/wake` | `{"at": "07:30"}`: turn the computer on at that time. |
| GET | `/pending` | What comes next, what is running, what is watched, the wake-up alarm. |
| GET | `/runs/{id}` | One run. |
| POST | `/runs/{id}/cancel` · `/cancel` | Cancel a run · the current countdown or next quick action. |
| POST | `/runs/{id}/postpone` · `/postpone` | Postpone (`{"delay": "10m"}`). |
| GET | `/history?limit=&offset=&rule_id=` | Past runs. |
| GET | `/capabilities` | The `powerclock doctor` report. |
| GET | `/schema/rule` | The JSON Schema of a rule. |
| WebSocket | `/events` | Live events: `run_started`, `warning_started`, `tick`, `postponed`, `cancelled`, `run_finished`, `rule_changed`, `wake_changed` (the token can also go in `?token=`). |

## Troubleshooting

- **"PowerClock is not running in the background"** — `powerclock service install` (or `powerclock service status`; logs:
  `journalctl --user -u powerclock`). To try it in the foreground: `POWERCLOCK_DRY_RUN=1 powerclock-daemon`.
- **A power action does nothing** — `powerclock doctor`: each `power.*` line says whether your system
  allows it (e.g. hibernation needs swap and `resume=`). If a rule has `dry_run` or the daemon runs
  in test mode, `powerclock status` says so.
- **Applications are not asked to save** — `powerclock doctor` → `power.graceful` shows the method found
  (KDE's `org.kde.Shutdown`, GNOME's `gnome-session-quit`); without one, logind is used directly.
- **The computer does not wake up** — run `powerclock doctor --test-wake 120` and read what woke it (or
  that it did not suspend). Check `wake.helper` and `wake.authorized` in `powerclock doctor`; from off,
  check the BIOS option and use AC power.
- **It woke up right after suspending** — a touchpad, pointing stick, mouse or keyboard set as a
  wake-up device; `powerclock doctor --test-wake` names it.
- **An idle or CPU rule never fires** — look at `powerclock status` (*Watching*): it shows what the sensor
  reads and how much of the `for` has been measured. If idle time is "unknown", your desktop does
  not expose it (see [Conditions and sensors](#conditions-and-sensors)).
- **`--when-exits` does nothing** — PowerClock waits until it sees the program running (`powerclock status`
  says "not running yet"). Check the exact process name with `ps -e`.
- **No tray icon on GNOME** — install/enable the *AppIndicator and KStatusNotifierItem Support*
  extension, or use the window.
- **My hand edit of `rules.json` is ignored** — `powerclock status` shows the error; fix it and the
  daemon loads it within 2 seconds.

### Native look on KDE

With pipx, PowerClock brings its own copy of Qt, which cannot load KDE's Breeze style, so controls are
drawn with Qt's *Fusion* style (colours, icons and dark mode still follow Plasma). For the exact
Breeze look, use your system's Qt:

```bash
sudo apt install python3-pyside6.qtwidgets python3-pyside6.qtnetwork python3-qasync qt6-svg-plugins
pipx install --system-site-packages powerclock    # without [gui]
```

## Uninstalling

*Diagnostics → Uninstall PowerClock…*, or:

```bash
powerclock uninstall            # service, menu, login start, wake-up helper (password) and the program
powerclock uninstall --purge    # …and your rules and history too
```

Installed with pipx, the last step is `pipx uninstall powerclock`.

## Development

```bash
uv sync --all-extras                     # everything, including the GUI and the dev tools
uv run pytest                            # tests (never touch the real system)
uv run ruff check --fix . && uv run ruff format .
POWERCLOCK_DRY_RUN=1 uv run powerclock-daemon --foreground    # a daemon that turns nothing off
uv run powerclock-gui
uv run python scripts/i18n.py update     # new texts into the translation catalogues
uv run python scripts/i18n.py compile
uv run python scripts/screenshots.py     # regenerate the README images
```

The design is described in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and the plan in
[docs/ROADMAP.md](docs/ROADMAP.md). The code is in `src/powerclock/`: `models.py` (rules; the source of
truth, also for the JSON Schema), `engine/` (scheduler, watcher of states, evaluator, executor,
wake planner), `sensors/`, `daemon/` (API, storage), `cli/`, `gui/` and `platform/linux/`
(everything specific to Linux). Tests run against a simulated computer and a fake clock; the few
that read the real system are marked `real` and skipped by default.

## Roadmap

- **0.1 — Linux** (now): everything above, with clearer wording and a step to **open installed
  applications** (Flatpak ones too) with recipes: Chrome as a kiosk, VLC on a loop, Okular as a
  presentation…
- **0.2**: logging in when PowerClock turns the computer on (only that boot, with the screen
  locked), media players, volume and desktop settings, the new design, phone notifications (ntfy,
  Telegram), more conditions (sunrise and sunset, calendar, files, devices, electricity tariff
  periods as an option) and turning other computers on (Wake-on-LAN).
- **0.3 — Windows** and **0.4 — macOS**.
- **1.0**: remote control (Telegram bot, web interface), several computers, MQTT/Home Assistant,
  KDE Connect, and describing rules in plain language.

## License

[GPL-3.0-or-later](LICENSE). PowerClock is free software: you can use, study, share and improve it; if
you distribute a modified version, it must stay free under the same license.
