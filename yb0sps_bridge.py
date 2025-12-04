#!/usr/bin/env python3
# yb0sps_bridge.py
# UDP -> HTTP bridge for N1MM and JTDX/WSJT-X
# Reads config from config.ini in same folder.

import socket
import threading
import requests
import configparser
import time
import os
import xml.etree.ElementTree as ET
import json

# Load configuration
cfg = configparser.ConfigParser()
cfg.read('config.ini')

WEB_URL = cfg.get('server', 'url', fallback='http://example.com/post')
AUTH_TOKEN = cfg.get('server', 'token', fallback='ABC123')

def to_bool(s):
    return str(s).strip().lower() in ('1', 'true', 'yes', 'on')

N1MM_ENABLED = to_bool(cfg.get('n1mm', 'enabled', fallback='true'))
N1MM_PORT = int(cfg.get('n1mm', 'port', fallback='12060'))

JTDX_ENABLED = to_bool(cfg.get('jtdx', 'enabled', fallback='true'))
JTDX_PORT = int(cfg.get('jtdx', 'port', fallback='2237'))

LOG_ENABLE = to_bool(cfg.get('log', 'enable', fallback='true'))
LOG_FILE = cfg.get('log', 'file', fallback='bridge.log')

def log(msg):
    ts = time.strftime('%Y-%m-%d %H:%M:%S')
    line = f'[{ts}] {msg}'
    print(line)
    if LOG_ENABLE:
        try:
            with open(LOG_FILE, 'a', encoding='utf-8') as f:
                f.write(line + '\n')
        except Exception:
            pass

def parse_n1mm_xml(data):
    """
    Parse first-level tags from N1MM XML contactinfo/… elements.
    Returns dict of tag->text
    """
    out = {}
    try:
        root = ET.fromstring(data)
        # If root is xml declaration or non-element, ElementTree may still give element
        for child in root:
            # child.tag may include namespace; use localname if present
            tag = child.tag
            if '}' in tag:
                tag = tag.split('}', 1)[1]
            out[tag] = child.text if child.text is not None else ''
    except Exception as e:
        log(f"XML parse error: {e}")
    return out

def try_parse_json(data):
    try:
        obj = json.loads(data)
        if isinstance(obj, dict):
            return {k: str(v) for k, v in obj.items()}
    except Exception:
        pass
    return {}

def post_form(payload):
    try:
        r = requests.post(WEB_URL, data=payload, timeout=10)
        log(f"POST {WEB_URL} -> {r.status_code}")
    except Exception as e:
        log(f"POST error: {e}")

def handle_packet(source, data, addr):
    short = data if len(data) < 300 else data[:300] + '...'
    log(f"{source} from {addr} -> {short}")

    payload = {
        'source': source,
        'data_raw': data,
        'token': AUTH_TOKEN
    }

    # For N1MM, parse XML first-level fields into POST vars
    if source == 'N1MM':
        parsed = parse_n1mm_xml(data)
        for k, v in parsed.items():
            payload[k] = v if v is not None else ''
    else:
        # For JTDX/WSJT-X — try JSON then XML
        j = try_parse_json(data)
        if j:
            for k,v in j.items():
                payload[k] = v
        else:
            parsed = parse_n1mm_xml(data)  # reuse xml parser for simple xml
            for k,v in parsed.items():
                payload[k] = v

    # Send in background thread to avoid blocking UDP receive loop
    t = threading.Thread(target=post_form, args=(payload,))
    t.daemon = True
    t.start()

def start_udp_listener(port, source):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind(('0.0.0.0', port))
    except Exception as e:
        log(f"Failed to bind {source} on port {port}: {e}")
        return
    log(f"{source} listener started on UDP port {port}")
    while True:
        try:
            data, addr = sock.recvfrom(8192)
            # decode best-effort
            try:
                s = data.decode('utf-8', errors='replace').rstrip('\x00')
            except Exception:
                s = str(data)
            handle_packet(source, s, addr)
        except Exception as e:
            log(f"{source} recv error: {e}")
            time.sleep(1)

def main():
    log("yb0sps_bridge starting")
    threads = []
    if N1MM_ENABLED:
        t = threading.Thread(target=start_udp_listener, args=(N1MM_PORT, 'N1MM'), daemon=True)
        threads.append(t)
        t.start()
    else:
        log("N1MM listener disabled in config.ini")

    if JTDX_ENABLED:
        t = threading.Thread(target=start_udp_listener, args=(JTDX_PORT, 'JTDX'), daemon=True)
        threads.append(t)
        t.start()
    else:
        log("JTDX listener disabled in config.ini")

    # Keep main thread alive while child threads run
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log("Stopping (KeyboardInterrupt)")

if __name__ == '__main__':
    main()
