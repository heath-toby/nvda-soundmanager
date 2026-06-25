# NVDA Sound Manager

A maintenance fork of [yplassiard/nvda-soundmanager](https://github.com/yplassiard/nvda-soundmanager), updated for current NVDA versions.

## Credits

All original work by:

- Yannick Plassiard
- Danstiv
- Beqa Gozalishvili

This fork only modernises the add-on for NVDA 2024.4+ — see *What's new* below.

## Introduction

Sound Manager lets NVDA users adjust per-application audio volume directly from the keyboard via a layered shortcut.

## Shortcuts

Press **NVDA+Shift+V** to enter Sound Manager mode (a high beep confirms activation). While active:

| Key | Action |
|---|---|
| Up arrow | Increase volume of the selected app |
| Down arrow | Decrease volume of the selected app |
| Left arrow | Previous app (announces "{app}: Volume {N}") |
| Right arrow | Next app (announces "{app}: Volume {N}") |
| M | Mute / unmute the selected app |
| O | Open the per-app output device menu (only when an app is selected, not Master volume) |
| D | Open the system default output device menu |
| Control+Up arrow | Increase the focused window's app volume |
| Control+Down arrow | Decrease the focused window's app volume |
| Control+M | Mute / unmute the focused window's app |
| Escape | Exit Sound Manager mode (a low beep confirms) |
| NVDA+Shift+V | Also exits the mode |

### Output-device sub-menus (O and D)

Inside either sub-menu (a high 1760 Hz beep marks the entry):

| Key | Action |
|---|---|
| Up / Down arrow | Move between devices. NVDA's own audio is temporarily routed through the highlighted device so you hear the device name *through* the device — instant confirmation that it works. |
| Enter | Save the selection and return to the main layered mode |
| Escape | Cancel; revert any preview routing |

The **O** menu includes a top entry called **Default** which clears the per-app override so the app follows the system default again.

## Settings

A "Sound Manager" panel in NVDA's settings dialog offers:

- **Announce volume changes** — speak the new percentage after up/down adjustments
- **Announce app names when cycling** — speak app name + current volume when using left/right

## What's new

- **Per-app output device routing (O)** — pick which playback device an app uses, exactly like the Windows "App volume and device preferences" page. Persists across app restarts.
- **System default output device switching (D)** — change the system default playback device without leaving NVDA.
- **Live preview** — while moving between devices in either sub-menu, NVDA's speech is routed through the highlighted device so you hear its name through it. A direct ear-test that the device is connected and audible.
- Compatibility with NVDA 2024.4 and later (Python 3.11/3.13, 64-bit)
- Removed bundled 32-bit `psutil` and obsolete Python 2 backports — uses NVDA's bundled `pycaw` and `psutil` directly
- Fixed `GlobalPlugin.__init__` super() call that skipped the parent initializer
- Cycle between apps now wraps cleanly in both directions and de-duplicates sessions sharing an executable name
- Left/right cycling announces both app name and current volume, e.g. "VLC: Volume 86"
- Hardware volume keys are no longer intercepted — they pass through to Windows
