# Plan for Connection Detection Implementation

## Files to Modify

1. `state/amp_state.py`
   - Add `connection_changed = Signal(bool)` signal
   - Add `set_connected(connected: bool)` method to update `self.connected` and emit signal

2. `midi/sender.py`
   - Keep `__init__` as is (do not open port immediately)
   - Add `open_port(port_name: str)` method that opens and stores MIDI output port under threading.Lock
   - Modify all send methods to check if port is open (under lock) before sending; on exception, set port to None (no-op, no exception)
   - Add `close()` method to properly close port under lock
   - Ensure sender is a single persistent instance (UI keeps reference)

3. `midi/listener.py`
   - Modify to accept an optional input port name in `__init__` (if None, use default from protocol)
   - In `run()`, if port name provided, try to open that specific port; otherwise use default behavior
   - Keep existing `connection_lost` signal on IOError/OSError
   - Ensure listener is a single persistent instance (UI keeps reference)
   - Signals to AmpState connected only once (main.py connects them once)

4. `main.py`
   - Create single persistent instances of MidiListener and MidiSender (but don't start/open yet)
   - Create `ConnectionMonitor` instance and start it
   - Connect `AmpState.connection_changed` signal to slots in midi/connection_monitor.py (or have monitor update AmpState directly)
   - ConnectionMonitor handles:
     * Port detection (prefix "NUX NMP-03")
     * Opening/closing listener and sender ports under appropriate locks
     * Starting/stopping listener thread
     * Calling state sync function on connection
   - Keep main.py minimal: just instantiation and wiring

5. `ui/main_window.py`
   - Add permanent connection indicator (small LED/dot) visible in window at all times (green when connected, red when disconnected)
   - Add persistent warning banner (InfoBar) that shows only when disconnected
   - Add brief "Connected" confirmation InfoBar that appears on reconnection and auto-dismisses after 2 seconds
   - Modify layout to include these indicators
   - Connect to `AmpState.connection_changed` to update all indicators
   - Add synchronous port check before showing window (check mido.get_input_names()/get_output_names() for prefix) to set initial state and avoid "disconnected" flash

6. Create new file: `midi/connection_monitor.py`
   - `ConnectionMonitor(QThread)` class
   - Polls every second for ports with prefix "NUX NMP-03" (input and output separately)
   - When device detected and previously disconnected:
        - Set `AmpState.connected = True` via signal (single source of truth)
        - Open MidiSender port (exact output port name found) under lock
        - Start MidiListener thread with exact input port name
        - After short delay (~300-500 ms), call state sync function to push AmpState to device
        - Show brief "Connected" confirmation
   - When device not found and previously connected:
        - Set `AmpState.connected = False` via signal
        - Stop MidiListener thread
        - Close MidiSender port under lock
        - Show persistent warning banner
   - Handles port detection and exact name resolution
   - Owns the open/close logic for ports (under locks)
   - Emits signals for connection state changes (or updates AmpState directly)

## New Components

- `ConnectionMonitor` class (in `midi/connection_monitor.py`)
  - Responsibilities:
    * Poll mido.get_input_names()/get_output_names() every ~1 second
    * Check for presence of any input port containing "NUX NMP-03"
    * Check for presence of any output port containing "NUX NMP-03"
    * When both found and previously disconnected:
        - Set `AmpState.connected = True`
        - Open sender port under lock
        - Start listener thread with resolved input port name
        - After delay, sync state to device
    * When either not found and previously connected:
        - Set `AmpState.connected = False`
        - Stop listener thread
        - Close sender port under lock
  - Does NOT recreate listener/sender instances; uses persistent instances from main.py
  - Runs in separate QThread to avoid blocking UI
  - Uses threading.Lock for safe port open/close operations

## Signal Flow

1. **Startup**
   - `main.py`: Creates single persistent `AmpState`, `MidiListener`, `MidiSender`, `ConnectionMonitor`
   - Before showing window: checks ports synchronously for prefix "NUX NMP-03"
   - If found: sets `AmpState.connected = True` (initial state)
   - If not found: sets `AmpState.connected = False`
   - `ConnectionMonitor` starts polling in background thread
   - UI shows appropriate connection indicators based on initial state

2. **Device Connected (detected by poll or startup check)**
   - `ConnectionMonitor` sets `AmpState.connected = True` and emits signal
   - UI updates: permanent indicator to green, warning banner hides
   - `ConnectionMonitor` slot (or main.py via signal):
        * Opens MidiSender port (exact output port name) under lock
        * Starts MidiListener thread with resolved input port name
        * After ~300-500 ms delay, calls state sync function to push current AmpState to device
        * Shows brief "Connected" confirmation InfoBar (auto-dismisses after 2s)
   - No signal rewiring needed (connections made once in main.py)

3. **Device Disconnected (detected by poll)**
   - `ConnectionMonitor` sets `AmpState.connected = False` and emits signal
   - UI updates: permanent indicator to red, warning banner shows
   - `ConnectionMonitor` slot:
        * Stops MidiListener thread
        * Closes MidiSender port under lock
   - Persistent warning banner remains visible until reconnection

4. **MidiListener Detects Disconnection (IOError/OSError during polling)**
   - `listener.connection_lost` emitted
   - `main.py` handler sets `AmpState.connected = False` (if not already)
   - This causes UI to update to disconnected state (if not already)
   - Note: `ConnectionMonitor` poll will also detect disconnection shortly; both paths set same state via AmpState

5. **User Interaction While Disconnected**
   - UI updates `AmpState` normally (e.g., changing presets, tuner)
   - `MidiSender` send methods check port under lock: if None (no port), do nothing (no-op, no exception)
   - No MIDI messages sent
   - Persistent warning banner remains visible

6. **Reconnection**
   - Same as device connected flow above
   - `ConnectionMonitor` detects device, sets connected=True, updates UI
   - Opens sender port, starts listener thread, after delay syncs state to device
   - Shows brief "Connected" confirmation

## Threading & Safety
- All MIDI port opening/closing and polling occurs in background thread (`ConnectionMonitor`)
- MidiListener runs in its own QThread (started/stopped by ConnectionMonitor)
- Qt UI thread only receives signals and updates widgets
- `AmpState` signals are thread-safe (QueuedConnection when emitted from background threads)
- Port open/close operations protected by threading.Lock in MidiSender and managed by ConnectionMonitor
- Proper cleanup on exit: ConnectionMonitor stopped, MidiListener stopped, MidiSender port closed

## Edge Cases Handled
- Device unplugged during MIDI send: sender detects exception under lock, sets port to None (no-op); poll will soon show disconnected
- Device plugged in while app already running: poll detects, connects, opens ports, starts listener, syncs state
- Multiple devices with similar names: uses first match (prefix-based) as originally intended
- Port name changes after reconnection (Windows index suffix): resolved by prefix polling each cycle
- Cold start without device: app starts normally, checks ports, sets initial disconnected state, waits for device
- No flash "disconnected" at startup if device is plugged in (synchronous pre-check)

## Dependencies
- No new dependencies (uses existing mido, PySide6, qfluentwidgets)
- Does not introduce MIDI dependencies in audio/loop_engine.py (separate concern)

## Atomic Commits (on feat/connection-status branch)
1. amp_state: add connection_changed signal and setter
2. midi/sender: make sender resilient with persistent instance and lock-protected port operations
3. midi/listener: modify to accept port reference and make persistent instance
4. midi/connection_monitor: implement polling thread with port open/close logic and state sync
5. main.py: instantiate persistent instances, wire up ConnectionMonitor, add synchronous startup check
6. ui/main_window.py: add permanent connection indicator, warning banner, and connected confirmation
7. utils: extract state sync function (apply_state_to_device) for reuse at launch and reconnection
8. audio: separate commit for LoopEngine handling (as requested)
9. test: verify connection/disconnection scenarios (manual test checklist later)
