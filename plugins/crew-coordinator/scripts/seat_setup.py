"""seat_setup: writes the one-time root install script for the signed operator seat.

What it does: embeds the root helper, event map and verifier inline in one bash script, so what he reads is what runs.
The script checks sudo and /usr/local safety, installs from a root-owned copy, makes the key, records the cutover, prints the undo.
Why: the first install must not depend on any the user-writable file at run time. He hashes the whole script file himself.
Depends on: os, re, hashlib; ../root/*.py. Interface: build(home, uid) -> script text; write(home, uid) -> (path, sha256).
"""
import hashlib
import os
import re

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "root")
FILES = (("harness_grant_helper.py", "harness-grant", "0755"), ("harness_event_map.py", "harness_event_map.py", "0644"),
         ("harness_verify.py", "harness_verify.py", "0644"))


def _src(name, home, uid):
    s = open(os.path.join(ROOT, name), encoding="utf-8").read()
    if name == "harness_grant_helper.py":
        s = s.replace("/EXCHANGE_HOME/_harness/operator-pending", os.path.join(home, "_harness", "operator-pending"))
        s = s.replace("/EXCHANGE_HOME/_harness/events.jsonl", os.path.join(home, "_harness", "events.jsonl"))
        s = s.replace("/EXCHANGE_HOME/_harness/bin/harness.py", os.path.join(home, "_harness", "bin", "harness.py"))
        s = s.replace('"home": "/EXCHANGE_HOME"', '"home": "%s"' % home)
        assert "/EXCHANGE_HOME" not in s.split("CFG = ", 1)[1].split("REQ_NAME", 1)[0], "unsubstituted placeholder"
        s = s.replace('"uid": 501', '"uid": %d' % uid, 1)
    return s

# 0.26.2: under sudo's default use_pty the signer's stdin is sudo's own pty, not his tab, so the signer cannot tell it is on the right terminal.
# This one drop-in turns use_pty off for the signer alone. It contains nothing else: no NOPASSWD, no !authenticate, no !tty_tickets.
SUDOERS_LINE = "Defaults!/usr/local/libexec/harness-grant !use_pty"
SUDOERS_FILE = "/etc/sudoers.d/harness-grant"
SUDOERS_CHECK = [
    'if [ -L /etc/sudoers.d ] || [ ! -d /etc/sudoers.d ]; then /bin/rm -rf "$T"; echo "refused: /etc/sudoers.d is missing or a symlink"; exit 1; fi',
    'if ! /usr/bin/grep -Eq "^[#@]includedir[[:space:]]+(/private)?/etc/sudoers\\.d[[:space:]]*$" /etc/sudoers; then /bin/rm -rf "$T"; echo "refused: /etc/sudoers does not include /etc/sudoers.d, so the signer setting would not apply"; exit 1; fi',
    "printf '%s\\n' '" + SUDOERS_LINE + "' > \"$T/harness-grant.sudoers\"",
    'if [ -L %s ]; then /bin/rm -rf "$T"; echo "refused: %s is a symlink"; exit 1; fi' % (SUDOERS_FILE, SUDOERS_FILE),
    'if [ -e %s ] && ! /usr/bin/cmp -s %s "$T/harness-grant.sudoers"; then echo "refused: %s already exists and differs from the signer setting; its content:"; /bin/cat %s; /bin/rm -rf "$T"; exit 1; fi' % ((SUDOERS_FILE,) * 4),
    'if ! /usr/sbin/visudo -cf "$T/harness-grant.sudoers" >/dev/null 2>&1; then /bin/rm -rf "$T"; echo "refused: visudo rejected the signer sudo setting; nothing was installed"; exit 1; fi',
    'echo "sudo setting to be installed (one line, undo: sudo rm %s):"; /bin/cat "$T/harness-grant.sudoers"; (cd "$T" && /usr/bin/shasum -a 256 harness-grant.sudoers)' % SUDOERS_FILE]
SUDOERS_INSTALL = ['/usr/bin/install -m 0440 -o root -g wheel "$T/harness-grant.sudoers" %s' % SUDOERS_FILE,
                   '/usr/sbin/visudo -c >/dev/null 2>&1 || { /bin/rm -f %s; echo "refused: sudoers failed its check after install; the signer setting was removed"; exit 1; }' % SUDOERS_FILE]


