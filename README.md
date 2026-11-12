# RDS Pi Kiosk

> **Beta (pre-release).** Please report problems in Issues.

A free, open-source Raspberry Pi OS image that boots straight into a locked-down,
full-screen web kiosk. Flash it, set a URL, and plug the Pi into a screen.

- **Free mode:** shows any web page you choose, full screen, with no desktop, no
  browser bars, and no pop-ups. Set it up from your phone or in a text file on the SD card.
- **Pair with RDS:** one tap turns the screen into an [RDS](https://www.digitalsignagerds.com/?utm_source=rds-pi-kiosk&utm_medium=free-tool&utm_campaign=pi-kiosk-image&utm_content=readme)
  digital-signage player, with playlists, schedules and every screen in one dashboard.

Supported boards: Raspberry Pi 5, Pi 4, Pi 400, CM4 and CM5 (64-bit). Connect an
HDMI screen and use Ethernet or Wi-Fi.

## Quick start

1. Download `rds-pi-kiosk-<version>-arm64.img.xz` from
   [Releases](https://github.com/promotienda/rds-pi-kiosk/releases) and check
   its SHA-256 (and, once published, its signature: see *Verifying a download*).
2. Write it to a microSD card (8 GB or larger) with Raspberry Pi Imager
   (*Choose OS → Use custom*) or balenaEtcher. In Imager's OS customisation you
   can set Wi-Fi, a user with a password, and SSH. All of it is optional.
3. Optional: open the card's boot partition on your computer and edit `kiosk.txt`
   (for example `URL=https://example.com`).
4. Put the card in the Pi, connect the screen and the network, and power it on.

If no URL is set, the screen shows a **welcome page**. It has a setup address
(`http://<the Pi's IP>/`), a QR code and a setup code. Open that address on a
phone or computer on the same network and enter the code. There you can set the
URL, rotation and zoom, or choose **Pair with RDS**.

## kiosk.txt

`kiosk.txt` is on the FAT boot partition, the one any computer can read. Write
one `KEY=VALUE` per line. Lines that start with `#` are notes. If a value has a
typo, the Pi ignores it and keeps the last working value, so a typo never turns
the screen off.

| Key | Default | |
|---|---|---|
| `URL` | *(empty → welcome page)* | `http://` or `https://` page to show |
| `MODE` | `free` | `rds` = install the RDS agent and pair (needs internet) |
| `ROTATION` | `0` | `0`, `90`, `180`, `270` |
| `ZOOM` | `1.0` | page zoom, `0.25`–`5` |
| `WIFI_SSID`, `WIFI_PASSWORD`, `WIFI_COUNTRY` | | the password is removed from the file once saved |
| `TIMEZONE` | UTC | e.g. `Europe/Madrid` |
| `HOSTNAME` | `rds-kiosk` | |
| `SETUP_PAGE` | `on` | `off` = no setup page on the network |
| `SETUP_CODE` | random | your own 6–32 letters/digits |
| `SSH_AUTHORIZED_KEY` | | one OpenSSH public key: enables key-only SSH for `kioskadmin` |
| `AUTO_SECURITY_UPDATES` | `yes` | automatic updates (see Security notes), never an automatic reboot |

## Pair with RDS

Pairing runs RDS's public installer. It downloads the latest RDS agent for arm64,
checks its SHA-256 against the value RDS publishes, and installs it with apt.
Then the screen switches to RDS mode and shows a QR code that links it to your
RDS account. Its open-source dependencies are already in the image, so this
takes about a minute.

- The RDS agent is **not** part of this image. It is only downloaded if you choose to pair.
- After pairing, agent updates are offered in RDS. Nothing updates the agent
  automatically: you choose when, in RDS.
- `MODE=free` in `kiosk.txt` goes back to showing your own URL. The agent stays
  installed and paired, so `MODE=rds` brings it back.
- If pairing fails (no internet, for example), the screen keeps working in free
  mode and shows the reason.

## How it works

| Piece | What it does |
|---|---|
| `rds-kiosk.service` | [cage](https://github.com/cage-kiosk/cage) (a Wayland kiosk compositor) runs Chromium in `--kiosk` mode on tty1, as the unprivileged user `kiosk`. It restarts if anything crashes. |
| `rds-kiosk-config.service` | applies `kiosk.txt` at every boot (`/usr/sbin/rds-kiosk-apply`) |
| `rds-kiosk-setup.service` | the setup page: Python standard library only, runs as the unprivileged user `kiosk-setup`, sandboxed by systemd |
| `rds-kiosk-request.path` | root applies setup-page changes after checking them again |
| `rds-kiosk-pair.service` | Pair with RDS (`/usr/sbin/rds-kiosk-pair`) |

Security notes:

- The setup page needs the setup code, which is shown only on the screen itself.
  It accepts only JSON with a Host header that names this device, so other web
  pages cannot reconfigure it, and it locks for 10 minutes after 10 wrong codes.
  Over the network it can change only the URL, rotation and zoom. Wi-Fi, SSH and
  the mode are set in `kiosk.txt`.
- Chromium is locked by policy: no downloads, `file://`, `chrome://`, developer
  tools, extensions, password manager or sign-in.
- No account has a usable password unless you create one in Raspberry Pi Imager
  or set `SSH_AUTHORIZED_KEY`. tty1 belongs to the kiosk, and VT switching is off.
- A hardware watchdog reboots the Pi if the system hangs.
- Updates install automatically. In free mode that means Debian security
  updates and the Raspberry Pi archive (all of it, including Chromium, not only
  security fixes). Once paired with RDS it means Debian security updates only.
  They never touch the kernel, the boot firmware or bootloader, or the RDS
  agent, and never reboot the Pi. Wi-Fi/Bluetooth firmware may update like any
  other package. `AUTO_SECURITY_UPDATES=no` in `kiosk.txt` turns them off.

## Verifying a download

Each release has `<file>.sha256`:

```
sha256sum -c rds-pi-kiosk-<version>-arm64.img.xz.sha256      # Linux
shasum -a 256 -c rds-pi-kiosk-<version>-arm64.img.xz.sha256  # macOS
```

Releases will also carry a [minisign](https://jedisct1.github.io/minisign/)
signature, `<file>.minisig`. **Signature pending:** the project key has not
been published yet. When it is, its public key will be here:

```
RDS Pi Kiosk release key (minisign): PENDING
```

and you can check a download with
`minisign -Vm rds-pi-kiosk-<version>-arm64.img.xz -P <public key>`.

## Building

```
sudo ./build.sh                     # or: sudo VERSION=0.1.0 ./build.sh
```

The build uses [pi-gen](https://github.com/RPi-Distro/pi-gen), pinned to
`2026-10-06-raspios-trixie-arm64`. It runs pi-gen stages 0–2 (Raspberry Pi OS
Lite) and then this repository's `stage-kiosk`. It needs a Debian or Ubuntu host,
about 15 GB of free disk and 1–2 hours. `build.sh` lists the packages to install
first. The output, `deploy/rds-pi-kiosk-<version>-arm64.img.xz`, comes with
`.sha256` and `.info` files.

`tests/run.sh` runs the unit tests on any machine with Python 3.

## Licence

MIT for the build scripts and files in this repository (see `LICENSE`).
Images built from them contain Raspberry Pi OS and Debian packages, each under
its own licence (see `/usr/share/doc/*/copyright` in the image). pi-gen is
BSD-3-Clause. The RDS agent is not part of this repository or of the image: it
is downloaded from RDS, under RDS's terms, only when you choose "Pair with RDS".

Raspberry Pi is a trademark of Raspberry Pi Ltd. This project is not affiliated
with or endorsed by Raspberry Pi Ltd.
