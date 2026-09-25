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
- **Plain words** in the interface (English and Spanish): the Quick button says what it will do
  (*Schedule shutdown*, *Shut down now*), the warning says what is about to happen (*The computer
  will shut down in 42 s*), the rule editor asks *When*, *Only if…*, *Wait while…* and *What it
  does*, Diagnostics names every check, and the technical words (daemon, dry run, helper,
  unattended, guards, triggers) stay in the command line and in `rules.json`.
