#!/usr/bin/env python3
"""Exercise Home Assistant with the same MQTT messages as the remote."""

import argparse
from getpass import getpass
import json
from threading import Event, Lock
from time import perf_counter

import paho.mqtt.client as mqtt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host", help="MQTT broker hostname")
    parser.add_argument("remote_id", help="Remote ID from the integration's setup")
    parser.add_argument("--port", type=int, help="Defaults to 1883, or 8883 with TLS")
    parser.add_argument("--username", help="MQTT username. Prompts for the password.")
    parser.add_argument("--tls", action="store_true", help="Use the system's trusted certificates")
    args = parser.parse_args()
    prefix = f"ununiversal_remote/{args.remote_id}"
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    if args.username:
        client.username_pw_set(args.username, getpass("MQTT password: "))
    if args.tls:
        client.tls_set()

    lock = Lock()
    ready = Event()
    screen = None
    pending = None

    def on_connect(client, userdata, flags, reason, properties):
        if reason.is_failure:
            print(f"Broker rejected the connection: {reason}", flush=True)
            return
        client.subscribe([(f"{prefix}/screen", 0), (f"{prefix}/ir", 0)])

    def on_subscribe(client, userdata, mid, reasons, properties):
        if any(reason.is_failure for reason in reasons):
            print("The broker denied a screen or IR subscription.", flush=True)
        else:
            client.publish(f"{prefix}/ready", "{}")

    def on_disconnect(client, userdata, flags, reason, properties):
        nonlocal screen, pending
        with lock:
            screen = pending = None
            ready.clear()

    def on_message(client, userdata, message):
        nonlocal screen, pending
        try:
            payload = json.loads(message.payload)
            if message.topic == f"{prefix}/ir":
                print(f"IR · {payload['command_id']}", flush=True)
                return
            screen_id, token, title, body, buttons = (
                payload[name] for name in ("screen_id", "screen_token", "title", "text", "buttons")
            )
            labels = " | ".join(buttons.get(f"soft_{index}", "…") for index in range(1, 5))
        except (KeyError, ValueError, TypeError, AttributeError):
            return
        with lock:
            elapsed = ""
            if pending and pending[0] != token:
                elapsed = f" · {(perf_counter() - pending[1]) * 1000:.1f} ms from press"
                pending = None
            screen = (screen_id, token)
            print(f"\n{title} [{screen_id}]{elapsed}", flush=True)
            if body:
                print(body, flush=True)
            print(labels, flush=True)
            ready.set()

    client.on_connect = on_connect
    client.on_subscribe = on_subscribe
    client.on_disconnect = on_disconnect
    client.on_message = on_message
    client.connect(args.host, args.port or (8883 if args.tls else 1883))
    client.loop_start()
    try:
        if not ready.wait(5):
            print("Waiting for a screen. Use 'ready' to request it again.")
        print("Keys: soft_1 … soft_4, channel_up, channel_down, volume_up, volume_down")
        print("Add a repeat count, e.g. 'channel_up 3'. Use 'ready' to resync or 'quit' to exit.")
        while True:
            try:
                line = input("> ").split()
            except (KeyboardInterrupt, EOFError):
                break
            if not line:
                continue
            if line[0] == "quit":
                break
            if line[0] == "ready":
                client.publish(f"{prefix}/ready", "{}")
                continue
            if len(line) > 2 or (len(line) == 2 and (not line[1].isascii() or not line[1].isdecimal()
                            or len(line[1]) > 2 or not 1 <= int(line[1]) <= 32)):
                print("Enter one button ID with an optional repeat count from 1 to 32.")
                continue
            with lock:
                if screen is None:
                    print("Request a screen first with 'ready'.")
                    continue
                payload = json.dumps({"screen_id": screen[0], "screen_token": screen[1], "button_id": line[0]})
                pending = (screen[1], perf_counter())
                for _ in range(int(line[1]) if len(line) == 2 else 1):
                    client.publish(f"{prefix}/press", payload)
    finally:
        client.disconnect()
        client.loop_stop()


if __name__ == "__main__":
    main()