def build(home, uid):
    out = ["#!/bin/bash", "# Operator seat setup (one time, as root). Generated; read it, hash the WHOLE file yourself, then run the copy you hashed.",
           "# Undo: delete /usr/local/libexec/harness-grant /usr/local/libexec/harness_event_map.py /usr/local/libexec/harness_verify.py",
           "# /usr/local/etc/harness-grant.pub /usr/local/var/harness-grants.log /var/db/harness-grant /etc/sudoers.d/harness-grant (the one sudo setting, `sudo rm /etc/sudoers.d/harness-grant`).",
           "# Break-glass: sudo touch /usr/local/var/harness-grants.disabled",
           "set -eu", 'PATH=/usr/bin:/bin:/usr/sbin:/sbin',
           '[ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 1; }', '[ -n "${SUDO_USER:-}" ] || { echo "run with sudo from his account"; exit 1; }',
           'echo "approval 1 of 1: sudo password already given; this script installs the signer"',
           'L=$(/usr/bin/stat -f "%Su:%Sg %Lp" /usr/local); case "$L" in "root:wheel 755"|"root:wheel 775") ;; *) echo "/usr/local is not root:wheel safe: $L"; exit 1;; esac',
           '[ "${L##* }" != 775 ] || { echo "/usr/local is group-writable"; exit 1; }',
           'if /usr/bin/sudo -l -U "$SUDO_USER" 2>/dev/null | /usr/bin/grep -Eq "NOPASSWD|!authenticate|!tty_tickets|timestamp_type=global|timestamp_timeout=-|timestamp_timeout=([6-9]|[1-9][0-9])"; then echo "refused: sudoers for $SUDO_USER has NOPASSWD, !authenticate, shared or long-lived tickets"; exit 1; fi',
           'if /usr/bin/grep -rEq "^[^#]*(NOPASSWD|!authenticate|!tty_tickets|timestamp_type *= *global|timestamp_timeout *= *(-|[6-9]|[1-9][0-9]))" /etc/sudoers /etc/sudoers.d 2>/dev/null; then echo "refused: sudoers file has NOPASSWD, !authenticate, shared or long-lived tickets"; exit 1; fi',
           'T=$(/usr/bin/mktemp -d /var/root/seat.XXXXXX); /bin/chmod 700 "$T"'] + SUDOERS_CHECK
    for name, dest, mode in FILES:
        out += [f"cat > \"$T/{dest}\" <<'HARNESS_EOF_{dest}'", _src(name, home, uid).rstrip("\n"), f"HARNESS_EOF_{dest}"]
    out += ['echo "sha256 of the embedded files (compare with the critic\'s record):"; (cd "$T" && /usr/bin/shasum -a 256 harness-grant harness_event_map.py harness_verify.py)',
            "for d in /usr/local/libexec /usr/local/etc /usr/local/var; do [ ! -L \"$d\" ] || { echo \"$d is a symlink\"; exit 1; }; /usr/bin/install -d -m 0755 -o root -g wheel \"$d\"; done",
            "/usr/bin/install -d -m 0700 -o root -g wheel /var/db/harness-grant"]
    for name, dest, mode in FILES:
        out.append(f'/usr/bin/install -m {mode} -o root -g wheel "$T/{dest}" /usr/local/libexec/{dest}')
    out += SUDOERS_INSTALL
    out += ['[ -f /var/db/harness-grant/key ] || { /usr/bin/openssl genrsa -out /var/db/harness-grant/key 3072 2>/dev/null; /bin/chmod 600 /var/db/harness-grant/key; }',
            '/usr/bin/openssl rsa -in /var/db/harness-grant/key -pubout -out /usr/local/etc/harness-grant.pub 2>/dev/null; /bin/chmod 644 /usr/local/etc/harness-grant.pub',
            '/usr/bin/grep -q \'"t":"cutover"\' /usr/local/var/harness-grants.log 2>/dev/null || /usr/local/libexec/harness-grant cutover',
            '/bin/rm -rf "$T"',
            'echo "installed. Sign operator acts with the one line: sudo -k; sudo /usr/local/libexec/harness-grant approve; sudo -k. Audit: /usr/bin/python3 -I -S /usr/local/libexec/harness_verify.py <events.jsonl> /usr/local/var/harness-grants.log /usr/local/etc/harness-grant.pub"']
    return "\n".join(out) + "\n"


def write(home, uid):
    text = build(home, uid)
    d = os.path.join(home, "_harness", "operator-scripts")
    os.makedirs(d, mode=0o700, exist_ok=True)
    p = os.path.join(d, "seat-setup.sh")
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    os.chmod(p, 0o700)
    return p, hashlib.sha256(text.encode("utf-8")).hexdigest()
