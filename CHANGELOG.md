# Changelog

All notable changes to PowerClock are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased] — 0.1.0

The first release, for Linux.

### Added

- **Power actions**: shut down, restart, suspend, hibernate, hybrid sleep, lock the screen, log
  out and turn off the screen, gracefully by default (KDE and GNOME let applications ask to
  save), always after a cancellable countdown.
- **Turning the computer on**: wake-ups from suspend and power-on from off through the RTC alarm,
  planned automatically for the rules that need them, with a tiny root helper installed once
  (polkit) and an unattended mode for when nobody is logged in.
- **Rules** kept by a user daemon (systemd): triggers at a time, after a delay, on a cron
  schedule, when nobody uses the computer, when a program exits, when CPU or network traffic
  stay low, on battery level or power source changes, at start-up or after resume; conditions,
  guards that make a run wait, and steps (power, run a program, open, close a program, notify,
  wait, wait until, program a wake-up).
- **Sensors on demand** with averages over time, and a history of every run with its reason.
- **Command line** (`powerclock`): quick actions (`--in`, `--at`, `--when-idle`,
  `--when-exits`, `--when-cpu-below`, `--when-net-below`, `--wake`), status, cancel, postpone,
  history, rules, `doctor` and `doctor --test-wake`, service and helper installation.
- **Graphical interface** (`powerclock-gui`): tray icon, Quick tab, rule editor with forms and
  JSON, history, diagnostics, countdown window; English and Spanish.
- **Local API** (HTTP + WebSocket on 127.0.0.1 with a token) and a dry-run mode everywhere.
- **Installer for everyone** on Linux: download `install-powerclock.sh`, allow it to run,
  double-click it; it fetches a pinned, checksum-verified uv, installs PowerClock with its own
  Python, and opens an installation window that asks for the password once. A welcome on first
  use; updates and uninstalling from the Diagnostics tab or with `powerclock update` /
  `powerclock uninstall`; `powerclock setup` for technical users.
- **Opening applications** (`launch` step, Quick tab, `powerclock launch`): pick an installed
  app from the menu's list (Flatpak and Snap too), fill its arguments from a recipe (25 to
  start: a web page as a kiosk or an app window, a playlist on a loop, a PDF as a presentation,
  OBS recording…), place its window (KDE Plasma), keep it open if it closes, close it cleanly.
  Apps start as units of systemd's user manager, so they reach the desktop even when PowerClock
  started before the session; `run` now gets the session's variables too. `{date}`, `{time}`…
  in commands, file names and notifications; a `desktop_session` trigger and condition;
  `powerclock apps` and `powerclock recipes`.
- **A new look**: the «Next» band at the top says what PowerClock will do next and when; actions
  are buttons, "When" is a choice of four, what is scheduled shows as cards, and the countdown
  has a ring. States have their own colours ("night and dawn"), always with a symbol and a word;
  new tray icons for watching and turning on; the desktop's font on Plasma and GNOME.
- **Other computers and savings**: a `wake_lan` step and `powerclock wake-lan` turn on another
  computer on the network (Wake-on-LAN); `powerclock stats` and the History tab show the hours
  on and off and what PowerClock saved by shutting down and suspending (kWh and money, with
  your consumption and price or typical values).
- **More triggers and conditions**: at sunrise or sunset (computed offline), before calendar
  events (any `.ics` address or file, with repeating events), after some time in use without a
  break or in total today, when a file appears, a device is plugged in, the Wi-Fi changes or a
  sensor gets too hot; conditions for public holidays and, only for time-of-use contracts, the
  electricity tariff period (Spain 2.0TD, `powerclock tariff`).
- **Messages and answers**: a `push` step sends to your phone (ntfy, Telegram) or any webhook;
  an `ask` step waits for a button (and reminds you again every few minutes); "if a step fails"
  steps get the `{error}`. Tokens live in `secrets.json`, never in the rules
  (`powerclock secrets`).
- **Sound, media players and the desktop** as steps: control a media player (MPRIS), set the
  volume (with a gradual fade), play a sound or say a text aloud, change the theme, wallpaper,
  brightness or power profile, connect a VPN or switch Wi-Fi, keep the screen on and silence
  notifications for a while, and take a screenshot for the history.
- **Logging in by itself after a scheduled power-on** (`log_in` in a rule, `--log-in`, "and
  log in" in the Quick tab): a one-time ticket for the calling user that the root helper uses
  at boot, before the login screen, only if this boot is that alarm's (and not the power
  button, when the BIOS tells). The display manager's setting goes to /run and is removed once
  PowerClock has locked the screen. SDDM and LightDM.
- **Plain words** in the interface (English and Spanish): the Quick button says what it will do
  (*Schedule shutdown*, *Shut down now*), the warning says what is about to happen (*The computer
  will shut down in 42 s*), the rule editor asks *When*, *Only if…*, *Wait while…* and *What it
  does*, Diagnostics names every check, and the technical words (daemon, dry run, helper,
  unattended, guards, triggers) stay in the command line and in `rules.json`.
