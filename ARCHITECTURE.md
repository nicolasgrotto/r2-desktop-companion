# R2 Desktop Companion architecture

[Português (Brasil) · Detailed reference](ARCHITECTURE-pt-br.md)

## Runtime and entry points

`run_companion.py` and the portable executable both enter through `r2_companion.app.main`. The Qt application acquires the profile lock, loads preferences and language, and constructs the `Companion` coordinator. Its components share one Qt event loop. The updater runs in a separate process, and optional Windows media integration uses a worker thread.

| Area | Responsibility |
| --- | --- |
| [app.py](src/r2_companion/app.py) | Wires together services, desktop windows, and action callbacks. Owns startup, restart, and shutdown. |
| [core](src/r2_companion/core) | Preference models, the action registry, and localization. |
| [pet and droids](src/r2_companion/pet) · [profiles](src/r2_companion/droids) | Character states, animation, movement, behaviors, and resources. |
| [features](src/r2_companion/features) | Countdown, focus, projections, productivity, backups, and personal minigames. |
| [services](src/r2_companion/services) | Windows integration, audio, storage, media, and updates. |
| [ui](src/r2_companion/ui) | Qt windows for the mascot, overlays, action wheel, settings, and tools. |

## Desktop behavior and actions

`PetController` drives animation and movement. `ReactionDirector` prioritizes explicit interactions, completions, contextual reactions, and autonomous actions. Animation and movement tokens discard callbacks from interrupted actions. `Positioning` constrains placement to monitor work areas and handles monitor changes. Window avoidance and fullscreen corner return use shorter travel times than normal walks.

`PresencePolicy` combines the selected mode with focus, quiet hours, fullscreen, suspension, and reduced motion. The runtime adapter applies the resulting permissions to movement, sound, effects, and visibility. The action wheel pauses autonomy while letting active projections and explicit click audio continue.

The wheel, context menu, keyboard search, and optional global shortcut dispatch through the action registry. `WindowLayerPolicy` coordinates always-on-top and stacking for the mascot and its overlays. Conventional panels use their own focus and window lifecycle.

## Projections, sound, and media

`ProjectionController` owns the selection and content model. `ProjectionOverlay` draws the card and beam, avoids the mascot and the visible wheel, and stays outside the input path. The Tools Center exposes the full projection text to assistive technology. Clock, timer, and focus cards update on a timer. Music cards update on media events and close when playback stops or the selected session disappears.

`AudioService` manages banks of Qt sound effects and vocalizations built from per-droid assets. Playback respects presence, volume, mute, categories, cooldowns, and the active sound. A bank is released when a profile is replaced or a preview closes.

The optional media worker wraps Windows Global System Media Transport Controls through WinRT. It publishes immutable snapshots to the Qt thread. Commands apply to the displayed session and its published capabilities, and stale responses are ignored.

## Persistence and process lifecycle

| Profile file | Contents |
| --- | --- |
| `config.json` | Core and per-droid preferences, favorites, positions, and startup settings. |
| `tools.json` | Tasks and notes. |
| `companion_state.json` | Presence, accessibility, language, themes, focus recovery, shortcuts, media opt-in, and personal minigames. |

The profile lock protects the data directory. Stores use atomic writes, local backups, and schema validation. Selective restore merges the chosen collection from the backup with the other live collection, validates the result, and saves a recovery copy before committing it.

The ordinary timer and focus use the same countdown. Focus adds a checkpoint and restores an interrupted session in a paused state. The language selector persists its choice before restarting. The new process waits for the same profile lock while the old process flushes data and shuts down.

The updater verifies the ZIP against its published SHA-256, stages a complete replacement, and keeps a backup. The new process confirms its startup identity. If that confirmation fails, the installer attempts to restore the previous bundle. Data lives outside the installed bundle.

## Build and verification

[Build from source](README.md#build-from-source) covers setup and packaging. The [test guide](tests/README.md) separates logic, Qt, and interactive Windows checks. `tools/verify_package.py` checks a relocated portable bundle in both languages, and `tools/verify_post_update.py` exercises update and recovery using actual executables.

For local diagnosis, inspect `companion.log` and `navigation.jsonl` in the active profile. Set `R2_NAV_TRACE=1` before launch to add Qt input and focus events to the navigation trace. The [Portuguese technical reference](ARCHITECTURE-pt-br.md) covers the animation transitions, native window behavior, and updater handoff in more detail.
