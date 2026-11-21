# Handheld integration reliability

The original experiments started from the Home Assistant 0.1.3 handheld build. The current integration includes the action lifecycle changes. The state patches remain an offline proof of the read-only screen exchange.

## Reproduce the tests

Use the [Home Assistant test environment](remote-design.md#verify-the-implementation) and run the action tests against the current source.

```sh
python -m unittest discover -s tests -p test_offline_action_lifecycle.py -v
```

The [archived source patches](../tests/fixtures/handheld-v013) include the original action and the two state experiments. They apply in that order to the historical 0.1.3 handheld snapshot. The state tests use `HANDHELD_DSP_FIXTURE` to locate the [Climate C fixture](../firmware/dsp-v48-native-menu/climate_smoke.c). Before the action fix, the baseline could wait on a version reply after the link dropped, report readiness until a delayed disconnect callback, or finish unloading before a pending disconnect completed.

The action tests drive a real isolated Home Assistant config entry, temporary store, and integration event and task paths through a simulated Bluetooth client. They cover late notifications, duplicates within a connection, reused timestamps after reconnect, presses queued at link loss, repeated recovery, and TV and Controls profiles across unload and reload. The test records each accepted effect at the dispatch boundary and fails if a Home Assistant service is invoked. A write already handed to an external service before a disconnect is outside that boundary. The existing history tracks 128 exact key frames per connection.

The state tests feed `climate.home`, `light.living_room`, `cover.living_room_blinds`, and `fan.ceiling` through the isolated Home Assistant state registry and event bus. The simulated transport delivers frames directly to the host build of the DSP Climate parser. Coverage includes coalescing a 100-event burst, °C and °F, unavailable or invalid readings, sequence gaps and stale display data, reconnect with a fresh snapshot, scope changes, and rejected write attempts. Bluetooth delivery, embedded execution, and physical display behavior remain unverified by this fixture.

## State provider contract

Create one provider per active link with `Remote.make_state_provider(client, activation, send)`. Home Assistant owns the field map, with `climate.home` on screen `0x04` by default. The transport supplies `send(client, frame)` and must deliver bytes only to the supplied active client. On the Home Assistant loop, pass validated logical `OPEN` or `CLOSE` frames to `provider.async_receive(frame)`. Call `provider.async_close()` on link loss and entry unload to detach the listener and cancel any timer or pending send.

Each accepted `OPEN` produces a fresh snapshot with sequence zero. Deltas use the same screen generation and advance the sequence. Changes to several fields are combined into the latest values, with at most one writer and deltas spaced at least 250 ms apart. Invalid values are encoded as unavailable. The transport must respect the protocol's frame limits and prevent old frames from crossing connection boundaries. See the [DSP frame specification](../firmware/dsp-v48/PROTOCOL.md#proposed-screen-snapshots-and-state-updates).

The stock GATT path remains disconnected from this provider. On-device state needs a verified inbound carrier through the stock ARM firmware that delivers bounded frames to DSP RAM without persisting them, with a reliable way to identify the current connection.
